from __future__ import annotations

import os
from typing import Any, ClassVar, Dict, List, Literal

from rag.guard import neutralize_untrusted

DomainStatus = Literal["OK", "UNAUTHORIZED", "NOT_FOUND", "TIMEOUT", "UNAVAILABLE"]

_BLOCK_CHARS_DEFAULT = 2000
_TRUNCATION = "\n[truncated]"


def _block_char_limit() -> int:
    """Max chars per rendered evidence block (0 = uncapped)."""
    raw = os.environ.get("RAG_EVIDENCE_MAX_CHARS", "")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        return _BLOCK_CHARS_DEFAULT
    if limit == 0:
        return 0
    return limit if limit >= 200 else _BLOCK_CHARS_DEFAULT


def safe_value(value: Any, limit: int = 0) -> str:
    """Neutralize one rendered value: no injection text, no newlines.

    ``limit`` is accepted for call-site compatibility and ignored; the prompt
    budget is the only length bound.
    """
    del limit
    return neutralize_untrusted(str(value if value is not None else ""))


def _cap_block(block: str) -> str:
    limit = _block_char_limit()
    if limit <= 0 or len(block) <= limit:
        return block
    cut = block[: max(0, limit - len(_TRUNCATION))].rstrip()
    return f"{cut}{_TRUNCATION}"


# Short and marker-like on purpose: a sentence-shaped banner gets echoed into
# the answer by small models. Provenance stays in citations, not the prompt.
_HEADER = "[live Tasking Manager data]"


class EvidenceBase:
    """Prompt/citation rendering shared by the domain evidence dataclasses."""

    status: DomainStatus
    operation: str
    provenance: str

    _CONTEXT_FIELD: ClassVar[str] = "project_id"
    _CITATION_SCOPE: ClassVar[str] = "project"
    _CITATION_KIND: ClassVar[str] = ""
    _CITATION_TITLE: ClassVar[str] = ""
    _CITATION_HEADING: ClassVar[str] = ""
    _CITATION_SOURCE: ClassVar[Dict[str, str]] = {}
    # Scope-less citations (site-wide evidence) override these templates.
    _CITATION_ID_TEMPLATE: ClassVar[str] = "tm:{scope}:{ident}:{kind}"
    _CITATION_DOC_TEMPLATE: ClassVar[str] = "tasking_manager:{scope}:{ident}"

    @property
    def authorized(self) -> bool:
        return self.status == "OK"

    def _body_lines(self) -> List[str]:
        return []

    def to_prompt_block(self) -> str:
        """Small structured block for the LLM. Empty unless authorized.

        A ``user_id`` subject is audit metadata, never prompt content: it is
        masked here and stays available in citations and span metadata. Any
        other context field (e.g. ``project_id``) is still rendered, since
        the LLM needs it to attribute the numbers.
        """
        if not self.authorized:
            return ""
        lines = [_HEADER]
        context_value = getattr(self, self._CONTEXT_FIELD, None)
        if self._CONTEXT_FIELD != "user_id" and context_value is not None:
            lines.append(f"project: {safe_value(context_value, 64)}")
        lines.extend(self._body_lines())
        return _cap_block("\n".join(lines))

    def _scope_id(self) -> Any:
        raise NotImplementedError

    def to_citation(self) -> Dict[str, Any]:
        """Audit citation persisted server-side (never raw rows)."""
        ident = self._scope_id()
        context = {
            "scope": self._CITATION_SCOPE,
            "ident": ident,
            "kind": self._CITATION_KIND,
        }
        return {
            "id": self._CITATION_ID_TEMPLATE.format(**context),
            "title": self._CITATION_TITLE.format(id=ident),
            "doc_id": self._CITATION_DOC_TEMPLATE.format(**context),
            "heading": self._CITATION_HEADING,
            "source_refs": [dict(self._CITATION_SOURCE)],
            "commit": None,
            "status": self.status,
        }
