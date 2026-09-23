from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Literal, Optional

Route = Literal["KB", "DOMAIN", "BOTH"]

# project #123 / project 123 / project id 123 (case-insensitive).
# The trailing (?!\d) refuses to silently truncate longer numbers.
_PROJECT_ID_RE = re.compile(r"project\s*(?:id\s*)?#?\s*(\d{1,8})(?!\d)", re.I)

# Project links: /projects/123, /project/123 (tasks.hotosm.org URLs).
_PROJECT_URL_RE = re.compile(r"/projects?/(\d{1,8})\b", re.I)

# A bare number, optionally "#123" — only meaningful while clarifying.
_BARE_PROJECT_ID_RE = re.compile(r"^\s*#?(\d{1,8})\s*$")

# A project mention that refers to a specific project: an explicit id/URL,
# a definite/deictic reference ("the project", "my project"), a possessive
# ("project's"), or the pronoun "it" (follow-ups referencing the project in
# context). Generic indefinite mentions ("a project", "a task") do not
# count — those are usually KB how-to phrasing and must not trigger a
# project-id clarification.
_PROJECT_ANCHOR = (
    r"\bproject\s*(?:id\s*)?#?\s*\d{1,8}(?!\d)"
    r"|/projects?/\d{1,8}(?!\d)"
    r"|\b(?:the|this|that|these|those|my|our|its|their)\s+projects?"
    r"|\bprojects?\s*(?:’|')s"
    r"|\bit\b"
)

# Live-aggregate intent (minimal scope: task counts / task status).
# Mapped/validated/status phrasing needs a project anchor — bare "a task
# mapped" or "status of a task" is a KB how-to, not a live aggregate.
_STATS_RE = re.compile(
    r"\b(how many|count|total|number of)\b.{0,60}\btasks?\b"
    r"|\btasks?\b.{0,60}\b(how many|count|total|number)\b"
    rf"|\b(?:validated|mapped)\b.{{0,40}}(?:{_PROJECT_ANCHOR})"
    rf"|\btasks?\b.{{0,60}}\b(?:validated|mapped)\b.{{0,40}}(?:{_PROJECT_ANCHOR})"
    rf"|\bstatus\b.{{0,25}}\btasks?\b.{{0,40}}(?:{_PROJECT_ANCHOR})"
    rf"|\btasks?\b.{{0,25}}\bstatus\b.{{0,40}}(?:{_PROJECT_ANCHOR})"
    r"|\b(?:compare|show|check)\b.{0,30}\bstats\b"
    r"|\bwhat(?:'s| is| are)\b.{0,40}\bstats\b",
    re.I,
)

# How-to intent — KB evidence still needed alongside domain data.
_HOWTO_RE = re.compile(
    r"\b(how do i|how to|how can i|steps?|instructions?|validate|validation|"
    r"mapping|create|procedure|guide)\b",
    re.I,
)

# Strict how-to phrasing for personal capabilities: only explicit asks keep KB.
_HOWTO_STRICT_RE = re.compile(
    r"\b(how do i|how to|how can i|steps?|instructions?|procedure|guide)\b",
    re.I,
)

# Summary intent — live project attributes matched as "<keyword> ... project".
# The project must be an anchored reference; bare "a project" stays KB.
_SUMMARY_KEYWORDS = (
    r"status|private|priority|difficult|stage|published|draft|archived|"
    r"organisation|organization|author|progress|percent|details?|info|"
    r"information|overview|summar(?:y|ies|ize|ized|izing)"
)
_SUMMARY_RE = re.compile(
    rf"\b(?:{_SUMMARY_KEYWORDS})\b.{{0,60}}(?:{_PROJECT_ANCHOR})"
    rf"|(?:{_PROJECT_ANCHOR}).{{0,60}}\b(?:{_SUMMARY_KEYWORDS})\b",
    re.I,
)

# Teams intent — which teams work on a project and in what role.
# Anchored project reference only (see _PROJECT_ANCHOR).
_TEAM_WORDS = r"teams?|members?"
_TEAMS_RE = re.compile(
    rf"\b(?:{_TEAM_WORDS})\b.{{0,60}}(?:{_PROJECT_ANCHOR})"
    rf"|(?:{_PROJECT_ANCHOR}).{{0,60}}\b(?:{_TEAM_WORDS})\b",
    re.I,
)

