"""Qwen3 tokenizer for RAG prompt fitting (runtime-only).

Loads the official ``Qwen/Qwen3-1.7B`` ``tokenizer.json`` vendored at
``chat/retrieval/tokenizers/qwen3-1.7b.json`` (gitignored, scp like
``chunks.json``) or overridden via ``RAG_TOKENIZER_PATH``.

No tiktoken import, no fallback: a missing artifact fails loudly so a
mis-deployed host never silently mis-budgets prompts.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from tokenizers import Tokenizer

VENDORED_PATH = Path(__file__).resolve().parent / "tokenizers" / "qwen3-1.7b.json"
ENV_VAR = "RAG_TOKENIZER_PATH"

_lock = threading.Lock()
_tok = None


def get_tokenizer() -> Tokenizer:
    """Return the cached Qwen3 tokenizer (thread-safe, loaded once)."""
    global _tok
    if _tok is None:
        with _lock:
            if _tok is None:
                raw = os.getenv(ENV_VAR, "").strip()
                path = Path(raw) if raw else VENDORED_PATH
                if not path.is_file():
                    raise RuntimeError(
                        f"Qwen tokenizer missing at {path}; "
                        "scp qwen3-1.7b.json there (see deploy runbook)"
                    )
                try:
                    _tok = Tokenizer.from_file(str(path))
                except Exception as exc:
                    raise RuntimeError(
                        f"Qwen tokenizer corrupt at {path}: {exc}"
                    ) from exc
    return _tok


def count_tokens(text: str) -> int:
    """Count Qwen3 tokens (no special tokens)."""
    if not text:
        return 0
    return len(get_tokenizer().encode(text, add_special_tokens=False).ids)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Trim text to at most ``max_tokens`` Qwen tokens on a token boundary."""
    if max_tokens <= 0:
        return ""
    if count_tokens(text) <= max_tokens:
        return text
    ids = get_tokenizer().encode(text, add_special_tokens=False).ids[:max_tokens]
    return get_tokenizer().decode(ids).rstrip() + " …"
