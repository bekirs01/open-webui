"""
humanizer.py — NLP-based text humanizer for OpenWebUI.

Rewrites AI-generated text to sound more natural using spaCy + NLTK.
No external APIs. All processing is local.
"""

from __future__ import annotations

import random
import re
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# One-time NLP model initialisation (lazy, with graceful fallback)
# ---------------------------------------------------------------------------

_nlp = None          # spaCy model
_wordnet_ready = False


def _ensure_nlp():
    global _nlp
    if _nlp is not None:
        return _nlp

    try:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    except OSError:
        log.info("spaCy model en_core_web_sm not found – downloading…")
        try:
            from spacy.cli import download as spacy_download
            spacy_download("en_core_web_sm")
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception as exc:
            log.warning("Could not load spaCy model: %s", exc)
            _nlp = None

    return _nlp


def _ensure_wordnet():
    global _wordnet_ready
    if _wordnet_ready:
        return
    import nltk
    for pkg in ("punkt", "wordnet", "averaged_perceptron_tagger", "omw-1.4"):
        try:
            nltk.download(pkg, quiet=True)
        except Exception:
            pass
    _wordnet_ready = True


# ---------------------------------------------------------------------------
# Static lookup tables
# ---------------------------------------------------------------------------

CONTRACTIONS: dict[str, str] = {
    "don't": "do not",
    "doesn't": "does not",
    "didn't": "did not",
    "won't": "will not",
    "wouldn't": "would not",
    "can't": "cannot",
    "couldn't": "could not",
    "shouldn't": "should not",
    "isn't": "is not",
    "aren't": "are not",
    "wasn't": "was not",
    "weren't": "were not",
    "haven't": "have not",
    "hasn't": "has not",
    "hadn't": "had not",
    "I'm": "I am",
    "I've": "I have",
    "I'll": "I will",
    "I'd": "I would",
    "you're": "you are",
    "you've": "you have",
    "you'll": "you will",
    "you'd": "you would",
    "he's": "he is",
    "she's": "she is",
    "it's": "it is",
    "we're": "we are",
    "we've": "we have",
    "we'll": "we will",
    "we'd": "we would",
    "they're": "they are",
    "they've": "they have",
    "they'll": "they will",
    "they'd": "they would",
    "that's": "that is",
    "there's": "there is",
    "here's": "here is",
    "let's": "let us",
    "who's": "who is",
    "what's": "what is",
    "it'd": "it would",
    "he'd": "he would",
    "she'd": "she would",
    "needn't": "need not",
    "mustn't": "must not",
    "shan't": "shall not",
    "ain't": "am not",
}

AI_PHRASES: list[str] = [
    r"It is important to note that[,]?\s*",
    r"It is worth (mentioning|noting) that[,]?\s*",
    r"It['']s worth (mentioning|noting) that[,]?\s*",
    r"It should be noted that[,]?\s*",
    r"Certainly[,]?\s*",
    r"Absolutely[,]?\s*",
    r"Of course[,]?\s*",
    r"Indeed[,]?\s*",
    r"In conclusion[,]?\s*",
    r"To summarize[,]?\s*",
    r"To conclude[,]?\s*",
    r"In summary[,]?\s*",
    r"As (an AI|a language model|an AI language model)[,]?\s*",
    r"I (must|want to) (emphasize|point out|clarify) that[,]?\s*",
    r"It goes without saying that[,]?\s*",
    r"Needless to say[,]?\s*",
    r"Without a doubt[,]?\s*",
    r"I would like to (point out|note|highlight) that[,]?\s*",
    r"It is (crucial|essential|vital|imperative) to (note|understand|recognize) that[,]?\s*",
    r"As we (all )?know[,]?\s*",
    r"As (previously |already )?mentioned[,]?\s*",
    r"Last but not least[,]?\s*",
]