# Chat intent — recent discussion; HTML stripped, username + excerpt only.
# Anchored project reference only (see _PROJECT_ANCHOR).
_DISCUSSION_WORDS = r"chats?|comments?|discussion"
_CHAT_RE = re.compile(
    rf"\b(?:{_DISCUSSION_WORDS})\b.{{0,60}}(?:{_PROJECT_ANCHOR})"
    rf"|(?:{_PROJECT_ANCHOR}).{{0,60}}\b(?:{_DISCUSSION_WORDS})\b",
    re.I,
)

# My-work intent — the asker's own locked/current tasks; no project id needed.
# "working on" only counts in the first person so third-party questions
# ("who is working on project 5?") fall through to the project fallback.
# Count questions ("how many tasks have I mapped?") belong to contributions.
_MYWORK_RE = re.compile(
    r"\bmy\b.{0,30}\btasks?\b"
    r"|\b(?:i\s+am|i['’]?m|am\s+i)\b.{0,20}\bworking\s+on\b"
    r"|\blocked\b.{0,20}\btasks?\b"
    r"|\btasks?\b.{0,30}\blocked\b",
    re.I,
)

# First-person marker shared by the personal capabilities below.
_FIRST_PERSON_RE = re.compile(
    r"\b(?:my|mine|me|i|i['’]?m|i['’]?ve|am\s+i|have\s+i|did\s+i|do\s+i)\b",
    re.I,
)

# Mapping level / badges — possessive or perfect-aspect phrasing only, so
# "how do I earn badges?" stays a KB how-to.
_USER_PROFILE_RE = re.compile(
    r"\b(?:mapper|mapping)\s+level\b"
    r"|\bnext\s+(?:mapping\s+|mapper\s+)?level\b"
    r"|\bbadges?\b.{0,40}\b(?:have\s+i|i\s+have|i['’]?ve|i\s+earned|earned|"
    r"do\s+i\s+have|on\s+my\s+profile|my\s+profile)\b"
    r"|\bdo\s+i\s+have\b.{0,30}\bbadges?\b"
    r"|\b(?:my|earned)\s+badges?\b",
    re.I,
)

# Contribution totals / hours / month-over-month / contributed projects.
_USER_CONTRIBUTIONS_RE = re.compile(
    r"\b(?:my|mine)\b.{0,30}\b(?:contributions?|hours|time\s+spent)\b"
    r"|\bcontributions?\b.{0,40}\b(?:i\s+have|have\s+i|i['’]?ve|this\s+month|"
    r"last\s+month|my)\b"
    r"|\bhours\b.{0,40}\b(?:contributed|mapping|validating|mapped|validated|"
    r"this\s+month|last\s+month)\b"
    r"|\b(?:how\s+many|number\s+of|count\s+of|total)\b.{0,40}\b(?:tasks?|projects?)\b"
    r".{0,40}\b(?:have\s+i|i\s+have|i['’]?ve|did\s+i|i\s+did)\b"
    r"|\bprojects?\b.{0,40}\b(?:contributed|worked\s+on)\b"
    r"|\bcontributed\b.{0,40}\b(?:this\s+month|last\s+month|projects?)\b",
    re.I,
)

# Authored/created projects — authorship, never inferred from mapping or
# validation. First-person creation markers only, so procedural asks
# ("how do I create a project?") stay KB how-to questions.
_USER_CREATED_PROJECTS_RE = re.compile(
    r"\bprojects?\b.{0,30}\bi\s+(?:have\s+|had\s+)?"
    r"(?:created|authored|made|owned)\b"
    r"|\bprojects?\b.{0,30}\bi['’]?ve\s+(?:created|authored|made)\b"
    r"|\b(?:how\s+many|number\s+of|count\s+of|total)\b.{0,40}\bprojects?\b"
    r".{0,40}\b(?:have\s+i|did\s+i|do\s+i|i\s+have|i['’]?ve)\b"
    r".{0,30}\b(?:created|create|authored|author|made|own|owned)\b"
    r"|\b(?:created|authored|made|owned)\s+by\s+(?:me|myself)\b"
    r"|\b(?:which|what|list|show|see|view)\b.{0,30}\bprojects?\b"
    r".{0,40}\b(?:i\s+(?:created|authored|made|own|owned)"
    r"|i['’]?ve\s+(?:created|authored|made)"
    r"|did\s+i\s+(?:create|author|make))\b"
    r"|\bmy\s+created\s+projects?\b",
    re.I,
)

