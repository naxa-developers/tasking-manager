class RagAnswerFailed(Exception):
    """Non-streamed LLM generation failed; the API maps it to a 503 body."""
