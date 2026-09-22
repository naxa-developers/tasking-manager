from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import quote

DEFAULT_CONFIDENCE_THRESHOLD = 0.015

LOW_CONFIDENCE_ANSWER = (
    "I couldn't find relevant information for that question in the Tasking Manager "
    "knowledge base. Try rephrasing with more specific Tasking Manager terms like "
    "mapping, validation, projects, teams, or permissions."
)

# Deterministic deny copy for live-data questions; no existence oracle.
DOMAIN_UNAVAILABLE_ANSWER = (
    "I couldn't retrieve live project data for that request. The project may not "
    "exist, or you may not have access to it. Check the project ID, or ask me a "
    "knowledge-base question about mapping, validation, projects, teams, or permissions."
)

# Temporary live-data failure (timeout / tool unavailable), never a deny.
DOMAIN_TEMPORARY_ANSWER = (
    "I couldn't reach live project data right now. Please try again in a moment."
)

GREETING_ANSWER = (
    "Hi! I am TMBot, your Tasking Manager assistant. "
    "Ask me about mapping, validation, project creation, permissions, or task states."
)
THANKS_ANSWER = (
    "You're welcome! Ask me about mapping, validation, projects, teams, "
    "or permissions if you need more help."
)
FAREWELL_ANSWER = (
    "Goodbye! Ask me anytime about mapping, validation, projects, teams, "
    "or permissions."
)
SMALLTALK_ANSWERS: Dict[str, str] = {
    "greeting": GREETING_ANSWER,
    "thanks": THANKS_ANSWER,
    "farewell": FAREWELL_ANSWER,
}

# Deterministic clarification when a live-data question has no project id.
NEEDS_PROJECT_ANSWER = (
    "Which project do you mean? Send the project ID or a project link "
    "(for example, tasks.hotosm.org/projects/123) and I'll look up the live details."
)

# Nothing about another user's profile is ever fetched or consolidated for the
# LLM; the asker is pointed at the public web profile instead.
THIRD_PARTY_USER_ANSWER = (
    "I can't look up another user's profile or contributions. Open the user's "
    "profile on the Tasking Manager website to see their public activity and "
    "statistics."
)

_THIRD_PARTY_USER_LINK_TEMPLATE = (
    "I can't look up another user's profile or contributions. You can view "
    "their public profile on the Tasking Manager website: "
    "[{username}'s profile](/users/{quoted})."
)

_USERNAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_.\-]")


def third_party_user_answer(username: Optional[str] = None) -> str:
    """Canned redirect copy; deep-links the web profile when a name is known."""
    if not username:
        return THIRD_PARTY_USER_ANSWER
    safe = _USERNAME_SAFE_RE.sub("", str(username)).strip("._-")[:40]
    if not safe:
        return THIRD_PARTY_USER_ANSWER
    return _THIRD_PARTY_USER_LINK_TEMPLATE.format(
        username=safe, quoted=quote(safe, safe="")
    )


def conf_threshold() -> float:
    """Top fused-score floor below which retrieval is treated as weak."""
    try:
        return float(
            os.getenv("CONFIDENCE_THRESHOLD", str(DEFAULT_CONFIDENCE_THRESHOLD))
        )
    except ValueError:
        return DEFAULT_CONFIDENCE_THRESHOLD


def is_low_confidence(resp: Any) -> bool:
    """True when retrieval returned no candidates or a weak top result."""
    if not getattr(resp, "results", None):
        return True
    try:
        top = float(getattr(resp.results[0], "fused_score", 0.0) or 0.0)
    except Exception:
        return True
    return top < conf_threshold()
