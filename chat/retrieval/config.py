from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


from dotenv import load_dotenv  # type: ignore
from llama_index.embeddings.litellm import LiteLLMEmbedding  # type: ignore

load_dotenv(Path(__file__).resolve().parents[2] / "tasking-manager.env", override=False)


# Env parsing helpers — one place for getenv/convert/fallback.
def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _env_optional(*names: str) -> Optional[str]:
    """First non-empty env var among names, in order."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


# LiteLLM / embedding


# Per-model instruction prefixes: query at retrieval time, doc at index time.
MODEL_PREFIXES: dict = {
    "Qwen/Qwen3-Embedding-0.6B": (
        "Instruct: Given a question about the HOT Tasking Manager, retrieve relevant documentation passages that answer the question\nQuery: ",
        "",
    ),
}


def lookup_model_prefixes(model: str) -> tuple:
    """Return (query_prefix, doc_prefix) for an embedding model id."""
    mid = (model or "").strip()
    if mid in MODEL_PREFIXES:
        return MODEL_PREFIXES[mid]
    # Allow "<provider>/<id>" variants to resolve to the bare-id entry.
    for key, prefixes in MODEL_PREFIXES.items():
        if mid.endswith("/" + key) or mid.endswith(key):
            return prefixes
    return ("", "")


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str  # litellm embedding model id (required: EMBEDDING_MODEL)
    dimension: int  # embedding dimension (required: EMBEDDING_DIMENSION)
    api_key: Optional[str]
    api_base: Optional[str]
    query_prefix: str = ""  # prepended to queries at retrieval time
    doc_prefix: str = ""  # prepended to chunk texts at index time

    def require_api_key(self) -> str:
        if not self.api_key:
            raise RuntimeError(
                "Embedding API key is not configured — set LLM_API_KEY (or LITELLM_API_KEY) "
                "in tasking-manager.env (see example.env TMBot section). "
                f"model={self.model} dim={self.dimension}"
            )
        return self.api_key

    def apply_query_prefix(self, text: str) -> str:
        return f"{self.query_prefix}{text}" if self.query_prefix else text

    def apply_doc_prefix(self, text: str) -> str:
        return f"{self.doc_prefix}{text}" if self.doc_prefix else text


def get_embedding_config() -> EmbeddingConfig:
    model = (_env_optional("EMBEDDING_MODEL") or "").strip()
    if not model:
        raise RuntimeError(
            "Embedding model is not configured — set EMBEDDING_MODEL in "
            "tasking-manager.env (see example.env TMBot section)."
        )
    dimension = _env_int("EMBEDDING_DIMENSION", 0)
    if dimension <= 0:
        raise RuntimeError(
            "Embedding dimension is not configured — set EMBEDDING_DIMENSION in "
            "tasking-manager.env to match the indexed vectors (see example.env "
            "TMBot section)."
        )
    api_key = _env_optional("LLM_API_KEY", "LITELLM_API_KEY")
    api_base = _env_optional("EMBEDDING_API_BASE", "LLM_API_BASE", "LITELLM_API_BASE")
    reg_q, reg_d = lookup_model_prefixes(model)
    query_prefix = os.getenv("EMBEDDING_QUERY_PREFIX", reg_q)
    doc_prefix = os.getenv("EMBEDDING_DOC_PREFIX", reg_d)
    return EmbeddingConfig(
        model=model,
        dimension=dimension,
        api_key=api_key,
        api_base=api_base,
        query_prefix=query_prefix,
        doc_prefix=doc_prefix,
    )


@dataclass(frozen=True)
class GenerationConfig:
    model: str  # litellm model id (required: LITELLM_MODEL / GENERATION_MODEL)
    api_key: Optional[str]
    api_base: Optional[str]
    temperature: float
    max_tokens: int
    timeout: float
    drop_params: bool = True
    num_retries: int = 2

    def require_api_key(self) -> str:
        if not self.api_key:
            raise RuntimeError(
                "Generation API key is not configured — set LLM_API_KEY (or LITELLM_API_KEY) "
                f"in tasking-manager.env (see example.env TMBot section). model={self.model}"
            )
        return self.api_key


def get_generation_config() -> GenerationConfig:
    model = _env_optional("LITELLM_MODEL", "GENERATION_MODEL")
    if not model:
        raise RuntimeError(
            "Generation model is not configured — set LITELLM_MODEL (or "
            "GENERATION_MODEL) in tasking-manager.env (see example.env TMBot "
            "section)."
        )
    model = model.strip()
    api_key = _env_optional("LLM_API_KEY", "LITELLM_API_KEY")
    api_base = _env_optional("GENERATION_API_BASE", "LLM_API_BASE", "LITELLM_API_BASE")
    temp = _env_float("LITELLM_TEMPERATURE", 0.2)
    max_tokens = _env_int("LITELLM_MAX_TOKENS", 512)
    timeout = _env_float("LITELLM_TIMEOUT", 30.0)
    num_retries = max(0, _env_int("LITELLM_NUM_RETRIES", 2))
    return GenerationConfig(
        model=model,
        api_key=api_key,
        api_base=api_base,
        temperature=temp,
        max_tokens=max_tokens,
        timeout=timeout,
        num_retries=num_retries,
    )


# pgvector


@dataclass(frozen=True)
class PGVectorConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    table_name: str
    table_test: str
    embed_dim: int

    def connection_string(self, async_: bool = False) -> str:
        proto = "postgresql+asyncpg://" if async_ else "postgresql://"
        return f"{proto}{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"

    def pgvector_connection_kwargs(self) -> dict:
        return dict(host=self.host, port=self.port, database=self.database, user=self.user, password=self.password)


def get_pgvector_config(embed_dim: Optional[int] = None) -> PGVectorConfig:
    # PGVECTOR_* wins; POSTGRES_* fallback lets deployments reuse the RDS creds.
    host = os.getenv("PGVECTOR_HOST") or os.getenv("POSTGRES_ENDPOINT") or "localhost"
    # tm-db single DB
    port = _env_int("PGVECTOR_PORT", _env_int("POSTGRES_PORT", 5432))
    database = (
        os.getenv("PGVECTOR_DATABASE")
        or os.getenv("PGVECTOR_DB")
        or os.getenv("POSTGRES_DB")
        or "rag"
    )
    user = os.getenv("PGVECTOR_USER") or os.getenv("POSTGRES_USER") or "rag"
    password = os.getenv("PGVECTOR_PASSWORD") or os.getenv("POSTGRES_PASSWORD") or "rag"
    table_name = os.getenv("PGVECTOR_TABLE", "kb_nodes")
    table_test = os.getenv("PGVECTOR_TABLE_TEST", "kb_nodes_test")
    if embed_dim is None:
        embed_dim = get_embedding_config().dimension
    return PGVectorConfig(
        host=host, port=port, database=database, user=user, password=password, table_name=table_name, table_test=table_test, embed_dim=embed_dim
    )


# LlamaIndex embedding model — official LiteLLM integration (provider-agnostic)


class LiteLLMEmbeddingAdapter(LiteLLMEmbedding):
    """Official LlamaIndex LiteLLMEmbedding plus instruction prefixes.

    Instruction-tuned embedders (e.g. Qwen3-Embedding) need a prefix; models
    without an instruction schema do not. Prefixes are applied here — right
    before the provider call — so the configured values stay empty by default
    and any LiteLLM-routed embedder keeps working.
    """

    api_base: Optional[str] = None
    query_prefix: str = ""
    doc_prefix: str = ""

    @staticmethod
    def _prefixed(prefix: str, text: str) -> str:
        return f"{prefix}{text}" if prefix else text

    def _get_query_embedding(self, query: str) -> List[float]:
        return super()._get_query_embedding(self._prefixed(self.query_prefix, query))

    def _get_text_embedding(self, text: str) -> List[float]:
        return super()._get_text_embedding(self._prefixed(self.doc_prefix, text))

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return super()._get_text_embeddings(
            [self._prefixed(self.doc_prefix, text) for text in texts]
        )


def get_embedding_model() -> LiteLLMEmbeddingAdapter:
    """Return a LlamaIndex-compatible embedding model via LiteLLM."""
    cfg = get_embedding_config()
    cfg.require_api_key()
    return LiteLLMEmbeddingAdapter(
        model_name=cfg.model,
        api_key=cfg.api_key or "",
        api_base=cfg.api_base,
        query_prefix=cfg.query_prefix,
        doc_prefix=cfg.doc_prefix,
    )


def get_vector_store(table_name: Optional[str] = None, embed_dim: Optional[int] = None):  # type: ignore[no-untyped-def]
    pg_cfg = get_pgvector_config(embed_dim=embed_dim)
    if table_name:
        pg_cfg = PGVectorConfig(
            host=pg_cfg.host,
            port=pg_cfg.port,
            database=pg_cfg.database,
            user=pg_cfg.user,
            password=pg_cfg.password,
            table_name=table_name,
            table_test=pg_cfg.table_test,
            embed_dim=pg_cfg.embed_dim,
        )
    try:
        from llama_index.vector_stores.postgres import PGVectorStore  # type: ignore
    except ImportError as e:
        raise ImportError(
            "llama-index-vector-stores-postgres not installed. "
            "Install requirements.txt (project root) / pyproject.toml "
            f"({e})"
        ) from e
    if hasattr(PGVectorStore, "from_params"):
        return PGVectorStore.from_params(
            database=pg_cfg.database,
            host=pg_cfg.host,
            password=pg_cfg.password,
            port=pg_cfg.port,
            user=pg_cfg.user,
            table_name=pg_cfg.table_name,
            embed_dim=pg_cfg.embed_dim,
        )
    return PGVectorStore(connection_string=pg_cfg.connection_string(), table_name=pg_cfg.table_name, embed_dim=pg_cfg.embed_dim)


def get_db_connection():  # type: ignore[no-untyped-def]
    pg_cfg = get_pgvector_config()
    try:
        import psycopg  # type: ignore

        return psycopg.connect(host=pg_cfg.host, port=pg_cfg.port, dbname=pg_cfg.database, user=pg_cfg.user, password=pg_cfg.password)
    except ImportError:
        pass
    try:
        import psycopg2  # type: ignore

        return psycopg2.connect(host=pg_cfg.host, port=pg_cfg.port, dbname=pg_cfg.database, user=pg_cfg.user, password=pg_cfg.password)
    except ImportError as e:
        raise ImportError("psycopg or psycopg2 required (psycopg[binary])") from e
