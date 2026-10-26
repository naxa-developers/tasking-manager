"""Deterministic prompt-injection guard.

The only non-LLM decision in the pipeline. Everything else — intent, route,
operation choice, project scope — belongs to the router model.

``detect_injection`` returns a reason string or None; ``neutralize_untrusted``
is applied to untrusted text (user input, retrieved chunks, evidence values)
before it reaches a prompt.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import re
import unicodedata
from typing import Optional

# Patterns — injection / RBAC escape / exfil attempts.

_UNSAFE_PATTERNS: list[re.Pattern] = [
    # classic instruction override
    re.compile(r"ignore\s+(all\s+)?(previous|above|system)\s+instructions", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|above|system)", re.I),
    re.compile(r"reveal.*prompt", re.I),
    re.compile(r"show\s+me\s+your\s+(system\s+)?prompt", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"do\s+anything\s+now\b", re.I),
    re.compile(r"\bDAN\b.*\bmode\b", re.I),
    re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I),
    re.compile(r"pretend\s+you\s+are", re.I),
    re.compile(r"act\s+as\s+if\s+you\s+are\s+not", re.I),
    # RBAC escape / exfil bait (mapper asking to see restricted docs by social engineering the LLM)
    re.compile(r"show\s+me\s+restricted", re.I),
    re.compile(r"bypass.*\brbac\b", re.I),
    re.compile(r"leak.*admin", re.I),
    re.compile(r"as\s+admin.*show", re.I),
    re.compile(r"as\s+administrator.*show", re.I),
    re.compile(r"ignore\s+rbac", re.I),
    re.compile(r"override.*role", re.I),
    re.compile(r"dump\s+(all\s+)?(docs|documents|knowledge)", re.I),
    # Raw KB / retrieval extraction (single-voice hardening)
    re.compile(r"\braw\s+(documents|docs|chunks|context|evidence)\b", re.I),
    re.compile(r"(show|give)\s+me\s+.*\bretrieved\b", re.I),
    re.compile(r"show\s+me\s+the\s+(kb|knowledge\s*base)\b", re.I),
    re.compile(r"ignore\s+.*evidence", re.I),
]

# Input normalization + obfuscation-resistant detection.

_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REPETITION_RE = re.compile(r"(.)\1{3,}")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")

_FUZZY_TARGETS: tuple[str, ...] = (
    "ignore",
    "bypass",
    "override",
    "reveal",
    "jailbreak",
    "instructions",
    "previous",
    "disregard",
)

# A single fuzzy hit needs an exact anchor; two or more stand on their own.
_FUZZY_ANCHORS: tuple[str, ...] = (
    "instructions",
    "prompt",
    "safety",
    "rules",
    "rbac",
    "jailbreak",
    "developer mode",
    "restricted",
    "system override",
)
_FUZZY_MIN_LEN = 5
_FUZZY_MIN_RATIO = 0.82

_B64_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])"
)
_HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_DECODED_VOCAB: tuple[str, ...] = (
    "ignore",
    "instructions",
    "prompt",
    "jailbreak",
    "bypass",
    "override",
    "disregard",
    "reveal",
    "forget",
    "previous",
)


def strip_obfuscation(text: str) -> str:
    """NFKC-normalize, drop zero-width/control chars, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZERO_WIDTH_RE.sub("", t)
    t = _CONTROL_RE.sub(" ", t)
    return _WHITESPACE_RE.sub(" ", t).strip()


def normalize_for_matching(text: str) -> str:
    """Casefolded, de-obfuscated form used for every comparison below."""
    return _REPETITION_RE.sub(r"\1", strip_obfuscation(text).casefold())


def _is_typo_variant(word: str, target: str) -> bool:
    """Typoglycemia (same first/last, scrambled middle) or close difflib match."""
    if word == target or len(word) < _FUZZY_MIN_LEN:
        return False
    if abs(len(word) - len(target)) > 2:
        return False
    if (
        word[0] == target[0]
        and word[-1] == target[-1]
        and sorted(word[1:-1]) == sorted(target[1:-1])
    ):
        return True
    return (
        difflib.SequenceMatcher(None, word, target, autojunk=False).ratio()
        >= _FUZZY_MIN_RATIO
    )


def _fuzzy_injection_reason(normalized: str) -> Optional[str]:
    """Misspelled injection phrasing — typoglycemia / character mutations."""
    hits = {
        target
        for word in _WORD_RE.findall(normalized)
        for target in _FUZZY_TARGETS
        if _is_typo_variant(word, target)
    }
    if not hits:
        return None
    if len(hits) >= 2:
        return f"fuzzy injection tokens {sorted(hits)!r}"
    if any(anchor in normalized for anchor in _FUZZY_ANCHORS):
        return f"fuzzy injection token {sorted(hits)[0]!r} with anchor"
    return None


def _decode_candidate(blob: str) -> Optional[str]:
    """Decode a base64/hex token; printable lowercase ASCII or None."""
    raw_candidates = []
    if _B64_TOKEN_RE.fullmatch(blob):
        try:
            raw_candidates.append(base64.b64decode(blob, validate=True))
        except (binascii.Error, ValueError):
            pass
    if _HEX_TOKEN_RE.fullmatch(blob) and len(blob) % 2 == 0:
        try:
            raw_candidates.append(bytes.fromhex(blob))
        except ValueError:
            pass
    for raw in raw_candidates:
        try:
            decoded = raw.decode("ascii")
        except UnicodeDecodeError:
            continue
        if not decoded or sum(ch.isprintable() for ch in decoded) < len(decoded) * 0.85:
            continue
        return decoded.casefold()
    return None


def _encoded_injection_reason(normalized: str) -> Optional[str]:
    """Base64/hex payloads that decode to injection vocabulary."""
    tokens = _B64_TOKEN_RE.findall(normalized) + _HEX_TOKEN_RE.findall(normalized)
    for token in tokens:
        decoded = _decode_candidate(token)
        if decoded and any(v in decoded for v in _DECODED_VOCAB):
            return "encoded injection payload"
    return None


def _spaced_out_reason(normalized: str) -> Optional[str]:
    """Best-of-N letter spacing ("i g n o r e ...") — never a real question."""
    single = sum(1 for w in normalized.split(" ") if len(w) == 1 and w.isalnum())
    if single >= 8:
        return "spaced-out input"
    return None


def detect_injection(text: str) -> Optional[str]:
    """Reason when text looks like an injection attempt, else None."""
    normalized = normalize_for_matching(text)
    for pat in _UNSAFE_PATTERNS:
        if pat.search(normalized):
            return f"Blocked by safety rule: {pat.pattern!r}"
    reason = _fuzzy_injection_reason(normalized) or _spaced_out_reason(normalized)
    if reason:
        return reason
    # Base64 is case-sensitive: decode from the merely de-obfuscated text.
    return _encoded_injection_reason(strip_obfuscation(text))


def neutralize_untrusted(text: str) -> str:
    """Sanitize user-generated content before it reaches the LLM."""
    cleaned = strip_obfuscation(text)
    if detect_injection(cleaned):
        return "[message withheld]"
    return cleaned
