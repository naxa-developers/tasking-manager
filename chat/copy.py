"""Canned copy — the only strings returned without asking the model."""

from __future__ import annotations

LOW_CONFIDENCE_ANSWER = (
    "I couldn't find relevant information for that question in the Tasking Manager "
    "knowledge base. Try rephrasing with more specific Tasking Manager terms like "
    "mapping, validation, projects, teams, or permissions."
)

DOMAIN_UNAVAILABLE_ANSWER = (
    "I couldn't retrieve live Tasking Manager data for that request. The project "
    "may not exist, or you may not have access to it. Check the project ID, or ask "
    "me a documentation question about mapping, validation, projects, or teams."
)

DOMAIN_TEMPORARY_ANSWER = "I couldn't reach live Tasking Manager data right now. Please try again in a moment."

BLOCKED_ANSWER = "I can't help with that."

MISSING_DETAIL_ANSWER = (
    "I don't have that detail in the available data. Asking about a specific "
    "project ID (for example tasks.hotosm.org/projects/123) usually helps."
)

GENERATION_FAILED_ANSWER = (
    "I couldn't put an answer together just now. Please try again in a moment."
)