BUZZWORDS: dict[str, str] = {
    "delve": "explore",
    "delves": "explores",
    "delved": "explored",
    "delving": "exploring",
    "leverage": "use",
    "leverages": "uses",
    "leveraged": "used",
    "leveraging": "using",
    "robust": "strong",
    "facilitate": "help",
    "facilitates": "helps",
    "facilitated": "helped",
    "facilitating": "helping",
    "utilize": "use",
    "utilizes": "uses",
    "utilized": "used",
    "utilizing": "using",
    "comprehensive": "full",
    "innovative": "new",
    "streamline": "simplify",
    "streamlines": "simplifies",
    "streamlined": "simplified",
    "streamlining": "simplifying",
    "pivotal": "key",
    "holistic": "complete",
    "transformative": "impactful",
    "synergy": "cooperation",
    "synergies": "cooperation",
    "paradigm": "approach",
    "paradigms": "approaches",
    "ecosystem": "environment",
    "scalable": "flexible",
    "actionable": "practical",
    "empower": "help",
    "empowers": "helps",
    "empowered": "helped",
    "empowering": "helping",
    "cutting-edge": "advanced",
    "state-of-the-art": "advanced",
    "game-changing": "important",
    "groundbreaking": "new",
    "unprecedented": "new",
    "endeavor": "effort",
    "endeavors": "efforts",
    "plethora": "many",
    "myriad": "many",
    "utilize": "use",
}

TRANSITIONAL_WORDS = re.compile(
    r"\b(Moreover|Furthermore|Additionally|In addition|Also)[,]?\s+",
    re.IGNORECASE,
)

