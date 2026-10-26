from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from loguru import logger

from chat.domain._rows import _attr
from chat.domain.auth import authorize_project
from chat.domain.evidence import DomainStatus, EvidenceBase, safe_value

ANNOTATIONS_OPERATION = "get_project_annotations"
ANNOTATIONS_PROVENANCE = "TaskAnnotation.get_task_annotations_by_project_id"

# Per-op prompt-size guard for the annotation list.
_MAX_ANNOTATIONS = 20


@dataclass(frozen=True)
class AnnotationEntry:
    task_id: Optional[int]
    annotation_type: Optional[str] = None
    annotation_source: Optional[str] = None
    excerpt: Optional[str] = None


@dataclass(frozen=True)
class ProjectAnnotationsEvidence(EvidenceBase):
    """Task annotations (issues flagged on tasks) for one project.

    Mirrors ``TaskAnnotation.get_task_annotations_by_project_id``: per-type
    counts plus a bounded list with task id, type, source, and a markdown
    excerpt. The per-type endpoint is the same data filtered, so one op
    carries both; per-task comments stay out (no task-id route).
    """

    status: DomainStatus
    project_id: int
    operation: str = ANNOTATIONS_OPERATION
    annotations_total: Optional[int] = None
    by_type: Tuple[Tuple[str, int], ...] = ()
    annotations: Tuple[AnnotationEntry, ...] = ()
    provenance: str = ANNOTATIONS_PROVENANCE

    _CITATION_KIND = "annotations"
    _CITATION_TITLE = "Project {id} task annotations"
    _CITATION_HEADING = "project_annotations"
    _CITATION_SOURCE = {
        "path": "backend/models/postgis/task_annotation.py",
        "symbol": "TaskAnnotation.get_task_annotations_by_project_id",
    }

    def _scope_id(self) -> Any:
        return self.project_id

    def _body_lines(self) -> List[str]:
        lines: List[str] = []
        if self.by_type:
            breakdown = ", ".join(
                f"{count} {safe_value(name, 32)}" for name, count in self.by_type
            )
            lines.append(f"annotations_by_type: {breakdown}")
        if self.annotations:
            shown = self.annotations[:_MAX_ANNOTATIONS]
            label = "task_annotations"
            if self.annotations_total is not None and self.annotations_total > len(
                shown
            ):
                label += f" (showing {len(shown)} of {self.annotations_total})"
            else:
                label += f" (complete list, {len(shown)} items)"
            lines.append(label + ":")
            for position, row in enumerate(shown, start=1):
                parts = [f"task #{row.task_id}"]
                if row.annotation_type:
                    parts.append(safe_value(row.annotation_type, 32))
                if row.annotation_source:
                    parts.append(f"by {safe_value(row.annotation_source, 64)}")
                if row.excerpt:
                    parts.append(safe_value(row.excerpt, 120))
                lines.append(f"{position}. " + " | ".join(parts))
        elif self.annotations_total == 0:
            lines.append("task_annotations: none")
        return lines


async def get_project_annotations_evidence(
    user_id: int, project_id: int, db: Any
) -> ProjectAnnotationsEvidence:
    """Authorized read-only task-annotation summary for one project."""
    status, _project = await authorize_project(user_id, project_id, db)
    if status != "OK":
        return ProjectAnnotationsEvidence(status=status, project_id=project_id)

    from backend.models.postgis.task_annotation import TaskAnnotation

    entries: List[AnnotationEntry] = []
    try:
        dto = await TaskAnnotation.get_task_annotations_by_project_id(project_id, db)
        for row in _attr(dto, "tasks") or []:
            entries.append(
                AnnotationEntry(
                    task_id=_attr(row, "task_id"),
                    annotation_type=_attr(row, "annotation_type"),
                    annotation_source=_attr(row, "annotation_source"),
                    excerpt=_attr(row, "annotation_markdown"),
                )
            )
    except Exception:
        logger.exception(f"project {project_id} annotations fetch failed")
        return ProjectAnnotationsEvidence(status="UNAVAILABLE", project_id=project_id)

    counts: Counter = Counter()
    for entry in entries:
        if entry.annotation_type:
            counts[str(entry.annotation_type)] += 1

    return ProjectAnnotationsEvidence(
        status="OK",
        project_id=project_id,
        annotations_total=len(entries),
        by_type=tuple(counts.most_common()),
        annotations=tuple(entries),
    )
