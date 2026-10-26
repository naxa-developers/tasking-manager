"""Deterministic project-reference and third-party-subject extraction.

These are parsing and privacy helpers, not intent routing. Intent is owned by
``chat.retrieval.domain.llm_router``.
"""

from __future__ import annotations

import re
from typing import List, Optional

# project #123 / project 123 / project id 123 (case-insensitive).
# The trailing (?!\d) refuses to silently truncate longer numbers.
_PROJECT_ID_RE = re.compile(r"project\s*(?:id\s*)?#?\s*(\d{1,8})(?!\d)", re.I)

# Project links: /projects/123, /project/123 (tasks.hotosm.org URLs).
_PROJECT_URL_RE = re.compile(r"/projects?/(\d{1,8})\b", re.I)

# A bare number, optionally "#123" — only meaningful while clarifying.
_BARE_PROJECT_ID_RE = re.compile(r"^\s*#?(\d{1,8})\s*$")


def extract_project_ids(query: str) -> List[int]:
    """Return referenced project ids in order of appearance (deduplicated)."""
    text = query or ""
    matches = list(_PROJECT_ID_RE.finditer(text)) + list(_PROJECT_URL_RE.finditer(text))
    matches.sort(key=lambda match: match.start())
    ids: List[int] = []
    for match in matches:
        try:
            project_id = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if project_id > 0 and project_id not in ids:
            ids.append(project_id)
    return ids


def extract_project_id(query: str) -> Optional[int]:
    """Return the first referenced project id, or None (back-compat helper)."""
    ids = extract_project_ids(query)
    return ids[0] if ids else None


def extract_bare_project_id(query: str) -> Optional[int]:
    """A bare number (optionally ``#123``) — only meaningful while clarifying."""
    match = _BARE_PROJECT_ID_RE.match(query or "")
    if not match:
        return None
    try:
        project_id = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


# Third-party user queries ----------------------------------------------------
#
# Profile/activity questions about someone other than the asker are never
# answered from live evidence and never consolidated through the LLM: the
# service short-circuits them with a canned pointer at the public web profile
# (data minimisation; the web surface is the intended access path).

_PERSONAL_DATA_RE = re.compile(
    r"\b(?:profiles?|contributions?|hours|streak|badges?|activity|statistics|stats)\b"
    r"|\bmapping\s+level\b|\bmapper\s+level\b|\bnext\s+level\b"
    r"|\bwork(?:ed|ing)?\s+on\b"
    r"|\bcontribut(?:e|ed|ing)\b"
    r"|\bmap(?:ped|ping)?\b"
    r"|\bvalidat(?:e|ed|ing|ion)\b"
    r"|\binvalidat(?:e|ed|ing|ion)\b"
    r"|\block(?:ed)?\b"
    r"|\bsubmit(?:ted)?\b"
    r"|\btasks?\b.{0,40}\b(?:mapped|validated|invalidated|locked|submitted)\b"
    r"|\b(?:mapped|validated|invalidated|locked|submitted)\b.{0,40}\btasks?\b"
    r"|\b(?:validation|validating|validated)\b.{0,30}"
    r"\b(?:versus|vs\.?|split|compared|ratio)\b"
    r"|\b(?:mapping|mapped)\b.{0,30}\b(?:versus|vs\.?|split|compared|ratio)\b"
    r"|(?<![\w@])@[A-Za-z0-9][\w.-]{1,39}\b",
    re.I,
)

# Generic "somebody else" references; concrete references carry a capture group.
_GENERIC_OTHER_PERSON_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        r"\b(?:another|other|any\s+other|some\s+other)\s+"
        r"(?:user|users|mapper|mappers|account|accounts)\b",
        re.I,
    ),
    re.compile(r"\bsomeone\s+else(?:['’]s)?\b", re.I),
)

# Concrete third-party subjects: "user alice", "profile of alice", "@alice",
# "alice's", "has alice ...".
_CONCRETE_OTHER_PERSON_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(
        r"\b(?:user|users|mapper|mappers|account|accounts)\s+"
        r"(?:named\s+|called\s+)?@?([A-Za-z0-9][\w.-]{1,39})\b",
        re.I,
    ),
    re.compile(r"\bprofile\s+of\s+@?([A-Za-z0-9][\w.-]{1,39})\b", re.I),
    re.compile(r"(?<![\w@])@([A-Za-z0-9][\w.-]{1,39})\b"),
    re.compile(r"\b([A-Za-z0-9][\w.-]{1,39})['’]s\b"),
    re.compile(
        r"\b(?:has|have|had|did|does|do|is|was|were|can)\s+"
        r"@?([A-Za-z0-9][\w.-]{1,39})\b",
        re.I,
    ),
)

# The asker's own data ("my profile") keeps personal questions asker-scoped,
# even when other people are mentioned ("can another user see my profile?").
_OWN_PERSONAL_DATA_RE = re.compile(
    r"\b(?:my|our|mine)\s+(?:\w+\s+){0,2}"
    r"(?:profiles?|contributions?|hours|streak|badges?|activity|statistics|"
    r"stats|tasks?|level|teams?)\b",
    re.I,
)

# Words that look like captured names but never are.
_SUBJECT_STOPWORDS: frozenset[str] = frozenset(
    (
        "a an account accounts activity an another anybody anyone are badge "
        "badges been bot campaign campaigns check contribute contributed "
        "contributing contribution contributions data do does earn earned "
        "everybody everyone find get had has have he her his hour hours how i "
        "info information invalidate invalidated invalidating invalidation "
        "is it its let level levels list lock locked look "
        "looking manager map mapped mapper mappers mapping maps me my name "
        "names openstreetmap org organisation organisations organization "
        "organizations orgs osm other others our page pages people person "
        "profile profiles project projects see she show somebody someone "
        "statistics stats streak submitted task tasking tasks team teams that "
        "the their these they this those tmbot today tomorrow user users "
        "validate validated validating validation validator validators view we "
        "what when where which who whom whose why work worked working "
        "yesterday you your"
    ).split()
)


def is_third_party_user_query(query: str) -> bool:
    """True when the question asks for another person's profile/activity data.

    Deterministic, LLM-free detection: the service uses it to redirect the
    asker to the public web profile instead of consolidating somebody else's
    personal data in a generation prompt.
    """
    text = query or ""
    if not text.strip() or not _PERSONAL_DATA_RE.search(text):
        return False
    if any(pattern.search(text) for pattern in _GENERIC_OTHER_PERSON_PATTERNS):
        # Asker-owned data ("can another user see my profile?") stays a KB ask.
        if not _OWN_PERSONAL_DATA_RE.search(text):
            return True
    for pattern in _CONCRETE_OTHER_PERSON_PATTERNS:
        for match in pattern.finditer(text):
            candidate = (match.group(1) or "").strip("._-").lower()
            if candidate and candidate not in _SUBJECT_STOPWORDS:
                return True
    return False


def extract_third_party_username(query: str) -> Optional[str]:
    """Best-effort username for the web deep link; None when nobody is named."""
    text = query or ""
    for pattern in _CONCRETE_OTHER_PERSON_PATTERNS:
        for match in pattern.finditer(text):
            candidate = (match.group(1) or "").strip("._-")
            if candidate and candidate.lower() not in _SUBJECT_STOPWORDS:
                return candidate
    return None
