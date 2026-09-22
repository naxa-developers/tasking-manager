from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from chat.retrieval.domain.routing import extract_bare_project_id, extract_project_ids

CLARIFY_CITATION_ID = "tm:clarify:project_id"


def clarification_citation() -> Dict[str, Any]:
    """Citation entry persisted with a needs-project-id clarification turn."""
    return {
        "id": CLARIFY_CITATION_ID,
        "title": "",
        "doc_id": "tasking_manager:clarify",
        "heading": "needs_project_id",
        "source_refs": [],
        "commit": None,
    }


def is_clarification_message(message: Mapping[str, Any]) -> bool:
    """True when an assistant message is the project-id clarification."""
    if str(message.get("role") or "") != "assistant":
        return False
    for cite in message.get("citations") or []:
        if isinstance(cite, Mapping) and cite.get("id") == CLARIFY_CITATION_ID:
            return True
    return False


def pending_clarification_question(
    messages: Sequence[Mapping[str, Any]],
) -> Optional[str]:
    """User question awaiting a project id, or None when nothing is pending."""
    if not messages:
        return None
    if not is_clarification_message(messages[-1]):
        return None
    for message in reversed(messages[:-1]):
        if str(message.get("role") or "") == "user":
            content = str(message.get("content") or "").strip()
            return content or None
    return None


def latest_explicit_project_id(
    messages: Sequence[Mapping[str, Any]],
) -> Optional[int]:
    """Most recent single explicit project id mentioned by the user."""
    for message in reversed(messages):
        if str(message.get("role") or "") != "user":
            continue
        ids = extract_project_ids(str(message.get("content") or ""))
        if len(ids) == 1:
            return ids[0]
    return None


def resolve_supplied_project_id(query: str) -> Optional[int]:
    """Project id supplied by a clarification reply: explicit or bare number."""
    ids = extract_project_ids(query)
    if len(ids) == 1:
        return ids[0]
    if not ids:
        return extract_bare_project_id(query)
    return None