# Projects run by the asker's own organisation(s). Requires a project noun so
# procedural asks ("how do I get my organization added?") stay KB how-to.
_USER_ORG_PROJECTS_RE = re.compile(
    r"\bmy\s+(?:organisation|organization|org)\b"
    r"|\bour\s+(?:organisation|organization|org)\b"
    r"|\b(?:organisation|organization|org)\b.{0,30}"
    r"\b(?:i\s+(?:manage|run|own)|i['’]?m\s+(?:part\s+of|in))\b"
    r"|\bprojects?\b.{0,40}\b(?:my|our)\s+(?:organisation|organization|org)\b",
    re.I,
)

# Streak / validation-vs-mapping split.
_USER_ACTIVITY_RE = re.compile(
    r"\bstreak\b"
    r"|\b(?:validation|validating|validated)\b.{0,30}\b(?:versus|vs\.?|and|"
    r"split|compared|ratio)\b.{0,30}\b(?:mapping|mapped|mapper)\b"
    r"|\b(?:mapping|mapped)\b.{0,30}\b(?:versus|vs\.?|and|split|compared|ratio)\b"
    r".{0,30}\b(?:validation|validating|validated)\b"
    r"|\bsplit\b.{0,40}\b(?:validation|validating|mapped|mapping)\b",
    re.I,
)

# The asker's own team memberships (project teams are a separate intent).
_USER_TEAMS_RE = re.compile(
    r"\bmy\b.{0,20}\bteams?\b"
    r"|\bteams?\b.{0,40}\b(?:am\s+i|i\s+am|i['’]?m|i\s+belong|do\s+i\s+belong|"
    r"part\s+of|member\s+of|membership)\b"
    r"|\b(?:which|what)\s+teams?\b.{0,30}\b(?:part\s+of|belong|member)\b",
    re.I,
)

# Submitted/validated/invalidated status of the asker's own tasks.
_USER_TASKS_RE = re.compile(
    r"\b(?:submitted|validated\s+yet|invalidated|invalidation|"
    r"validator\s+sa(?:y|id)|not\s+yet\s+validated)\b",
    re.I,
)

_LOCKED_RE = re.compile(r"\blocked\b", re.I)


def _user_ops(text: str) -> tuple:
    """Fixed personal capabilities implied by the question, in stable order."""
    ops = []
    if is_user_profile_intent(text):
        ops.append("user_profile")
    if is_user_org_projects_intent(text):
        ops.append("user_org_projects")
    if is_user_created_projects_intent(text):
        # Authorship is its own capability: never inferred from contributions.
        ops.append("user_projects_created")
    elif is_user_contributions_intent(text):
        ops.append("user_contributions")
    if is_user_activity_intent(text):
        ops.append("user_activity")
    if is_user_teams_intent(text):
        ops.append("user_teams")
    task_state = bool(_FIRST_PERSON_RE.search(text) and _USER_TASKS_RE.search(text))
    if task_state:
        ops.append("user_tasks")
    # Locked/current-task questions prefer mywork; status-only questions do not.
    if is_mywork_intent(text) and not (task_state and not _LOCKED_RE.search(text)):
        ops.append("mywork")
    return tuple(ops)


def extract_project_ids(query: str) -> List[int]:
    """Return referenced project ids in order of appearance (deduplicated)."""
    text = query or ""
    matches = list(_PROJECT_ID_RE.finditer(text)) + list(_PROJECT_URL_RE.finditer(text))
    matches.sort(key=lambda m: m.start())
    ids: List[int] = []
    for match in matches:
        try:
            pid = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if pid > 0 and pid not in ids:
            ids.append(pid)
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
        pid = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def is_stats_intent(query: str) -> bool:
    """True when the question asks for a live task aggregate."""
    return bool(_STATS_RE.search(query or ""))


def is_summary_intent(query: str) -> bool:
    """True when the question asks for live project attributes."""
    return bool(_SUMMARY_RE.search(query or ""))


def is_teams_intent(query: str) -> bool:
    """True when the question asks which teams work on a project."""
    return bool(_TEAMS_RE.search(query or ""))


