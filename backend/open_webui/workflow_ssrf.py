"""
SSRF guard for workflow HTTP Request nodes: only http(s) to public (non-reserved) IPs.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def validate_public_http_url(url: str) -> None:
    """
    Raise ValueError if URL must not be fetched (empty, non-http(s), private/loopback hosts, bad DNS).
    """
    s = (url or '').strip()
    if not s:
        raise ValueError('URL is empty')
    p = urlparse(s)
    if p.scheme not in ('http', 'https'):
        raise ValueError('Only http and https URLs are allowed')
    host = p.hostname
    if not host:
        raise ValueError('Missing host in URL')
    hlow = host.lower()
    if hlow in ('localhost', '0.0.0.0') or hlow.endswith('.local'):
        raise ValueError('Host not allowed')
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f'DNS resolution failed: {e}') from e
    if not infos:
        raise ValueError('No addresses resolved for host')
    for _fam, _socktype, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError(f'Target address not allowed: {ip}')
