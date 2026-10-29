from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from chat.env import env_float, env_int
from chat.retrieval import RetrievalResponse, ScoredNode

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


@dataclass(frozen=True)
class GateConfig:
    """Thresholds for the dense/lexical relevance gate."""

    dense_threshold: float
    dense_floor: float
    coverage_threshold: float
    arm_top_k: int


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    reason: str
    dense_top1: Optional[float]
    coverage: float
    dense_threshold: float


def get_gate_config() -> GateConfig:
    """Read gate thresholds from the environment."""
    dense_threshold = env_float("RAG_DENSE_SCORE_THRESHOLD", 0.35)
    dense_floor = env_float("RAG_DENSE_SCORE_FLOOR", 0.20)
    coverage_threshold = env_float("RAG_TERM_COVERAGE_THRESHOLD", 0.75)
    arm_top_k = max(1, env_int("RAG_RETRIEVAL_ARM_TOP_K", 30))
    if dense_floor > dense_threshold:
        dense_floor = dense_threshold
    return GateConfig(
        dense_threshold=dense_threshold,
        dense_floor=dense_floor,
        coverage_threshold=coverage_threshold,
        arm_top_k=arm_top_k,
    )


def _terms(text: str) -> list[str]:
    return [
        word
        for word in _WORD_RE.findall((text or "").lower())
        if len(word) > 2 and word not in _STOPWORDS
    ]


def lexical_coverage(question: str, text: str) -> float:
    """Fraction of meaningful query terms present in ``text``."""
    wanted = set(_terms(question))
    if not wanted:
        return 0.0
    present = set(_terms(text))
    return len(wanted & present) / len(wanted)


def _gate_for_top(
    top: ScoredNode,
    question: str,
    config: GateConfig,
) -> GateDecision:
    dense = top.vector_score
    if dense is None:
        # The vector arm reported no score. Don't reject a usable result on a
        # missing diagnostic; retrieval health is reported separately.
        return GateDecision(
            allow=True,
            reason="dense_score_missing",
            dense_top1=None,
            coverage=0.0,
            dense_threshold=config.dense_threshold,
        )

    coverage = lexical_coverage(question, top.node.get_content() or "")
    if dense >= config.dense_threshold:
        return GateDecision(
            allow=True,
            reason="dense_above_threshold",
            dense_top1=dense,
            coverage=coverage,
            dense_threshold=config.dense_threshold,
        )
    if dense >= config.dense_floor and coverage >= config.coverage_threshold:
        return GateDecision(
            allow=True,
            reason="lexical_rescue",
            dense_top1=dense,
            coverage=coverage,
            dense_threshold=config.dense_threshold,
        )
    return GateDecision(
        allow=False,
        reason="below_threshold",
        dense_top1=dense,
        coverage=coverage,
        dense_threshold=config.dense_threshold,
    )


def gate_decision(
    response: RetrievalResponse,
    question: str,
    config: Optional[GateConfig] = None,
) -> GateDecision:
    """Whether the KB arm has enough evidence to justify generation."""
    cfg = config or get_gate_config()
    results: Sequence[ScoredNode] = response.results or ()
    if not results:
        return GateDecision(
            allow=False,
            reason="no_results",
            dense_top1=None,
            coverage=0.0,
            dense_threshold=cfg.dense_threshold,
        )
    return _gate_for_top(results[0], question, cfg)


def is_low_confidence(
    response: RetrievalResponse,
    question: str,
    config: Optional[GateConfig] = None,
) -> bool:
    """True when the KB response must be replaced by canned copy."""
    return not gate_decision(response, question, config).allow