def is_chat_intent(query: str) -> bool:
    """True when the question asks for recent project discussion."""
    return bool(_CHAT_RE.search(query or ""))


def is_mywork_intent(query: str) -> bool:
    """True when the question asks about the asker's own locked/current tasks."""
    return bool(_MYWORK_RE.search(query or ""))


def is_user_profile_intent(query: str) -> bool:
    """True when the question asks for the asker's level or earned badges."""
    text = query or ""
    return bool(_FIRST_PERSON_RE.search(text) and _USER_PROFILE_RE.search(text))


def is_user_contributions_intent(query: str) -> bool:
    """True when the question asks for the asker's contribution totals."""
    text = query or ""
    return bool(_FIRST_PERSON_RE.search(text) and _USER_CONTRIBUTIONS_RE.search(text))


def is_user_created_projects_intent(query: str) -> bool:
    """True when the asker asks about projects they authored/created.

    Authorship is kept distinct from contribution: questions about mapped,
    validated, or worked-on projects never satisfy this intent.
    """
    text = query or ""
    if not _FIRST_PERSON_RE.search(text):
        return False
    return bool(_USER_CREATED_PROJECTS_RE.search(text))


def is_user_org_projects_intent(query: str) -> bool:
    """True when the asker asks what their own organisation(s) are running."""
    text = query or ""
    if not re.search(r"\bprojects?\b", text, re.I):
        return False
    if not _USER_ORG_PROJECTS_RE.search(text):
        return False
    if _HOWTO_STRICT_RE.search(text) and not re.search(
        r"\b(?:what|which|list|show|see|view)\b", text, re.I
    ):
        return False
    return True


def is_user_activity_intent(query: str) -> bool:
    """True when the question asks for the asker's streak or split."""
    text = query or ""
    return bool(_FIRST_PERSON_RE.search(text) and _USER_ACTIVITY_RE.search(text))


def is_user_teams_intent(query: str) -> bool:
    """True when the question asks which teams the asker belongs to."""
    text = query or ""
    return bool(_FIRST_PERSON_RE.search(text) and _USER_TEAMS_RE.search(text))


def is_user_tasks_intent(query: str) -> bool:
    """True when the question asks for the status of the asker's own tasks."""
    text = query or ""
    return bool(_FIRST_PERSON_RE.search(text) and _USER_TASKS_RE.search(text))


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
        "info information is it its let level levels list lock locked look "
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


# Discovery intents -----------------------------------------------------------

_DIFFICULTY_WORDS = {
    "beginner": "EASY",
    "easy": "EASY",
    "beginner-friendly": "EASY",
    "intermediate": "MODERATE",
    "moderate": "MODERATE",
    "advanced": "CHALLENGING",
    "challenging": "CHALLENGING",
    "hard": "CHALLENGING",
}

