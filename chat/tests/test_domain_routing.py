import pytest

from chat.retrieval.domain.routing import (
    extract_project_id,
    extract_project_ids,
    extract_third_party_username,
    is_stats_intent,
    is_third_party_user_query,
    route_query,
)


class TestExtractProjectId:
    @pytest.mark.parametrize(
        "q,pid",
        [
            ("How many tasks are in project 123?", 123),
            ("how many tasks in project #123?", 123),
            ("What is the status of Project ID 7?", 7),
            ("tasks in PROJECT 42 and how do I validate?", 42),
            ("How do I validate a task?", None),
            ("I have 123 apples", None),
            ("In 2024 we mapped a lot", None),
            ("", None),
        ],
    )
    def test_extract(self, q, pid):
        assert extract_project_id(q) == pid


class TestStatsIntent:
    def test_count_questions_are_stats(self):
        for q in [
            "How many tasks are in project 123?",
            "What is the total task count for project 5?",
            "Number of validated tasks in project 9?",
            "What is the status of tasks in project 11?",
        ]:
            assert is_stats_intent(q), q

    def test_howto_alone_is_not_stats(self):
        assert not is_stats_intent("How do I validate a task?")
        assert not is_stats_intent("How can I create a project?")

    def test_stats_wording_with_project_is_stats(self):
        assert is_stats_intent("What are the stats for project 123?")
        assert is_stats_intent("Compare the stats of project 123 and project 456")

    def test_stats_howto_without_project_stays_kb(self):
        r = route_query("How do stats work in the project?")
        assert r.route == "KB" and not r.needs_project_id

    def test_two_project_stats_asks_which_project(self):
        r = route_query("Compare the stats of project 123 and project 456")
        assert r.needs_project_id is True and r.ops == ("stats",)


class TestRouteQuery:
    def test_live_count_routes_domain(self):
        r = route_query("How many tasks are in project 123?")
        assert r.route == "DOMAIN" and r.project_id == 123

    def test_count_plus_howto_routes_both(self):
        r = route_query("How many tasks are in project 123 and how do I validate them?")
        assert r.route == "BOTH" and r.project_id == 123

    def test_howto_routes_kb(self):
        r = route_query("How do I validate a task?")
        assert r.route == "KB" and r.project_id is None

    def test_stats_without_project_routes_kb(self):
        # No project id and no my-work phrasing -> KB.
        r = route_query("How many tasks are in a typical project?")
        assert r.route == "KB"

    def test_empty_routes_kb(self):
        assert route_query("").route == "KB"
        assert route_query("   ").route == "KB"


class TestStructuralDefault:
    def test_named_project_defaults_to_summary(self):
        r = route_query("tell me about the project 123")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_project_question_defaults_to_summary(self):
        r = route_query("What is project 123?")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_bare_project_reference_defaults_to_summary(self):
        r = route_query("Project 123")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_url_reference_defaults_to_summary(self):
        r = route_query("i meant this project http://127.0.0.1:3000/projects/123")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_explicit_op_is_not_widened(self):
        assert route_query("How many tasks are in project 123?").ops == ("stats",)

    def test_howto_with_named_project_stays_kb(self):
        # Spec P1.3: procedural asks naming a project do not fetch a summary
        # (corpus golden-tm-eval-024 class).
        r = route_query("How do I map a task in project 123?")
        assert r.route == "KB" and r.ops == ()

    def test_mywork_is_not_overridden(self):
        r = route_query("My tasks in project 123")
        assert r.route == "DOMAIN" and r.ops == ("mywork",)

    def test_multi_project_reference_stays_kb(self):
        assert route_query("tell me about project 123 and project 456").route == "KB"

    def test_unnamed_project_stays_kb(self):
        assert route_query("What is mapping about in this project?").route == "KB"

    def test_bare_number_stays_kb(self):
        assert route_query("I have 123 apples").route == "KB"


