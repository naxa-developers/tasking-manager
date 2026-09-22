from __future__ import annotations

from typing import Any, Optional, Tuple

from loguru import logger

from chat.retrieval.domain.evidence import DomainStatus


async def can_read_project(user_id: int, project_id: int, db: Any) -> Optional[Any]:
    """Return the project row if user_id may read it, else None.

    Visibility (public/draft/private, manager/allowed-list/team) is owned by
    ``ProjectService.can_user_read_project`` — the same predicate the project
    APIs use — so RAG permissions can never drift from API permissions.
    """
    from backend.exceptions import NotFound
    from backend.services.project_service import ProjectService

    try:
        project = await ProjectService.get_project_by_id(project_id, db)
    except NotFound:
        return None
    except Exception:
        return None
    if project is None:
        return None
    try:
        if await ProjectService.can_user_read_project(project, user_id, db):
            return project
    except Exception:
        return None
    return None


async def authorize_project(
    user_id: int, project_id: int, db: Any
) -> Tuple[DomainStatus, Optional[Any]]:
    """Auth-first gate: (status, project); project is set only when status OK."""
    try:
        project = await can_read_project(user_id, project_id, db)
    except Exception:
        logger.exception(f"domain auth check failed for project {project_id}")
        return "NOT_FOUND", None
    if project is not None:
        return "OK", project

    try:
        from backend.exceptions import NotFound
        from backend.services.project_service import ProjectService

        await ProjectService.exists(project_id, db)
        return "UNAUTHORIZED", None
    except NotFound:
        return "NOT_FOUND", None
    except Exception:
        logger.exception(f"domain existence check failed for project {project_id}")
        return "NOT_FOUND", None