_TRENDING_RE = re.compile(
    r"\btrending\b|\bmost\s+active\b|\bpopular\b|\bbusiest\b|\bhot\s+projects\b",
    re.I,
)
_RECOMMENDATION_RE = re.compile(
    r"\brecommend\b|\bsuggest\b|\bpick\s+a\s+project\b",
    re.I,
)
_EXPIRING_RE = re.compile(
    r"\bexpir(?:e|es|ing|y)\b|\bdue\s+soon\b|\bending\s+soon\b|\bdeadline\b",
    re.I,
)
_SHORT_ON_MAPPERS_RE = re.compile(
    r"\bshort\s+on\s+mappers?\b|\bneed(?:s|ing)?\s+mappers?\b|\bunderstaffed\b|"
    r"\burgent(?:ly)?\b|\bfew\s+mappers?\b|\bmore\s+mappers?\b",
    re.I,
)
_GLOBAL_STATS_RE = re.compile(
    r"\b(?:how\s+many|number\s+of|total|count\s+of)\b[^?]{0,40}"
    r"\b(?:users?|mappers?|accounts?)\b"
    r"|\b(?:how\s+many|number\s+of|count\s+of)\b[^?]{0,40}\b(?:projects?|tasks?)\b"
    r"[^?]{0,40}\b(?:in\s+total|overall|on\s+tasking\s+manager|registered|"
    r"have\s+been|altogether)\b",
    re.I,
)
# Org/campaign leaderboard asks ("which organizations have the most projects")
# are site-wide aggregates, not trend rankings.
_ORG_LEADERBOARD_RE = re.compile(
    r"\b(?:countries|organisations?|organizations?|orgs?|campaigns?)\b"
    r".{0,50}\b(?:most|top|largest|busiest|active|with\s+the\s+most)\b",
    re.I,
)
_PROJECT_ANCHOR_RE = re.compile(_PROJECT_ANCHOR, re.I)
_SKILL_MATCH_RE = re.compile(
    r"\bmatch\s+my\s+(?:skill|level)\b|\bmy\s+skill\s+level\b|"
    r"\bfor\s+my\s+(?:skill|level)\b|\bsuitable\s+for\s+me\b|\bmy\s+level\b",
    re.I,
)
_HEALTH_RE = re.compile(r"\bhealth(?:care|-oriented)?\b|\bhospital", re.I)
_ACTION_MAP_RE = re.compile(r"\bprojects?\s+(?:i\s+can\s+)?(?:to\s+)?map\b", re.I)
_ACTION_VALIDATE_RE = re.compile(
    r"\bprojects?\s+(?:i\s+can\s+)?(?:to\s+)?validat(?:e|ing)\b", re.I
)
_COUNTRY_TEXT_RE = re.compile(
    r"\b(?:in|from|near)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\b"
)
_ORGANISATION_TEXT_RE = re.compile(
    r"\b(?:organi[sz]ation|org)\s+(?:called\s+|named\s+)?"
    r"([A-Za-z0-9][\w .&'\-]{1,60})",
    re.I,
)
_RUN_BY_TEXT_RE = re.compile(
    r"\b(?:run|managed|led|created|owned)\s+by\s+" r"([A-Za-z0-9][\w .&'\-]{1,60})",
    re.I,
)
_CAMPAIGN_TEXT_RE = re.compile(
    r"\bcampaign\s+(?:called\s+|named\s+)?([A-Za-z0-9][\w .&'\-]{1,60})",
    re.I,
)
_TRAILING_FILLER_RE = re.compile(
    r"\b(?:projects?|tasks?|right\s+now|currently|please|thanks)\b", re.I
)
# A captured "organization" phrase that starts with a verb/pronoun is prose,
# not an org name ("my organization added to Tasking Manager").
_ORG_NAME_STOPWORDS_RE = re.compile(
    r"^(?:added|currently|running|involved|working|active|that|which|who|"
    r"is|are|was|were|has|have|had|to|for|on|in|at|the|a|an|my|our|"
    r"me|us|myself|ourselves)\b",
    re.I,
)
_EXPIRING_DAYS_RE = re.compile(r"\b(?:within|next|in)\s+(\d{1,2})\s+days?\b", re.I)


def _clean_phrase(value: Optional[str]) -> Optional[str]:
    """Trim a free-text filter capture down to its meaningful phrase."""
    if not value:
        return None
    cleaned = _TRAILING_FILLER_RE.split(value, maxsplit=1)[0].strip(" .?!,'\"")
    if not cleaned or cleaned.lower() in ("tasking manager", "tm", "the"):
        return None
    return cleaned


def _discovery_filters(text: str) -> dict:
    """Allowlisted filters for the project-search capability."""
    filters: dict = {}
    low = text.lower()

    for word, canonical in _DIFFICULTY_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            filters["difficulty"] = canonical
            break

    if _SKILL_MATCH_RE.search(text):
        filters["based_on_skill"] = "true"

    if _EXPIRING_RE.search(text):
        days = _EXPIRING_DAYS_RE.search(text)
        filters["expiring_days"] = days.group(1) if days else "14"

    if _SHORT_ON_MAPPERS_RE.search(text):
        filters["short_on_mappers"] = "true"

    if _HEALTH_RE.search(text):
        filters["text_search"] = "health"

    if _ACTION_MAP_RE.search(text) or _ACTION_VALIDATE_RE.search(text):
        filters["action"] = "map" if _ACTION_MAP_RE.search(text) else "validate"

    country_match = _COUNTRY_TEXT_RE.search(text)
    country = _clean_phrase(country_match.group(1) if country_match else None)
    if country:
        filters["country"] = country

    organisation = _ORGANISATION_TEXT_RE.search(text) or _RUN_BY_TEXT_RE.search(text)
    organisation = _clean_phrase(organisation.group(1)) if organisation else None
    if organisation and not _ORG_NAME_STOPWORDS_RE.match(organisation):
        filters["organisation"] = organisation

    campaign = _CAMPAIGN_TEXT_RE.search(text)
    campaign = _clean_phrase(campaign.group(1)) if campaign else None
    if campaign:
        filters["campaign"] = campaign

    return filters


