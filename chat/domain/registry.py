from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Tuple

# Handlers have one of four call shapes, decided by ``scope``.
Fetcher = Callable[..., Awaitable[Any]]


def _loader(module: str, function: str) -> Callable[[], Fetcher]:
    """Resolve a fetcher lazily so importing this table stays cheap."""

    def load() -> Fetcher:
        mod = importlib.import_module(f"chat.domain.{module}")
        return getattr(mod, function)  # type: ignore[no-any-return]

    return load


@dataclass(frozen=True)
class Op:
    """One read-only capability the router may select."""

    name: str
    instruction: str
    scope: str
    load: Callable[[], Fetcher]
    required_filters: Tuple[str, ...] = ()
    allowlisted_filters: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def needs_project_id(self) -> bool:
        return self.scope == "project"

    @property
    def takes_filters(self) -> bool:
        return self.scope == "filter"


OPS: Tuple[Op, ...] = (
    Op(
        "stats",
        "Task counts for one project.",
        "project",
        _loader("stats", "get_project_stats_evidence"),
    ),
    Op(
        "summary",
        "One project's status, difficulty, organisation, progress, dates.",
        "project",
        _loader("stats", "get_project_summary_evidence"),
    ),
    Op(
        "teams",
        "Teams or members on one project.",
        "project",
        _loader("teams", "get_project_teams_evidence"),
    ),
    Op(
        "chat",
        "Recent discussion or comments on one project.",
        "project",
        _loader("project_chat", "get_project_chat_evidence"),
    ),
    Op(
        "project_activity",
        "Latest task activity on one project.",
        "project",
        _loader("project_activity", "get_project_activity_evidence"),
    ),
    Op(
        "project_contributions",
        "Contributors or daily activity for one project.",
        "project",
        _loader("project_contributions", "get_project_contributions_evidence"),
    ),
    Op(
        "project_tasks",
        "Invalidated tasks, or which tasks a user mapped on one project.",
        "project",
        _loader("project_tasks", "get_project_tasks_evidence"),
    ),
    Op(
        "project_annotations",
        "Flagged task issues on one project.",
        "project",
        _loader("project_annotations", "get_project_annotations_evidence"),
    ),
    Op(
        "similar_projects",
        "Projects similar to one project.",
        "project",
        _loader("similar_projects", "get_similar_projects_evidence"),
    ),
    Op(
        "project_partners",
        "Partners on one project.",
        "project",
        _loader("project_partners", "get_project_partners_evidence"),
    ),
    Op(
        "campaigns",
        "Campaigns on a project, or site campaigns.",
        "optional_project",
        _loader("campaigns", "get_campaigns_evidence"),
    ),
    Op(
        "favorites",
        "The asker's saved/favorite projects.",
        "optional_project",
        _loader("favorites", "get_favorites_evidence"),
    ),
    Op(
        "user_tasks",
        "Whether the asker's own submitted tasks have been validated.",
        # Two-arg handler: it reads the asker's tasks, not one project's.
        "personal",
        _loader("user_tasks", "get_user_tasks_evidence"),
    ),
    Op(
        "mywork",
        "The asker's own locked or assigned tasks.",
        "personal",
        _loader("mywork", "get_mywork_evidence"),
    ),
    Op(
        "user_profile",
        "The asker's mapper level or badges.",
        "personal",
        _loader("user_profile", "get_user_profile_evidence"),
    ),
    Op(
        "user_contributions",
        "The asker's contribution totals: tasks mapped, projects, hours.",
        "personal",
        _loader("user_contributions", "get_user_contribution_evidence"),
    ),
    Op(
        "user_projects_created",
        "Projects the asker personally created.",
        "personal",
        _loader("user_projects", "get_user_projects_created_evidence"),
    ),
    Op(
        "user_org_projects",
        "Projects run by the asker's organisation.",
        "personal",
        _loader("user_orgs", "get_user_org_projects_evidence"),
    ),
    Op(
        "user_activity",
        "The asker's streak or mapping/validation split.",
        "personal",
        _loader("user_activity", "get_user_activity_evidence"),
    ),
    Op(
        "user_teams",
        "Teams the asker belongs to.",
        "personal",
        _loader("user_teams", "get_user_teams_evidence"),
    ),
    Op(
        "user_interests",
        "The asker's mapping interest mix.",
        "personal",
        _loader("user_interests", "get_user_interests_evidence"),
    ),
    Op(
        "user_osm_stats",
        "The asker's OSM account age or changeset count.",
        "personal",
        _loader("user_osm_stats", "get_user_osm_stats_evidence"),
    ),
    Op(
        "notifications",
        "The asker's notifications.",
        "personal",
        _loader("notifications", "get_notifications_evidence"),
    ),
    Op(
        "global_stats",
        "Site-wide totals: users, projects, or tasks overall.",
        "personal",
        _loader("global_stats", "get_global_stats_evidence"),
    ),
    Op(
        "featured_projects",
        "Site featured projects.",
        "personal",
        _loader("featured_projects", "get_featured_projects_evidence"),
    ),
    Op(
        "active_projects",
        "Recently active projects.",
        "personal",
        _loader("active_projects", "get_active_projects_evidence"),
    ),
    Op(
        "trending_projects",
        "Most active or popular projects right now.",
        "personal",
        _loader("trending", "get_trending_projects_evidence"),
    ),
    Op(
        "user_recommendations",
        "A project recommendation for the asker.",
        "personal",
        _loader("recommendations", "get_user_recommendation_evidence"),
    ),
    Op(
        "project_search",
        "Find projects by country, difficulty, organisation, campaign, "
        "expiry, mappers, or needing validation.",
        "filter",
        _loader("project_discovery", "get_project_search_evidence"),
        allowlisted_filters=(
            "difficulty",
            "based_on_skill",
            "expiring_days",
            "short_on_mappers",
            "text_search",
            "action",
            "country",
            "organisation",
            "campaign",
        ),
    ),
    Op(
        "organisation_info",
        "One named organisation's profile, projects, campaigns.",
        "filter",
        _loader("organisation_info", "get_organisation_info_evidence"),
        required_filters=("organisation",),
        allowlisted_filters=("organisation",),
    ),
    Op(
        "team_detail",
        "One team by number: details or members.",
        "filter",
        _loader("team_detail", "get_team_detail_evidence"),
        required_filters=("team_id",),
        allowlisted_filters=("team_id",),
    ),
)

OPS_BY_NAME: Dict[str, Op] = {op.name: op for op in OPS}

# Operations that cannot run without a single grounded project id.
PROJECT_OPS: Tuple[str, ...] = tuple(op.name for op in OPS if op.scope == "project")

MAX_OPS_PER_TURN = 4


def prompt_catalogue() -> str:
    """The op catalogue exactly as the router model sees it."""
    return "\n".join(f"- {op.name}: {op.instruction}" for op in OPS)


def resolve(op_name: str) -> Op:
    """Registry entry for ``op_name``; raises KeyError when unknown."""
    return OPS_BY_NAME[op_name]