class TestSummaryRouting:
    def test_status_routes_domain_summary(self):
        r = route_query("What is the status of project 123?")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_private_routes_domain_summary(self):
        r = route_query("Is project 7 private?")
        assert r.route == "DOMAIN" and r.project_id == 7 and r.ops == ("summary",)

    def test_stats_op_selected_alone(self):
        r = route_query("How many tasks are in project 123?")
        assert r.route == "DOMAIN" and r.ops == ("stats",)

    def test_stats_and_summary_together(self):
        r = route_query("How many tasks are in project 123 and is it private?")
        assert r.route == "DOMAIN" and r.project_id == 123
        assert r.ops == ("stats", "summary")

    def test_summary_plus_howto_routes_both(self):
        r = route_query("What is the status of project 123 and how do I map a task?")
        assert r.route == "BOTH" and r.project_id == 123 and r.ops == ("summary",)

    def test_details_routes_domain_summary(self):
        r = route_query("Give me details about the project 123")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("summary",)

    def test_info_overview_summary_nouns_route_domain(self):
        for q in [
            "Give me info on project 7",
            "Project 123 overview",
            "project 123 summary",
            "Summarize project 123",
        ]:
            r = route_query(q)
            assert r.route == "DOMAIN" and r.ops == ("summary",), q

    def test_details_without_project_asks_which(self):
        r = route_query("Where are the project details shown?")
        assert r.route == "KB" and r.needs_project_id

    def test_bare_about_stays_kb(self):
        # "about" alone is too broad to imply live attributes.
        assert route_query("What is mapping about in this project?").route == "KB"

    def test_kb_route_has_no_ops(self):
        r = route_query("How do I validate a task?")
        assert r.route == "KB" and r.ops == ()


class TestTeamsRouting:
    def test_teams_routes_domain(self):
        r = route_query("What teams are associated with project 123?")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("teams",)

    def test_members_routes_domain(self):
        r = route_query("Who are the members of project 123?")
        assert r.route == "DOMAIN" and r.project_id == 123 and r.ops == ("teams",)

    def test_stats_and_teams_together(self):
        r = route_query("How many tasks are in project 123 and which teams work on it?")
        assert r.route == "DOMAIN" and r.project_id == 123
        assert r.ops == ("stats", "teams")

    def test_teams_plus_howto_routes_both(self):
        r = route_query("Which teams work on project 5 and how do I join a team?")
        assert r.route == "BOTH" and r.project_id == 5 and r.ops == ("teams",)

    def test_team_howto_without_project_stays_kb(self):
        assert route_query("How do I join a team?").route == "KB"


class TestChatRouting:
    def test_comments_route_domain(self):
        r = route_query("What are the recent comments on project 5?")
        assert r.route == "DOMAIN" and r.project_id == 5 and r.ops == ("chat",)

    def test_chat_noun_routes_domain(self):
        r = route_query("Show me the chat for project 5")
        assert r.route == "DOMAIN" and r.ops == ("chat",)

    def test_chat_plus_howto_routes_both(self):
        r = route_query(
            "What are people saying in project 5 comments and how do I comment?"
        )
        assert r.route == "BOTH" and r.ops == ("chat",)


class TestMyWorkRouting:
    def test_my_tasks_routes_domain_without_project(self):
        r = route_query("What tasks am I working on?")
        assert r.route == "DOMAIN" and r.project_id is None and r.ops == ("mywork",)

    def test_mapped_count_routes_contributions(self):
        # Count questions need lifetime totals, not the locked-task snapshot.
        r = route_query("How many tasks have I mapped?")
        assert r.route == "DOMAIN" and r.ops == ("user_contributions",)

    def test_mywork_plus_howto_routes_both(self):
        r = route_query("My task is locked, how do I unlock it?")
        assert r.project_id is None and "mywork" in r.ops


