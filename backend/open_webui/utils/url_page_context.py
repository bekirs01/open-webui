"""
Fetch public HTTP(S) pages and inject extracted text into the last user message for chat.

MVP: httpx + BeautifulSoup (no headless browser). JS-heavy sites may need Playwright later.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import Request

from open_webui.config import ENABLE_RAG_LOCAL_WEB_FETCH
from open_webui.constants import ERROR_MESSAGES
from open_webui.retrieval.web.utils import resolve_hostname, validate_url
from open_webui.utils.misc import (
    add_or_update_system_message,
    get_content_from_message,
    update_message_content,
)
from open_webui.utils.mws_gpt.registry import extract_last_user_text

log = logging.getLogger(__name__)


def validate_chat_http_url(url: str) -> None:
    """
    Reuse retrieval.validate_url (scheme, WEB_FETCH_FILTER_LIST, private IPs when RAG local fetch is off).
    When ENABLE_RAG_LOCAL_WEB_FETCH is true, validate_url skips private-IP resolution — chat fetch still
    must not target RFC1918/link-local addresses, so we always enforce that here in that case.
    """
    validate_url(url)
    if not ENABLE_RAG_LOCAL_WEB_FETCH:
        return
    import validators

    parsed_url = urlparse(url)
    hostname = parsed_url.hostname
    if not hostname:
        return
    try:
        ipv4_addresses, ipv6_addresses = resolve_hostname(hostname)
    except Exception as e:
        raise ValueError(f'{ERROR_MESSAGES.INVALID_URL}: {e}') from e
    for ip in ipv4_addresses:
        if validators.ipv4(ip, private=True):
            raise ValueError(ERROR_MESSAGES.INVALID_URL)
    for ip in ipv6_addresses:
        if validators.ipv6(ip, private=True):
            raise ValueError(ERROR_MESSAGES.INVALID_URL)

# --- Tunables (env override) ---
CHAT_URL_FETCH_ENABLED = os.getenv('CHAT_URL_FETCH_ENABLED', 'true').lower() == 'true'
CHAT_URL_FETCH_MAX_URLS = int(os.getenv('CHAT_URL_FETCH_MAX_URLS', '3'))
CHAT_URL_FETCH_TIMEOUT = float(os.getenv('CHAT_URL_FETCH_TIMEOUT', '18'))
CHAT_URL_FETCH_MAX_BYTES = int(os.getenv('CHAT_URL_FETCH_MAX_BYTES', str(2 * 1024 * 1024)))
CHAT_URL_FETCH_MAX_TEXT_CHARS = int(os.getenv('CHAT_URL_FETCH_MAX_TEXT_CHARS', '14000'))

# Skip common non-document URLs
_SKIP_HOST_SUFFIXES = (
    'localhost',
    '127.0.0.1',
)
_SKIP_PATH_HINTS = re.compile(
    r'\.(png|jpe?g|gif|webp|svg|ico|pdf|zip|mp4|mp3|wav|woff2?|ttf)(\?|$)',
    re.I,
)

_URL_RE = re.compile(
    r'https?://[^\s<>\")\]]+',
    re.IGNORECASE,
)


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = u.rstrip(').,;]\'"')
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _visible_text_from_soup(soup: BeautifulSoup) -> str:
    for tag in soup(['script', 'style', 'noscript', 'template', 'iframe']):
        tag.decompose()
    text = soup.get_text(separator='\n', strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    if len(text) > CHAT_URL_FETCH_MAX_TEXT_CHARS:
        text = text[: CHAT_URL_FETCH_MAX_TEXT_CHARS] + '\n\n[… truncated …]'
    return text


def _extract_readable_text(html: str) -> tuple[str, str]:
    """
    Prefer the DOM subtree that yields the most visible text.
    Next.js / SPA shells often expose an empty <div id="content"> — picking it alone yields
    almost no text; falling back to <body> fixes real-world contest pages (e.g. truetecharena.ru).
    """
    soup = BeautifulSoup(html, 'html.parser')
    title = ''
    if t := soup.find('title'):
        title = (t.get_text() or '').strip()

    candidates: list[tuple[str, Any]] = []
    for label, node in (
        ('article', soup.find('article')),
        ('main', soup.find('main')),
        ('role_main', soup.find(attrs={'role': 'main'})),
        ('body', soup.find('body')),
        ('id_contentish', soup.find(id=re.compile(r'content|main|article', re.I))),
        ('root', soup),
    ):
        if not node:
            continue
        sub = BeautifulSoup(str(node), 'html.parser')
        txt = _visible_text_from_soup(sub)
        candidates.append((label, txt))

    if not candidates:
        return title, ''

    _label, text = max(candidates, key=lambda x: len((x[1] or '').strip()))
    return title, text


def _walk_ld_json_strings(obj: Any, out: list[str], depth: int = 0) -> None:
    if depth > 14:
        return
    if isinstance(obj, dict):
        for k in (
            'name',
            'headline',
            'description',
            'text',
            'articleBody',
            'abstract',
            'about',
        ):
            v = obj.get(k)
            if isinstance(v, str) and v.strip() and len(v.strip()) > 12:
                out.append(v.strip())
        for v in obj.values():
            _walk_ld_json_strings(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk_ld_json_strings(v, out, depth + 1)


def _extract_supplementary_meta_and_jsonld(html: str) -> str:
    """Head/meta + JSON-LD (helps when the body is a JS shell)."""
    soup = BeautifulSoup(html, 'html.parser')
    parts: list[str] = []
    for sel in (
        ('meta', {'name': 'description'}),
        ('meta', {'property': 'og:description'}),
        ('meta', {'name': 'twitter:description'}),
    ):
        tag = soup.find(sel[0], attrs=sel[1])
        if tag and tag.get('content'):
            c = (tag.get('content') or '').strip()
            if c and len(c) > 8:
                parts.append(c)
    for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        raw = script.string or script.get_text() or ''
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        acc: list[str] = []
        _walk_ld_json_strings(data, acc)
        for s in acc:
            if s not in parts:
                parts.append(s)
    # de-dupe while keeping order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in parts:
        pl = p.lower()
        if pl in seen or len(p) < 12:
            continue
        seen.add(pl)
        uniq.append(p)
    return '\n\n'.join(uniq)


def _is_youtube_host(host: str) -> bool:
    h = (host or '').lower()
    return h in ('youtu.be', 'youtube.com', 'm.youtube.com', 'www.youtube.com') or h.endswith(
        '.youtube.com'
    )


async def _fetch_one(url: str) -> dict[str, Any]:
    out: dict[str, Any] = {'url': url, 'title': '', 'text': '', 'error': None}

    try:
        validate_chat_http_url(url)
    except Exception as e:
        out['error'] = f'invalid_or_blocked_url: {e}'
        return out

    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if any(host == s or host.endswith('.' + s) for s in _SKIP_HOST_SUFFIXES):
        out['error'] = 'local_host_skipped'
        return out
    if _SKIP_PATH_HINTS.search(parsed.path or ''):
        out['error'] = 'non_html_asset_skipped'
        return out

    headers = {
        'User-Agent': 'OpenWebUI/ChatUrlFetch/1.0 (+https://github.com/open-webui/open-webui)',
        'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8',
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(CHAT_URL_FETCH_TIMEOUT),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5),
        ) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            raw = resp.content
            if len(raw) > CHAT_URL_FETCH_MAX_BYTES:
                out['error'] = 'response_too_large'
                return out
            ctype = (resp.headers.get('content-type') or '').lower()
            if 'html' not in ctype and 'xml' not in ctype:
                # still try if server omits content-type
                if not raw.lstrip().startswith((b'<', b'\xef\xbb\xbf<')):
                    out['error'] = 'not_html'
                    return out
            html = raw.decode(resp.encoding or 'utf-8', errors='replace')
    except httpx.TimeoutException:
        out['error'] = 'timeout'
        return out
    except httpx.HTTPStatusError as e:
        out['error'] = f'http_{e.response.status_code}'
        return out
    except Exception as e:
        log.debug('url fetch failed %s: %s', url, e)
        out['error'] = f'fetch_error: {e!s}'
        return out

    try:
        title, text = _extract_readable_text(html)
        sup = _extract_supplementary_meta_and_jsonld(html)
        if sup:
            low = (text or '').lower()
            if len((text or '').strip()) < 120 or sup.lower() not in low:
                text = (f'{sup}\n\n---\n\n{text}' if (text or '').strip() else sup).strip()
        out['title'] = title
        out['text'] = text
        if not text or len(text.strip()) < 35:
            if _is_youtube_host(host):
                out['error'] = (
                    'empty_or_trivial_content (YouTube watch pages are JS-heavy; '
                    'no usable text in static HTML — paste a transcript or use Open WebUI web search)'
                )
            else:
                out['error'] = 'empty_or_trivial_content'
    except Exception as e:
        out['error'] = f'parse_error: {e!s}'
    return out


def _prepend_block(parts: list[str], result: dict[str, Any]) -> None:
    if result.get('error'):
        parts.append(
            f"### Page content from URL\n"
            f"- **URL:** {result['url']}\n"
            f"- **Status:** _(The page could not be used: {result['error']})_\n"
            f"_Answer using the URL, any quoted text in the user message, and general knowledge where helpful._\n"
        )
        return
    title = result.get('title') or '(no title)'
    text = (result.get('text') or '').strip()
    parts.append(
        f"### Page content from URL: {result['url']}\n"
        f"- **Title:** {title}\n\n"
        f"{text}\n"
    )


async def enrich_messages_with_url_pages(request: Request, form_data: dict) -> dict:
    """
    If the last user message contains HTTP(S) URLs, fetch and prepend extracted text.
    """
    if not CHAT_URL_FETCH_ENABLED:
        return form_data

    messages = form_data.get('messages')
    if not isinstance(messages, list) or not messages:
        return form_data

    last_user = extract_last_user_text(messages)
    if not last_user or 'http' not in last_user.lower():
        return form_data

    urls = _dedupe_urls(_URL_RE.findall(last_user))[:CHAT_URL_FETCH_MAX_URLS]
    if not urls:
        return form_data

    debug = os.getenv('CHAT_URL_FETCH_DEBUG', '').lower() == 'true'
    if debug:
        log.info('[url-fetch] enrichment starting; urls=%s last_user_len=%s', urls, len(last_user))

    blocks: list[str] = []
    for url in urls:
        r = await _fetch_one(url)
        if debug:
            log.info(
                '[url-fetch] %s error=%s title_len=%s text_len=%s',
                url,
                r.get('error'),
                len(r.get('title') or ''),
                len(r.get('text') or ''),
            )
        _prepend_block(blocks, r)

    if not blocks:
        return form_data

    prefix = (
        '\n\n'.join(blocks)
        + '\n\n---\n\n**User message:**\n\n'
    )

    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get('role') == 'user':
            if debug:
                _before = get_content_from_message(messages[i]) or ''
                log.info('[url-fetch] last user before inject: len=%s preview=%r', len(_before), _before[:400])
            messages[i] = update_message_content(messages[i], prefix, append=False)
            if debug:
                _after = get_content_from_message(messages[i]) or ''
                log.info('[url-fetch] last user after inject: len=%s preview=%r', len(_after), _after[:400])
            break

    form_data['messages'] = messages
    if debug:
        form_data['messages'] = add_or_update_system_message(
            '[URL_FETCH_DEBUG] URL page context was injected into the last user message.',
            form_data['messages'],
            append=True,
        )
    return form_data
