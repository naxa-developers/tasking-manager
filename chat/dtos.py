from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from chat.constants import MAX_QUESTION_CHARS


class RagChatRequestDTO(BaseModel):
    """An incoming chat question."""

    question: str = Field(..., max_length=MAX_QUESTION_CHARS)
    stream: Optional[bool] = True


class RagSessionCreateDTO(BaseModel):
    """Payload for creating a chat session."""

    title: Optional[str] = "New chat"


class RagSessionUpdateDTO(BaseModel):
    """Payload for updating a chat session."""

    title: Optional[str] = None


class RagCitationDTO(BaseModel):
    """One answer citation."""

    id: str
    title: str
    doc_id: str
    heading: str
    source_refs: List[Dict[str, Any]]
    commit: Optional[str] = None


class RagChatResponseDTO(BaseModel):
    """A non-streamed chat answer."""

    answer: str
    degraded: bool
    candidate_count: int
    guardrail: Optional[str] = None
    model: Optional[str] = None  # None for deterministic (canned) answers
    session_id: str


class RagMessageDTO(BaseModel):
    """One persisted session message."""

    role: str
    content: str
    model: Optional[str] = None
    candidate_count: Optional[int] = None
    created_at: Optional[str] = None


class RagSessionDTO(BaseModel):
    """A chat session row."""

    id: str
    title: str
    user_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0