class TestUserCapabilityRouting:
    def test_mapper_level_routes_profile(self):
        # Corpus golden-tm-eval-001: the "what do I need" clause keeps KB (BOTH).
        r = route_query(
            "What's my mapper level, and what do I need to reach the next one?"
        )
        assert r.route == "BOTH" and "user_profile" in r.ops

    def test_badges_routes_profile(self):
        for q in [
            "What badges have I earned?",
            "Which badges are on my profile?",
            "Do I have any badges?",
        ]:
            r = route_query(q)
            assert r.route == "DOMAIN" and r.ops == ("user_profile",), q

    def test_badge_howto_stays_kb(self):
        assert route_query("How do I earn badges?").route == "KB"

    def test_hours_routes_contributions(self):
        r = route_query("How many hours have I contributed?")
        assert r.route == "DOMAIN" and r.ops == ("user_contributions",)

    def test_month_comparison_routes_contributions(self):
        r = route_query("How is my contribution this month compared to last month?")
        assert r.route == "DOMAIN" and r.ops == ("user_contributions",)

    def test_contributed_projects_routes_contributions(self):
        r = route_query("What are the projects I have contributed to?")
        assert r.route == "DOMAIN" and r.ops == ("user_contributions",)

    def test_streak_routes_activity(self):
        r = route_query("What's my current mapping streak?")
        assert r.route == "DOMAIN" and r.ops == ("user_activity",)

    def test_validation_mapping_split_routes_activity(self):
        r = route_query("What's my validation-vs-mapping split?")
        assert r.route == "DOMAIN" and r.ops == ("user_activity",)

    def test_my_teams_routes_user_teams(self):
        for q in [
            "What teams am I part of?",
            "Which teams am I a member of?",
        ]:
            r = route_query(q)
            assert r.route == "DOMAIN" and r.ops == ("user_teams",), q

    def test_locked_task_any_word_order_routes_mywork(self):
        for q in [
            "What task do I currently have locked?",
            "Show my locked tasks",
            "Which tasks are locked by me?",
        ]:
            r = route_query(q)
            assert r.route == "DOMAIN" and "mywork" in r.ops, q

    def test_submitted_task_status_routes_user_tasks(self):
        r = route_query("Has my submitted task been validated yet?")
        assert r.route == "DOMAIN" and r.ops == ("user_tasks",)

    def test_invalidation_why_keeps_kb_evidence(self):
        # Corpus golden-tm-eval-022: a "why" invalidation ask keeps KB (BOTH).
        r = route_query("Why was my last task invalidated?")
        assert r.route == "BOTH" and r.ops == ("user_tasks",)

    def test_generic_howto_stays_kb_for_personal_domains(self):
        for q in [
            "How do I create a project?",
            "How do I validate a task?",
        ]:
            assert route_query(q).route == "KB", q

    def test_level_howto_routes_both(self):
        r = route_query("How do I reach the next mapping level?")
        assert r.route == "BOTH" and r.ops == ("user_profile",)


class TestGlobalStatsRouting:
    def test_registered_users_routes_global(self):
        r = route_query("How many users are registered on Tasking Manager?")
        assert r.route == "DOMAIN" and r.ops == ("global_stats",)

    def test_project_count_routes_global(self):
        r = route_query("How many projects are there on Tasking Manager?")
        assert r.route == "DOMAIN" and r.ops == ("global_stats",)

    def test_total_tasks_routes_global(self):
        r = route_query("How many tasks have been mapped/validated in total?")
        assert r.route == "DOMAIN" and r.ops == ("global_stats",)

    def test_project_scoped_count_still_stats(self):
        r = route_query("How many tasks are in project 123?")
        assert r.ops == ("stats",)

    def test_personal_count_still_contributions(self):
        r = route_query("How many tasks have I mapped?")
        assert r.ops == ("user_contributions",)


class TestProjectDiscoveryRouting:
    def test_country_routes_project_search(self):
        r = route_query("Which projects are in Kenya?")
        assert r.route == "DOMAIN" and r.ops == ("project_search",)
        assert r.filters.get("country") == "Kenya"

    def test_expiring_defaults_to_14_days(self):
        r = route_query("Which projects are expiring soon?")
        assert r.ops == ("project_search",)
        assert r.filters.get("expiring_days") == "14"

    def test_expiring_window_is_parsed(self):
        r = route_query("Which projects are expiring within 30 days?")
        assert r.filters.get("expiring_days") == "30"

    def test_beginner_routes_difficulty(self):
        r = route_query("Which projects are beginner-friendly?")
        assert r.ops == ("project_search",)
        assert r.filters.get("difficulty") == "EASY"

    def test_skill_match_sets_flag(self):
        r = route_query("Which projects match my skill level?")
        assert r.filters.get("based_on_skill") == "true"

    def test_health_routes_text_search(self):
        r = route_query("How many health-oriented projects are there?")
        assert r.ops == ("project_search",)
        assert r.filters.get("text_search") == "health"

    def test_short_on_mappers_sets_flag(self):
        r = route_query("Which projects are short on mappers?")
        assert r.filters.get("short_on_mappers") == "true"

    def test_organisation_routes_project_search(self):
        r = route_query("Which projects run by Humanitarian OpenStreetMap Team?")
        assert r.ops == ("project_search",)
        assert r.filters.get("organisation") == "Humanitarian OpenStreetMap Team"

    def test_org_howto_is_not_project_search(self):
        r = route_query("How do I get my organization added to Tasking Manager?")
        assert r.route == "KB" and r.ops == ()
        assert r.filters == {}


