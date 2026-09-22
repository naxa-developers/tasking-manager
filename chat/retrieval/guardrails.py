from __future__ import annotations

import base64
import binascii
import difflib
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional

from chat.constants import MAX_QUESTION_CHARS

Verdict = Literal["ok", "out_of_scope", "unsafe"]

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
    "ignore", "bypass", "override", "reveal",
    "jailbreak", "instructions", "previous", "disregard",
)

# A single fuzzy hit needs an exact anchor; two or more stand on their own.
_FUZZY_ANCHORS: tuple[str, ...] = (
    "instructions", "prompt", "safety", "rules", "rbac", "jailbreak",
    "developer mode", "restricted", "system override",
)
_FUZZY_MIN_LEN = 5
_FUZZY_MIN_RATIO = 0.82

_B64_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{16,}={0,2}(?![A-Za-z0-9+/=])")
_HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")
_DECODED_VOCAB: tuple[str, ...] = (
    "ignore", "instructions", "prompt", "jailbreak", "bypass",
    "override", "disregard", "reveal", "forget", "previous",
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
    return difflib.SequenceMatcher(None, word, target, autojunk=False).ratio() >= _FUZZY_MIN_RATIO


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


# Scope keywords — strong (TM-specific, one match ok) vs weak (need >=2).
_STRONG_SCOPE_KEYWORDS: tuple[str, ...] = (
    "tasking manager", "tasking-manager", "taskingmanager",
    "openstreetmap", "osm",
    "hotosm", "teachosm",
    "mapping", "mapper", "validator", "validation",
    "bad imagery", "changeset", "hashtag", "imagery", "tms", "preset", "gpx", "osmcha",
    "overpass", "josm", "rapid", "potlatch", "field papers", "walking papers", "mapswipe",
    "faq",
)
_WEAK_SCOPE_KEYWORDS: tuple[str, ...] = (
    "task", "tasks", "project", "campaign", "organisation", "organization",
    "team", "permission", "role", "admin", "administrator",
    "lock", "unlock", "split", "invalidate", "validate",
    "export", "search", "filter", "favourite", "favorite",
    "location", "locations", "map", "area", "areas",
    "interest", "level", "badge", "notification", "message", "inbox",
    "private", "draft", "published", "archived", "featured",
    "editor", "statistics", "leaderboard", "activity", "history",
    "comment", "mention",
    "user", "users", "account", "login", "profile", "manage", "create",
    "error", "troubleshoot",
    "system", "configuration", "privacy", "security", "governance", "states",
    "contribution", "contributions", "contributed", "streak", "hours",
    "registered", "trending", "expiring", "recommend", "beginner",
)

# Small-talk detection — conservative, precise vocabulary.
_GREETING_ALT = r"help\s+me|hi|hello|hey|greetings|good\s+morning|good\s+afternoon|good\s+evening|help"
_THANKS_ALT = r"thanks\s+a\s+lot|many\s+thanks|much\s+appreciated|thank\s+you|thankyou|thanks|thx|\bty\b"
_FAREWELL_ALT = r"good\s+bye|goodbye|good\s+night|see\s+you|take\s+care|farewell|bye|cya"
_SMALLTALK_ADDRESS = r"(?:\s+(?:there|team|tmbot|tm\s*bot|everyone|everybody|all|folks))?"
_THANKS_FILLER = r"(?:\s+for\s+(?:that|the\s+info|your\s+help|all\s+your\s+help|everything))?"
_THANKS_POLITENESS = r"(?:\s+(?:so\s+much|very\s+much|a\s+lot))?"
_GREETING_UNIT = r"(?:" + _GREETING_ALT + r")" + _SMALLTALK_ADDRESS
_THANKS_UNIT = r"(?:" + _THANKS_ALT + r")" + _SMALLTALK_ADDRESS + _THANKS_FILLER + _THANKS_POLITENESS
_FAREWELL_UNIT = r"(?:" + _FAREWELL_ALT + r")" + _SMALLTALK_ADDRESS
_SMALLTALK_UNIT = r"(?:" + _GREETING_UNIT + r"|" + _THANKS_UNIT + r"|" + _FAREWELL_UNIT + r")"
# Prefix match — substantive query starting with small-talk stays in-scope.
_SMALLTALK_PREFIX_RE = re.compile(r"^\s*(?:" + _GREETING_ALT + r"|" + _THANKS_ALT + r"|" + _FAREWELL_ALT + r")\b", re.I)
# Back-compat alias: historic name treated everything as a greeting.
_GREETING_RE = _SMALLTALK_PREFIX_RE
# Pure small-talk — 1-3 units joined by punctuation (full-match only).
_SMALLTALK_PURE_RE = re.compile(
    r"^\s*" + _SMALLTALK_UNIT + r"(?:\s*[,!?.\u2026;:\-\u2014\u2013]+\s*" + _SMALLTALK_UNIT + r"){0,2}\s*[!?.\u2026]*\s*$",
    re.I,
)
# Deprecated aliases kept for compatibility.
_GREETING_PURE_RE = _SMALLTALK_PURE_RE
_HELP_ME_RE = re.compile(r"^\s*help\s+me\s*[!?.]*\s*$", re.I)
# Leading-prefix strip — one leading unit + delimiters, remainder captured.
_SMALLTALK_STRIP_RE = re.compile(
    r"^\s*" + _SMALLTALK_UNIT + r"\s*[,!?.\u2026;:\-\u2014\u2013]*\s*(?P<rest>.+)$",
    re.I | re.DOTALL,
)
_SUBSTANTIVE_HINT_RE = re.compile(
    r"\?|\b(what|how|who|can|where|when|why|which|is|are|do|does|did|should|explain|tell|show|list|find|create|manage|task|tasks|project|projects|mapping|validation|validate|split|lock|team|user|filter|location|map)\b",
    re.I,
)


def is_smalltalk_query(query: str) -> bool:
    """True if query is pure small-talk with no substantive content."""
    normalized = normalize_for_matching(query or "")
    if not normalized:
        return False
    if _SMALLTALK_PURE_RE.match(normalized):
        return True
    if _HELP_ME_RE.fullmatch(normalized):
        return True
    return False


def is_greeting_query(query: str) -> bool:
    """Back-compat alias for is_smalltalk_query."""
    return is_smalltalk_query(query)


def smalltalk_kind(query: str) -> str:
    """Kind of pure small-talk: farewell wins on mixed, then thanks, else greeting."""
    normalized = normalize_for_matching(query or "")
    if re.search(_FAREWELL_ALT, normalized, re.I):
        return "farewell"
    if re.search(_THANKS_ALT, normalized, re.I):
        return "thanks"
    return "greeting"


def strip_smalltalk_prefix(query: str) -> tuple[str, bool]:
    """Strip a leading small-talk prefix for retrieval."""
    original = query or ""
    if not original.strip():
        return original, False
    if is_smalltalk_query(original):
        return original, False
    m = _SMALLTALK_STRIP_RE.match(original)
    if not m:
        return original, False
    rest = (m.group("rest") or "").strip()
    if len(rest) < 3:
        return original, False
    if not _SUBSTANTIVE_HINT_RE.search(rest):
        return original, False
    return rest, True


_FOLLOWUP_PRONOUNS_RE = re.compile(r"\b(it|this|that|these|those|them|so|more|steps?|how)\b", re.I)


def is_followup_query(query: str) -> bool:
    """True if query looks like a conversational follow-up (pronouns, short, vague)."""
    text = (query or "").strip()
    if not text or len(text) > 80:
        return False
    low = text.lower()
    # Must contain pronoun/vague term
    if not _FOLLOWUP_PRONOUNS_RE.search(text):
        return False
    # If it already has strong TM keywords, it's self-contained, not pure followup
    for kw in _STRONG_SCOPE_KEYWORDS:
        if kw.lower() in low:
            return False
    # If it has >=2 weak keywords, it's self-contained (e.g. "How do I lock a task?" has lock+task)
    weak_hits = [kw for kw in _WEAK_SCOPE_KEYWORDS if kw.lower() in low]
    if len(weak_hits) >= 2:
        return False
    if len(weak_hits) == 1 and "?" in text and any(w in low for w in ("what", "how", "who", "can", "where", "when", "why")):
        if any(w in low for w in ("task", "project", "user", "team", "org", "mapping", "validation")):
            return False
    # Single weak keyword with ? or short imperative is treated as a follow-up.
    if "?" in text or low.startswith("how"):
        return True
    if len(text.split()) <= 6:
        return True
    return False


@dataclass(frozen=True)
class GuardrailDecision:
    verdict: Verdict
    reason: str
    # which gate triggered (scope/safety) — for audit
    gate: str


def _question_form(text: str, low: str) -> bool:
    """True for interrogative form, including unpunctuated "how many" asks."""
    if "?" in text:
        return True
    return any(
        w in low for w in ("how many", "how much", "number of", "total number")
    )


def classify_query(query: str) -> GuardrailDecision:
    """Classify a raw user query before retrieval."""
    text = (query or "").strip()
    if not text:
        return GuardrailDecision(verdict="out_of_scope", reason="Empty query.", gate="scope")
    # Extremely long inputs are treated as potential injection payloads.
    if len(text) > MAX_QUESTION_CHARS:
        return GuardrailDecision(verdict="unsafe", reason="Input too long.", gate="safety")

    # Safety next — injection checks take precedence over scope (de-obfuscated).
    reason = detect_injection(text)
    if reason:
        return GuardrailDecision(verdict="unsafe", reason=reason, gate="safety")

    normalized = normalize_for_matching(text)

    # Small-talk prefix is in-scope (hello there, thanks ..., bye ...).
    if _SMALLTALK_PREFIX_RE.match(normalized):
        return GuardrailDecision(verdict="ok", reason="Small-talk prefix.", gate="scope")

    low = normalized

    # Strong keywords: single match is enough (TM-specific)
    for kw in _STRONG_SCOPE_KEYWORDS:
        if kw.lower() in low:
            return GuardrailDecision(verdict="ok", reason=f"Matched strong scope keyword {kw!r}.", gate="scope")

    # Weak keywords need >=2 distinct matches; one generic word stays out_of_scope.
    weak_hits = [kw for kw in _WEAK_SCOPE_KEYWORDS if kw.lower() in low]
    if len(weak_hits) >= 2:
        return GuardrailDecision(verdict="ok", reason=f"Matched weak scope keywords {weak_hits[:2]!r}.", gate="scope")
    if len(weak_hits) == 1:
        # Single weak hit needs question form + TM noun ("How do I lock a task?").
        if _question_form(text, low) and any(w in low for w in ("what", "how", "who", "can", "where", "when", "why")):
            if any(w in low for w in ("task", "project", "user", "team", "org", "mapping", "validation", "location", "filter", "badge", "level", "contribution", "streak", "hour")):
                return GuardrailDecision(verdict="ok", reason=f"Single weak '{weak_hits[0]}' + question-form TM probe.", gate="scope")
        # A weak single compound like "private project" already counts as 2 hits.

    # Fallback heuristic: question mark + interrogative + TM noun (catches cases with zero keyword hits but question-form)
    if _question_form(text, low) and any(w in low for w in ("what", "how", "who", "can", "where", "when", "why")):
        if any(w in low for w in ("task", "project", "user", "team", "org", "mapping", "validation", "location", "filter", "badge", "level", "contribution", "streak", "hour")):
            return GuardrailDecision(verdict="ok", reason="Question-form TM probe.", gate="scope")

    return GuardrailDecision(
        verdict="out_of_scope",
        reason="No Tasking Manager–related keywords detected.",
        gate="scope",
    )


# Refusal copy — short, non-leaky, no KB existence hints.

REFUSAL_TEMPLATES: dict[Verdict, str] = {
    "unsafe": "I can't help with that.",
    "out_of_scope": (
        "Could you be more precise? I can help with mapping, validation, "
        "projects, teams, organizations, and permissions — all grounded in "
        "the Tasking Manager knowledge base."
    ),
    # "ok" never renders a refusal
    "ok": "",
}


def refusal_for(verdict: Verdict) -> str:
    return REFUSAL_TEMPLATES.get(verdict, REFUSAL_TEMPLATES["out_of_scope"])