def discovery_filters(query: str) -> dict:
    """Allowlisted project-search filters for a question (public helper)."""
    return _discovery_filters(query or "")


_EXPIRING_DAYS_RE = re.compile(r"\b(?:within|next|in)\s+(\d{1,2})\s+days?\b", re.I)


def is_trending_intent(query: str) -> bool:
    """True when the question asks for popular or most-active projects."""
    return bool(_TRENDING_RE.search(query or ""))


def is_recommendation_intent(query: str) -> bool:
    """True when the question asks for project recommendations."""
    return bool(_RECOMMENDATION_RE.search(query or ""))


def is_global_stats_intent(query: str) -> bool:
    """True when the question asks for site-wide totals."""
    return bool(_GLOBAL_STATS_RE.search(query or ""))


def is_org_leaderboard_intent(query: str) -> bool:
    """True when the question ranks organisations/campaigns/countries."""
    return bool(_ORG_LEADERBOARD_RE.search(query or ""))


def is_project_search_intent(query: str) -> bool:
    """True when discovery filters identify a project-search question."""
    return bool(_discovery_filters(query or ""))


def _discovery_ops(text: str) -> tuple:
    """Global/discovery capabilities, only for questions without a project id."""
    if is_recommendation_intent(text):
        return ("user_recommendations",)
    if is_org_leaderboard_intent(text):
        return ("global_stats",)
    if is_trending_intent(text):
        return ("trending_projects",)
    if is_project_search_intent(text):
        return ("project_search",)
    if is_global_stats_intent(text):
        return ("global_stats",)
    return ()


@dataclass(frozen=True)
class DomainRoute:
    route: Route
    project_id: Optional[int] = None
    # Fixed domain operations in execution order; empty unless route is DOMAIN/BOTH.
    ops: tuple = ()
    # True when a project-scoped intent has no single resolvable project id.
    needs_project_id: bool = False
    # Allowlisted search filters for filter-aware ops (project_search).
    filters: dict = field(default_factory=dict)


def route_query(query: str) -> DomainRoute:
    """Deterministically route a question to KB, DOMAIN, or BOTH."""
    text = (query or "").strip()
    if not text:
        return DomainRoute(route="KB", project_id=None)
    ids = extract_project_ids(text)
    pid = ids[0] if len(ids) == 1 else None
    project_ops = tuple(
        op
        for op, want in (
            ("stats", is_stats_intent(text)),
            ("summary", is_summary_intent(text)),
            ("teams", is_teams_intent(text)),
            ("chat", is_chat_intent(text)),
        )
        if want
    )
    # More than one project id in one question: never guess which is meant.
    if len(ids) > 1 and project_ops:
        return DomainRoute(
            route="KB", project_id=None, ops=project_ops, needs_project_id=True
        )
    # Project-scoped ops need one explicit id; otherwise carry needs_project_id.
    ops = tuple(op for op in project_ops if pid is not None)
    ops = ops + _user_ops(text)
    filters: dict = {}
    anchored = pid is not None or bool(_PROJECT_ANCHOR_RE.search(text))
    if not ops and pid is None and not (project_ops and anchored):
        discovery = _discovery_ops(text)
        ops = ops + discovery
        if discovery == ("project_search",):
            filters = _discovery_filters(text)
    if not ops and pid is not None:
        ops = ("summary",)
    if not ops:
        if project_ops:
            return DomainRoute(
                route="KB", project_id=None, ops=project_ops, needs_project_id=True
            )
        return DomainRoute(route="KB", project_id=None)
    # Personal capabilities only need KB when the user explicitly asks how:
    # bare "mapping"/"validation" nouns must not force a KB lookup.
    personal_only = all(op not in ("stats", "summary", "teams", "chat") for op in ops)
    howto = _HOWTO_STRICT_RE.search(text) if personal_only else _HOWTO_RE.search(text)
    if howto:
        return DomainRoute(route="BOTH", project_id=pid, ops=ops, filters=filters)
    return DomainRoute(route="DOMAIN", project_id=pid, ops=ops, filters=filters)