class TestTrendingAndRecommendationRouting:
    def test_trending_routes_trending(self):
        r = route_query("What are the most active projects right now?")
        assert r.route == "DOMAIN" and r.ops == ("trending_projects",)

    def test_recommendation_routes_user_recommendations(self):
        # Corpus golden-tm-eval-021: "based on" keeps KB evidence (BOTH).
        r = route_query("Recommend a project based on what I usually map")
        assert r.route == "BOTH" and r.ops == ("user_recommendations",)


class TestGenericHowToStaysKb:
    # Generic indefinite phrasing is KB how-to, not project-scoped intent:
    # it must reach retrieval instead of a project-id clarification.
    @pytest.mark.parametrize(
        "q",
        [
            "What is the status of a task?",
            "How do I get a task mapped?",
            "How do I join a project team?",
            "How do I comment on a project?",
            "How do I become the author of a project?",
        ],
    )
    def test_generic_howto_has_no_project_demand(self, q):
        r = route_query(q)
        assert r.route == "KB" and r.needs_project_id is False, q


class TestThirdPartyWorkingOnFallsThrough:
    def test_who_is_working_on_routes_project_summary(self):
        r = route_query("Who is working on project 5?")
        assert r.route == "DOMAIN" and r.project_id == 5 and r.ops == ("summary",)

    def test_teams_about_the_project_asks_which(self):
        r = route_query("Which teams are working on the project?")
        assert r.route == "KB" and r.needs_project_id is True and r.ops == ("teams",)

    def test_long_project_number_is_not_truncated(self):
        # Silently truncating to 8 digits would query the wrong project.
        assert extract_project_ids("How many tasks are in project 123456789?") == []
        r = route_query("How many tasks are in project 123456789?")
        assert r.route == "KB" and r.needs_project_id is True


class TestThirdPartyUserRouting:
    """Another person's profile data is never answered from asker evidence."""

    @pytest.mark.parametrize(
        "q",
        [
            "what badges has alice earned?",
            "how many tasks has bob mapped?",
            "what is alice's streak?",
            "show me @bob's profile",
            "how do I see another user's contributions?",
            "which projects did alice contribute to?",
            "what has alice mapped?",
            "what did alice map?",
            "what is alice working on?",
            "show me the profile of carol",
            "can I see other users' profiles?",
        ],
    )
    def test_third_party_profile_asks_detected(self, q):
        assert is_third_party_user_query(q), q

    @pytest.mark.parametrize(
        "q",
        [
            "what badges have I earned?",
            "what's my mapping streak?",
            "how many tasks have I mapped?",
            "how many hours have I contributed?",
            "what are the projects I have contributed to?",
            "how do I earn badges?",
            "how do I update my profile?",
            "can another user see my profile?",
            "can other users see my contributions?",
            "who is working on project 5?",
            "which teams are working on the project?",
            "how many tasks were validated last month?",
            "how many users are registered on Tasking Manager?",
            "my task is locked, how do I unlock it?",
            "which tasks are locked by me?",
        ],
    )
    def test_asker_and_project_asks_not_third_party(self, q):
        assert not is_third_party_user_query(q), q

    @pytest.mark.parametrize(
        "q,username",
        [
            ("what badges has alice earned?", "alice"),
            ("what is alice's streak?", "alice"),
            ("show me @bob's profile", "bob"),
            ("show me the profile of carol", "carol"),
            ("how do I see another user's contributions?", None),
            ("how many tasks have I mapped?", None),
        ],
    )
    def test_username_extraction(self, q, username):
        assert extract_third_party_username(q) == username

    @pytest.mark.parametrize(
        "q",
        [
            "what is alice's streak?",
            "which projects did alice contribute to?",
            "what badges has alice earned?",
            "what teams is alice part of?",
        ],
    )
    def test_third_party_asks_never_route_to_asker_ops(self, q):
        r = route_query(q)
        assert r.route == "KB" and r.ops == (), q