# spaCy → WordNet POS map
_POS_MAP = {
    "ADJ":  "a",   # adjective
    "ADV":  "r",   # adverb
    "VERB": "v",   # verb
    "NOUN": "n",   # noun
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _protect_special_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Replace code fences, URLs, and block-quotes with placeholders."""
    placeholders: dict[str, str] = {}
    counter = [0]

    def _ph(value: str) -> str:
        key = f"PLACEHOLDER_{counter[0]}_END"
        counter[0] += 1
        placeholders[key] = value
        return key

    # Code blocks  ```...```
    text = re.sub(r"```[\s\S]*?```", lambda m: _ph(m.group()), text)
    # Inline code `...`
    text = re.sub(r"`[^`]+`", lambda m: _ph(m.group()), text)
    # URLs
    text = re.sub(
        r"https?://[^\s\)\]>\"']+", lambda m: _ph(m.group()), text
    )
    # Markdown block-quotes (lines starting with >)
    text = re.sub(
        r"^(>.*(\n|$))+", lambda m: _ph(m.group()), text, flags=re.MULTILINE
    )

    return text, placeholders


def _restore_special_blocks(text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        text = text.replace(key, value)
    return text


def _expand_contractions(text: str) -> str:
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in CONTRACTIONS) + r")\b",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        word = m.group(0)
        replacement = CONTRACTIONS.get(word) or CONTRACTIONS.get(word.lower(), word)
        # Preserve original capitalisation for the first letter
        if word[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    return pattern.sub(_replace, text)


def _remove_ai_phrases(text: str) -> str:
    for phrase in AI_PHRASES:
        text = re.sub(phrase, "", text, flags=re.IGNORECASE)
    return text


def _replace_buzzwords(text: str) -> str:
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(k) for k in BUZZWORDS) + r")\b",
        re.IGNORECASE,
    )

    def _replace(m: re.Match) -> str:
        word = m.group(0)
        replacement = BUZZWORDS.get(word) or BUZZWORDS.get(word.lower(), word)
        if word[0].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        return replacement

    return pattern.sub(_replace, text)


def _thin_transitions(text: str) -> str:
    """Remove ~50 % of transitional words like Moreover, Furthermore, …"""

    def _maybe_remove(m: re.Match) -> str:
        return "" if random.random() < 0.5 else m.group(0)

    return TRANSITIONAL_WORDS.sub(_maybe_remove, text)


def _get_wordnet_synonym(word: str, pos: str) -> str | None:
    """Return a synonym for *word* from WordNet (same POS), or None."""
    try:
        from nltk.corpus import wordnet as wn
    except ImportError:
        return None

    synsets = wn.synsets(word, pos=pos)
    candidates: list[str] = []
    for syn in synsets:
        for lemma in syn.lemmas():
            name = lemma.name().replace("_", " ")
            if name.lower() != word.lower() and " " not in name:
                candidates.append(name)

    return random.choice(candidates) if candidates else None


def _smart_synonym_swap(text: str, intensity: float, nlp) -> tuple[str, int]:
    """Use spaCy POS tags + WordNet to swap content words. Returns (new_text, num_changed)."""
    _ensure_wordnet()

    try:
        from nltk.corpus import wordnet  # noqa: F401 — just to verify it's present
    except ImportError:
        return text, 0

    doc = nlp(text)
    changed = 0
    result_tokens: list[str] = []

    for token in doc:
        wn_pos = _POS_MAP.get(token.pos_)
        if (
            wn_pos
            and not token.is_stop
            and not token.is_punct
            and not token.is_space
            and len(token.text) > 3
            and random.random() < intensity
        ):
            synonym = _get_wordnet_synonym(token.text, wn_pos)
            if synonym:
                # Preserve capitalisation
                if token.text[0].isupper():
                    synonym = synonym[0].upper() + synonym[1:]
                result_tokens.append(token.text_with_ws.replace(token.text, synonym, 1))
                changed += 1
                continue
        result_tokens.append(token.text_with_ws)

    return "".join(result_tokens), changed


def _split_long_sentences(text: str) -> str:
    """Break sentences > 25 words by splitting near the midpoint comma or conjunction."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []

    for sent in sentences:
        words = sent.split()
        if len(words) <= 25:
            result.append(sent)
            continue

        mid = len(words) // 2

        # Look for a comma within ±8 words of the midpoint
        best_split = None
        for delta in range(8):
            for offset in (mid + delta, mid - delta):
                if 0 < offset < len(words):
                    joined = " ".join(words[:offset])
                    if joined.rstrip().endswith(","):
                        best_split = offset
                        break
                if best_split is not None:
                    break
            if best_split is not None:
                break

        # Fall back to splitting at a conjunction near the midpoint
        if best_split is None:
            conjunctions = {"and", "but", "or", "so", "yet", "while", "although",
                            "because", "since", "when", "if", "though"}
            for delta in range(8):
                for offset in (mid + delta, mid - delta):
                    if 0 < offset < len(words) and words[offset].lower() in conjunctions:
                        best_split = offset
                        break
                if best_split is not None:
                    break

        if best_split is None:
            result.append(sent)
            continue

        first = " ".join(words[:best_split]).rstrip(",").rstrip()
        second = " ".join(words[best_split:])
        # Capitalise the start of the second part
        if second:
            second = second[0].upper() + second[1:]
        result.append(first + ". " + second)

    return " ".join(result)


def _vary_sentence_order(text: str) -> str:
    """With ~20 % probability, swap the two halves of a comma-separated sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []

    for sent in sentences:
        if random.random() < 0.2 and "," in sent:
            parts = sent.split(",", 1)
            if len(parts) == 2 and len(parts[0].split()) >= 3 and len(parts[1].split()) >= 3:
                new_sent = parts[1].strip().rstrip(".!?") + ", " + parts[0][0].lower() + parts[0][1:] + "."
                result.append(new_sent[0].upper() + new_sent[1:])
                continue
        result.append(sent)

    return " ".join(result)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def humanize_text(text: str, intensity: float = 0.5) -> dict:
    """
    Humanize AI-generated text using NLP algorithms.

    Parameters
    ----------
    text : str
        The original AI-generated text.
    intensity : float
        Controls synonym-swap aggressiveness (0.0 – 1.0).

    Returns
    -------
    dict with keys:
        humanized_text, orig_word_count, new_word_count,
        words_changed, orig_sentence_count, new_sentence_count
    """
    intensity = max(0.0, min(1.0, intensity))

    orig_word_count = len(text.split())
    orig_sentence_count = len(re.findall(r"[.!?]+", text)) or 1

    # 1. Protect special blocks
    protected, placeholders = _protect_special_blocks(text)

    # 2. Expand contractions
    protected = _expand_contractions(protected)

    # 3. Remove AI filler phrases
    protected = _remove_ai_phrases(protected)

    # 4. Replace buzzwords
    protected = _replace_buzzwords(protected)

    # 5. Thin transitional words
    protected = _thin_transitions(protected)

    # 6. Smart synonym swap via spaCy + WordNet
    words_changed = 0
    nlp = _ensure_nlp()
    if nlp and intensity > 0:
        protected, words_changed = _smart_synonym_swap(protected, intensity, nlp)

    # 7. Split long sentences
    protected = _split_long_sentences(protected)

    # 8. Vary sentence order
    protected = _vary_sentence_order(protected)

    # 9. Restore special blocks
    result = _restore_special_blocks(protected, placeholders)

    # Clean up extra whitespace
    result = re.sub(r" {2,}", " ", result).strip()

    new_word_count = len(result.split())
    new_sentence_count = len(re.findall(r"[.!?]+", result)) or 1

    return {
        "humanized_text": result,
        "orig_word_count": orig_word_count,
        "new_word_count": new_word_count,
        "words_changed": words_changed,
        "orig_sentence_count": orig_sentence_count,
        "new_sentence_count": new_sentence_count,
    }
