# Attribution worktable — 2026-10-13

## A1 — What's my mapper level, and what do I need to reach the next one?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["user_profile"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["user_profile"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_profile']
- kb top-5:
  1. `knowledge-base/general/07-mapper-levels-and-badges.md#h=mapper-levels#0` fused=0.0314
  2. `knowledge-base/mapper/02-project-page-and-task-selection.md#h=reading-the-project-page-and-selecting-a-task#0` fused=0.031
  3. `knowledge-base/general/05-roles-and-permissions-overview.md#h=who-can-map#1` fused=0.0306
  4. `knowledge-base/faq.md#h=do-i-need-prior-mapping-knowledge-to-participate#6` fused=0.0292
  5. `knowledge-base/general/05-roles-and-permissions-overview.md#h=teams-and-levels#2` fused=0.0279
- golden any-hit: **True**
  - knowledge-base/general/07-mapper-levels-and-badges.md -> {'rank': 1, 'node_id': 'knowledge-base/general/07-mapper-levels-and-badges.md#h=mapper-levels#0'}
- db expected: level ADVANCED; next-level requirements documented

### Qwen static

_llm_called=True; 38.23s; trace `0ce04151e712a7e92c2097eac39c646d`_

Your current mapper level is ADVANCED. To reach the next level, you need to meet or exceed the project's minimum mapping level, which is currently set to none (you are at the highest level). You can check your level progression by completing tasks and reviewing your statistics.

### DeepSeek (CLI answer)

_3.53s_

You're at the **Advanced** level — the highest mapper level, so there's no next level to reach.

Levels advance automatically based on your mapping and validation statistics after you complete tasks; since you're already at the top, there's nothing further required. One thing that can still grow is badges, which the system awards automatically when your statistics meet their milestones — you haven't earned any yet.

Next step: keep mapping and validating, and check your profile periodically to see whether any badge milestones have been met.

_replay trace: {"trace_id": "1d53202828f26cdb92c5dfbefdc26d41", "session_id": 513, "error": null, "llm_called": true}_

---

## A2 — What task do I currently have locked?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["mywork"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["mywork"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['mywork']
- db expected: locked_by=0 (no currently locked task)

### Qwen static

_llm_called=True; 1.46s; trace `604987e04091cedf4e4f9f9ef24d4309`_

You currently have no task locked.

### DeepSeek (CLI answer)

_2.6s_

You don't currently have any task locked.

If you want to lock a task, open a project's mapping or validation area and pick an available task, then select the lock option to start working on it.

_replay trace: {"trace_id": "0ac78f80e3452b7d2a507234a91ff9e2", "session_id": 514, "error": null, "llm_called": true}_

---

## A3 — What badges have I earned?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_profile"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_profile"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_profile']
- db expected: user_mapping_badge=0

### Qwen static

_llm_called=True; 2.93s; trace `b06fe0cde108a6fe6b917ad536a2e3b8`_

The available data does not include information about badges earned.

### DeepSeek (CLI answer)

_1.98s_

You haven't earned any badges yet — your badge count is 0.

Next step: keep contributing by mapping and validating tasks, and badges will appear on your profile as you meet their criteria.

_replay trace: {"trace_id": "936b7c1aa7188d15cef966425afc7558", "session_id": 515, "error": null, "llm_called": true}_

---

## A4 — How is my contribution this month compared to last month?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_contributions']
- db expected: task history 518/254/65; last action 2024-11-15 (monthly comparison from history)

### Qwen static

_llm_called=True; 12.02s; trace `ce23e97db7314e8fce3b77070b4376f7`_

The available data does not include specific information about your contribution this month compared to last month. A practical next step would be to check the "contributions_this_month" and "contributions_last_month" fields in the evidence.

### DeepSeek (CLI answer)

_2.33s_

You have no contributions this month or last month — both are zero.

For context, your all-time total is 225 hours across 27 projects. If you'd like to get back into it, a practical next step is to open the Contribute section and find a published project that needs mapping or validation.

_replay trace: {"trace_id": "48f40066bc2d6e520936632fe4ceb17f", "session_id": 516, "error": null, "llm_called": true}_

---

## A5 — What are the projects I have contributed to?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_contributions']
- db expected: projects_mapped=27

### Qwen static

_llm_called=True; 19.68s; trace `570605cdcea98c49d16819a83d968a13`_

The projects you have contributed to are:

1. #119 ward 7 tokha | mapped: 1 | validated: 0  
2. #114 Tokha ward 7 | mapped: 4 | validated: 0  
3. #99 Barbardiya municipality | no current tasks  
4. #98 Rapid edtor test | mapped: 1 | validated: 0  
5. #58 Rwanda replication | no current tasks  
6. #57 Rwanda | no current tasks  
7. #53 Shreepur | mapped: 1 | validated: 0  
8. #49 simlapur | mapped: 3 | validated: 0  
9. #30 Dodhara chadani | mapped: 16 | validated: 5  
10. #27 bangladesh | no current tasks  
11. #24 test 50 | mapped: 1 | validated: 0  
12. #23 test background | mapped: 3 | validated: 3  
13. #21 Mapping Landslides and Flood Disaster Response in Melamchi flood | no current tasks  
14. #20 test country tag | mapped: 7 | validated: 4  
15. #19 test project | mapped: 2 | validated: 0  
16. #17 sirte | status: ARCHIVED | mapped: 3 | validated: 0  
17. #15 libya Data quality monitoring test | mapped: 1 | validated: 0  
18. #14 Test dailekh | mapped: 75 | validated: 76  
19. #13 Palpa gulmi | status: DRAFT | no current tasks  
20. #11 Test project 4 | mapped: 4 | validated: 0  
21. #9 Test project 1 | status: ARCHIVED | mapped: 15 | validated: 15  
22. #7 Foobar | status: DRAFT | mapped: 8 | validated: 0  
23. #6 test by manjita | mapped: 159 | validated: 0  
24. #5 Testing 123 | status: ARCHIVED | mapped: 1 | validated: 1  
25. #3 Test by manjita | mapped: 140 | validated: 126  
26. #2 Test project with a long name | mapped: 6 | validated: 1  
27. #1 Home Playground | status: ARCHIVED | mapped: 2 | validated: 0

### DeepSeek (CLI answer)

_7.62s_

You've contributed to 27 projects in total. Here they all are:

- ward 7 tokha
- Tokha ward 7
- Barbardiya municipality
- Rapid edtor test
- Rwanda replication
- Rwanda
- Shreepur
- simlapur
- Dodhara chadani
- bangladesh
- test 50
- test background
- Mapping Landslides and Flood Disaster Response in Melamchi flood
- test country tag
- test project
- sirte
- libya Data quality monitoring test
- Test dailekh
- Palpa gulmi
- Test project 4
- Test project 1
- Foobar
- test by manjita
- Testing 123
- Test by manjita
- Test project with a long name
- Home Playground

Of these, 21 are published, 4 are archived, and 2 are draft. A couple of them currently have no open tasks, but your past contributions still count.

Next step: open your profile's contribution history in Tasking Manager if you want to see per-project task details.

_replay trace: {"trace_id": "9ed6b3b6991e260839d6b1c8b4c6a74d", "session_id": 511, "error": null, "llm_called": true}_

---

## A6 — What's my current mapping streak?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_activity"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_activity"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_activity']
- db expected: last action 2024-11-15 -> streak 0

### Qwen static

_llm_called=True; 2.55s; trace `8645c0f60457acfe0803083f8c82df0d`_

Current mapping streak: 0 days.

### DeepSeek (CLI answer)

_3.1s_

Your current mapping streak is **0 days** — you have no active mapping days in the last 30 days.

If you'd like to start one, mapping any task today would begin a new streak.

_replay trace: {"trace_id": "9348d5cef80f6658030f073a5f7e2b07", "session_id": 517, "error": null, "llm_called": true}_

---

## A7 — What's my validation-vs-mapping split?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_activity"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_activity"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_activity']
- db expected: 518/254/65 -> 33/67 validation-vs-mapping split

### Qwen static

_llm_called=True; 1.38s; trace `79ca79ab4ebed62094be49d739ffd9d1`_

The validation-vs-mapping split is 33% validation and 67% mapping.

### DeepSeek (CLI answer)

_2.42s_

Your split is 67% mapping and 33% validation.

Across your activity, you've mapped 518 tasks and validated 254, which lines up with that roughly two-thirds / one-third breakdown.

If you'd like to shift the balance, you could pick up more validation work by reviewing projects that are waiting for validation.

_replay trace: {"trace_id": "051f71d0f504f6f9a4b236db8dd20b10", "session_id": 518, "error": null, "llm_called": true}_

---

## A8 — What teams am I part of?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_teams"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_teams"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_teams']
- db expected: 9 teams

### Qwen static

_llm_called=True; 5.36s; trace `33c6062ba8f9d44b6b213d2f50cfb029`_

You are part of the following teams:

- Cool Cool team
- Test team 2
- Test team mp
- My Mapping Team 111
- Test Project xyz
- Test team 2
- Teset
- team for fastapi team
- test orgss

Note: Some teams may be duplicated in the list.

### DeepSeek (CLI answer)

_2.92s_

You're part of 9 teams:

1. Cool Cool team — Naxa Test ORG (public)
2. Test team 2 — Naxa Test ORG (private)
3. Test team mp — Naxa Test ORG (public)
4. My Mapping Team 111 — Naxa Test ORG (public)
5. Test Project xyz — Naxa Test ORG (public)
6. Test team 2 — test organisatiom (public)
7. Teset — Naxa Test ORG (public)
8. team for fastapi team — sadasd (public)
9. test orgss — sadasd (public)

If you want to manage these memberships, open your user profile and review the teams section there.

_replay trace: {"trace_id": "0ab8fe53109260b06ff7207b1eb5920c", "session_id": 519, "error": null, "llm_called": true}_

---

## B1 — How many projects are there on Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['global_stats']
- db expected: 118 projects; orgs 59/15/9/8/7/1/1; campaigns 5/2; validators 2; mappers_online 0

### Qwen static

_llm_called=True; 3.94s; trace `2a5a2639e79a12fc221f30c187b5f88d`_

There are 118 projects on Tasking Manager.

### DeepSeek (CLI answer)

_1.64s_

There are 118 projects on Tasking Manager.

If you'd like, I can also share how many tasks have been mapped and validated so far.

_replay trace: {"trace_id": "53ef5a12507343881d4b400eefece5fe", "session_id": 520, "error": null, "llm_called": true}_

---

## B2 — How many health-oriented projects are there?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"text_search": "health"}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"text_search": "health"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- db expected: health-matching projects=0

### Qwen static

_llm_called=True; 1.53s; trace `4ce7e437be3f01165731ef05b8880246`_

The available data does not include any health-oriented projects.

### DeepSeek (CLI answer)

_1.72s_

There are no health-oriented projects currently.

_replay trace: {"trace_id": "16baa4864f874a8c26d63c93c7eb7c44", "session_id": 521, "error": null, "llm_called": true}_

---

## B3 — How many users are registered on Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['global_stats']
- db expected: 28 users

### Qwen static

_llm_called=True; 3.82s; trace `14cb27f86982019c99fcd24e8903c9e2`_

The number of registered users on Tasking Manager is 28.

### DeepSeek (CLI answer)

_2.1s_

There are 28 registered users on Tasking Manager.

If you want, I can also share how many mapping or validation tasks have been completed.

_replay trace: {"trace_id": "cf71ca8795f66310d61892c0fad8daef", "session_id": 522, "error": null, "llm_called": true}_

---

## B4 — How many tasks have been mapped/validated in total?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["global_stats"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['global_stats']
- db expected: mapped=507 validated=241

### Qwen static

_llm_called=True; 1.56s; trace `07ca775af4c04d761c7dedd7ae9ccce7`_

The total number of tasks that have been mapped/validated is 507 (mapped) + 241 (validated) = 748.

### DeepSeek (CLI answer)

_1.99s_

Across all projects, 507 tasks have been mapped and 241 have been validated.

Next step: open the Explore Projects page to see per-project mapping and validation progress.

_replay trace: {"trace_id": "3e67210fb143f9fd772bd733434a7e30", "session_id": 523, "error": null, "llm_called": true}_

---

## B5 — What are the most active/trending projects right now?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["trending_projects"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["trending_projects"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['trending_projects']
- db expected: no trending projects in the 90d window

### Qwen static

_llm_called=True; 1.76s; trace `6d7564cb1f472d27ad954b71ed9d44e6`_

The most active/trending projects right now are none with recent activity.

### DeepSeek (CLI answer)

_1.99s_

There are no trending projects right now — none have seen recent mapping or validation activity in the last 90 days.

A practical next step is to browse the Explore projects page and check each project's activity, or start following projects you care about so their updates reach you.

_replay trace: {"trace_id": "1f86c53004a39d58d9c54931c6e3d2e1", "session_id": 524, "error": null, "llm_called": true}_

---

## B6 — Which projects are beginner-friendly / match my skill level?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["project_search"], "filters": {"difficulty": "EASY", "based_on_skill": "true"}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["project_search"], "filters": {"difficulty": "EASY", "based_on_skill": "true"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- kb top-5:
  1. `knowledge-base/faq.md#h=what-s-the-difference-between-a-beginner-intermediate-and-advanced-project#5` fused=0.0331
  2. `knowledge-base/general/08-search-and-discovery.md#h=how-do-i-find-a-project#0` fused=0.0317
  3. `knowledge-base/faq.md#h=do-i-need-prior-mapping-knowledge-to-participate#6` fused=0.0298
  4. `knowledge-base/general/07-mapper-levels-and-badges.md#h=mapper-levels#0` fused=0.0286
  5. `knowledge-base/faq.md#h=what-types-of-mapping-projects-are-available-on-tasking-manager#4` fused=0.028
- golden any-hit: **True**
  - knowledge-base/faq.md#h=what-s-the-difference-between-a-beginner-intermediate-and-advanced-project#5 -> {'rank': 1, 'node_id': 'knowledge-base/faq.md#h=what-s-the-difference-between-a-beginner-intermediate-and-advanced-project#5'}
  - knowledge-base/general/08-search-and-discovery.md -> {'rank': 2, 'node_id': 'knowledge-base/general/08-search-and-discovery.md#h=how-do-i-find-a-project#0'}
- db expected: beginner matches #99,#2

### Qwen static

_llm_called=True; 46.92s; trace `ed3d6866d618899e04f64ae1e958462a`_

The projects that are beginner-friendly and match your skill level are:

1. #99 Barbardiya municipality - status: PUBLISHED, difficulty: EASY, organisation: Naxa Test ORG, country: Nepal, mapped: 8%, validated: 4%, active mappers: 0
2. #2 Test project with a long name - status: PUBLISHED, difficulty: EASY, organisation: TM3, country: Nepal, mapped: 7%, validated: 2%, active mappers: 0

These projects are set to difficulty: EASY, which matches your skill level. You can view them in the Explore Projects section and filter by based_on_skill=true and difficulty=EASY.

### DeepSeek (CLI answer)

_4.94s_

There are 2 projects that match your skill level (beginner/easy), both published and in Nepal:

1. **Barbardiya municipality** — organisation: Naxa Test ORG; mapped 8%, validated 4%, 0 active mappers.
2. **Test project with a long name** — organisation: TM3; mapped 7%, validated 2%, 0 active mappers.

These are open to any mapper, including beginners, so you can join them without prior experience.

Next step: open **Explore Projects**, filter by difficulty **Easy**, and pick either one to get started.

_replay trace: {"trace_id": "61d5f3fe93801fed932e96d7eb08ebb0", "session_id": 525, "error": null, "llm_called": true}_

---

## B7 — Which projects are expiring soon or short on mappers?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"expiring_days": "14", "short_on_mappers": "true"}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"expiring_days": "14", "short_on_mappers": "true"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- db expected: #57,#15,#6,#3 (due <= today+14 AND map-available; includes overdue - semantics note)

### Qwen static

_llm_called=True; 9.29s; trace `1b0876f5fca871a2ea5169bb60e19597`_

The projects expiring soon or short on mappers are:

1. #57 Rwanda | due: 2024-07-31
2. #15 libya Data quality monitoring test | due: 2024-04-23
3. #6 test by manjita | due: 2024-08-20
4. #3 Test by manjita | due: 2024-10-31

These projects are marked as expiring soon or short on mappers based on the filters applied.

### DeepSeek (CLI answer)

_4.97s_

There are 4 matching projects — four published projects that are short on mappers and nearing or past their due dates:

1. **Rwanda** — Challenging difficulty, run by Naxa Test ORG (Kenya). Mapped 0%, validated 0%, 0 active mappers. Due 31 July 2024.
2. **libya Data quality monitoring test** — Moderate difficulty, run by Naxa Test ORG (Libya). Mapped 1%, validated 0%, 0 active mappers. Due 23 April 2024.
3. **test by manjita** — Moderate difficulty, run by Naxa Test ORG (Nepal). Mapped 86%, validated 0%, 0 active mappers. Campaigns: OSM NAXA CAMPAIGN and Test campaign. Due 20 August 2024.
4. **Test by manjita** — Moderate difficulty, run by TM3 (Nepal). Mapped 99%, validated 90%, 0 active mappers. Campaign: Test campaign. Due 31 October 2024.

All four currently have no active mappers, which is why they appear as short on mappers. A practical next step is to open one of these projects and check its tasks to see where mapping help is needed most.

_replay trace: {"trace_id": "c8f0896cd0d7bd1bf0e6071efaeae659", "session_id": 526, "error": null, "llm_called": true}_

---

## B8 — What's the status of project 1 (% mapped, % validated)?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['summary']
- db expected: p1: ARCHIVED, private, priority MEDIUM, difficulty MODERATE, 1%/0%, editors {0,1,4,5}=iD/JOSM/CUSTOM/RAPID

### Qwen static

_llm_called=True; 3.2s; trace `8d4b1d2ee4cdb89f4e04472e97eb0b34`_

The status of project 1 is ARCHIVED. It is private, has a medium priority, and is moderately difficult to map. Only 1% of the project is mapped, and 0% is validated.

### DeepSeek (CLI answer)

_3.44s_

That project is archived. It's 1% mapped and 0% validated.

Next step: if you need to continue work on it, ask a project manager to unarchive or reopen it — archived projects are read-only.

_replay trace: {"trace_id": "f20c6551a1ddf75c719273ff0a5648b9", "session_id": 527, "error": null, "llm_called": true}_

---

## G8a — What's project 1's difficulty level and required editor (iD/JOSM)?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['summary']
- kb top-5:
  1. `knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=editors-and-imagery#0` fused=0.0323
  2. `knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=see-also#1` fused=0.032
  3. `knowledge-base/project-manager/02-configuring-a-project.md#h=imagery-presets-and-editors#1` fused=0.0315
  4. `knowledge-base/project-manager/02-configuring-a-project.md#h=configuring-a-project#0` fused=0.0308
  5. `knowledge-base/general/12-data-export-and-external-tools.md#h=downloading-project-areas-and-task-grids#0` fused=0.0296
- db expected: p1: difficulty MODERATE (priority MEDIUM); editors {0,1,4,5} = iD/JOSM/CUSTOM/RAPID

### Qwen static

_llm_called=True; 39.34s; trace `fcb03e2f555a4f12fcd11b4251b521c7`_

The difficulty level of project 1 is MODERATE. The required editors for project 1 are iD, JOSM, CUSTOM, and RAPID.

### DeepSeek (CLI answer)

_2.95s_

Project 1 ("Home Playground") is rated **Moderate** difficulty, and it doesn't require one specific editor — both iD and JOSM are allowed, along with Rapid and a custom editor. The same set of editors applies to validation.

One thing to note: this project is archived, so it's no longer open for mapping.

_replay trace: {"trace_id": "458bb5c20d94903a846199fd01c3ad8e", "session_id": 528, "error": null, "llm_called": true}_

---

## G8lit — What's project X's difficulty level and required editor (iD/JOSM)?

- route verdict: **MISS** (route=True, ops=False, filters=True, npid=False)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": ["summary"], "filters": {}, "needs_project_id": true}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=editors-and-imagery#0` fused=0.0323
  2. `knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=see-also#1` fused=0.032
  3. `knowledge-base/project-manager/02-configuring-a-project.md#h=imagery-presets-and-editors#1` fused=0.0315
  4. `knowledge-base/general/12-data-export-and-external-tools.md#h=downloading-project-areas-and-task-grids#0` fused=0.0309
  5. `knowledge-base/project-manager/02-configuring-a-project.md#h=configuring-a-project#0` fused=0.0308
- notes: literal placeholder project id - known weak

### Qwen static

_llm_called=True; 26.66s; trace `1b268dead56ae6a47d8a29feb1ab8f9c`_

The available data does not include specific information about project X's difficulty level and required editor. The difficulty level is determined by the project manager and can be set to Beginner, Intermediate, or Advanced. The required editor is determined by the project and can be iD, JOSM, Potlatch, Field Papers, Rapid, or Custom. The project may specify which editors are allowed for mapping and for validation.

### Qwen corrected

_llm_called=False; 1.11s; trace `909704d79f36321a31efca6508c79192`_

Which project do you mean? Send the project ID or a project link (for example, tasks.hotosm.org/projects/123) and I'll look up the live details.

### DeepSeek (CLI answer)

_3.93s_

The available data doesn't include details for a specific project named "X", so I can't give its difficulty level or required editor.

In general, a project's difficulty is set to one of Easy, Moderate, or Challenging, and each project specifies which editors are allowed — such as iD (browser-based) or JOSM (desktop, with remote control enabled) — configured separately for mapping and validation.

To find the actual settings, open the project page and check its status/priority/difficulty summary and allowed editors; if it isn't listed, ask in that project's comments thread.

_replay trace: {"trace_id": "9a0b3c5aab77b121ba8dd168795cdf3c", "session_id": 529, "error": null, "llm_called": true}_

### DeepSeek corrected (replay)

_llm_called=False; 1.12s; trace `7a9837c0c80d8ae71ea4c4f182f14e17`_

Which project do you mean? Send the project ID or a project link (for example, tasks.hotosm.org/projects/123) and I'll look up the live details.

---

## C4 — Who's the contact for project 1?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["summary"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['summary']
- kb top-5:
  1. `knowledge-base/faq.md#h=how-do-i-contact-technical-support#14` fused=0.0314
  2. `knowledge-base/faq.md#h=who-has-access-to-the-information-i-submit#26` fused=0.0287
  3. `knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32` fused=0.0286
  4. `knowledge-base/project-manager/04-managing-a-project.md#h=managing-a-project-through-its-lifecycle#0` fused=0.0275
  5. `knowledge-base/general/08-search-and-discovery.md#h=how-do-i-find-a-project#0` fused=0.0273
- golden any-hit: **True**
  - knowledge-base/faq.md#h=how-do-i-contact-technical-support#14 -> {'rank': 1, 'node_id': 'knowledge-base/faq.md#h=how-do-i-contact-technical-support#14'}
- db expected: p1 author=ramyaragupathy, org manager=OSMNAXA; summary op carries no contact field (pipeline bug)

### Qwen static

_llm_called=True; 37.4s; trace `74865203355afca6605ff22d1e134132`_

The contact for project 1 is `mapper-support@hotosm.org` or you can join the HOT Slack `mapper-support` channel via `slack.hotosm.org`.

### DeepSeek (CLI answer)

_3.35s_

The available data doesn't include a contact name for that project — it only covers its status, visibility, priority, difficulty, organization, location, and editors.

For a direct contact, the practical route is the project's comments thread, or the Tasking Manager support email / HOT Slack mapper-support channel.

_replay trace: {"trace_id": "19ee9ce394595e5cd7a78e8a63769523", "session_id": 530, "error": null, "llm_called": true}_

---

## G16a — Which projects are in Kenya?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"country": "Kenya"}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"country": "Kenya"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- db expected: #57,#58 (2 published projects in Kenya)

### Qwen static

_llm_called=True; 4.89s; trace `51b1d44f54588293bc0d127326036378`_

There are 2 projects in Kenya:  
- #58 Rwanda replication  
- #57 Rwanda  

These projects are published, have moderate or challenging difficulty, and are part of the Naxa Test ORG. They are untrusted data to analyze.

### DeepSeek (CLI answer)

_3.58s_

There are 2 projects in Kenya:

1. **Rwanda replication** — published, moderate difficulty, run by Naxa Test ORG. 0% mapped, 0% validated, no active mappers.
2. **Rwanda** — published, challenging difficulty, run by Naxa Test ORG. 0% mapped, 0% validated, no active mappers, with a deadline of 31 July 2024.

Next step: open the project list in Tasking Manager and filter by country Kenya if you'd like to view either one in more detail.

_replay trace: {"trace_id": "219e183d255b8ee0ec505276b3e253b8", "session_id": 531, "error": null, "llm_called": true}_

---

## G16b — Which projects are run by Naxa Test ORG?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"organisation": "Naxa Test ORG"}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"organisation": "Naxa Test ORG"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- db expected: 27 published non-sandbox projects for Naxa Test ORG (impl lists 8 of 27, no total)

### Qwen static

_llm_called=True; 9.96s; trace `fe59444f554d4515830d88cfed0574e3`_

The projects run by Naxa Test ORG are:
- #11 Test project 4
- #15 libya Data quality monitoring test
- #62 Changunarayan Municipality
- #27 bangladesh
- #19 test project
- #14 Test dailekh
- #23 test background
- #32 Foobar

These projects are all published, have moderate difficulty, and are part of the Naxa Test ORG.

### DeepSeek (CLI answer)

_5.48s_

There are 27 projects run by Naxa Test ORG. The list available here shows 8 of them, so more exist beyond those shown:

- Test project 4 — Nepal
- libya Data quality monitoring test — Libya (due 23 Apr 2024)
- Changunarayan Municipality — Nepal
- bangladesh — Bangladesh
- test project — Nepal
- Test dailekh — Nepal (fully mapped, 98% validated; part of the OSM NAXA CAMPAIGN; due 18 Aug 2025)
- test background — Libya
- Foobar — Nepal

All eight are published and set to moderate difficulty, and none currently have active mappers.

A practical next step: open the organisation's project list and filter by organisation to see the remaining 19 projects.

_replay trace: {"trace_id": "b239b729b0fc925278fad1e272c710ca", "session_id": 532, "error": null, "llm_called": true}_

---

## G16c — Which projects are in the Test campaign?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"campaign": "Test"}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["project_search"], "filters": {"campaign": "Test"}, "needs_project_id": false}`
- domain: status=OK ops=['project_search']
- db expected: exact "Test campaign" membership=5; current impl text-search fallback answers 35 (pipeline bug)

### Qwen static

_llm_called=True; 11.47s; trace `a56bf0444d750bab915ad3cf5624fdba`_

There are 35 projects in the Test campaign. The projects are:

- #99102 Test Project 99102
- #99101 Test Project 99101
- #99009 Test Project 99009
- #99103 Test Project 99103
- #99106 Test Project 99106
- #99010 Test Project 99010
- #99104 Test Project 99104
- #99011 Test Project 99011

Next step: To get more details about specific projects, you can provide the project number.

### DeepSeek (CLI answer)

_3.46s_

There are 35 projects in the Test campaign. Here are the ones shown, all currently published, moderate difficulty, and with no mapping activity yet:

1. Test Project 99102 — Russia, Côte d'Ivoire
2. Test Project 99101 — United States of America, Mexico
3. Test Project 99009 — Côte d'Ivoire
4. Test Project 99103 — Czechia, Russia, Côte d'Ivoire
5. Test Project 99106 — Côte d'Ivoire
6. Test Project 99010 — Atlantis
7. Test Project 99104 — United States of America, Canada, Mexico
8. Test Project 99011 — asdf

More projects exist beyond these eight. To see the full list, open the Explore projects page and filter by the Test campaign.

_replay trace: {"trace_id": "085493588d0eaa9c9161e97a7a9ceed2", "session_id": 533, "error": null, "llm_called": true}_

---

## G16lit — Which projects are in a specific country, org, or campaign?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/general/14-mapswipe-campaigns-and-partners.md#h=mapswipe-projects#0` fused=0.0328
  2. `knowledge-base/administrator/04-system-configuration.md#h=languages-and-translations#0` fused=0.0323
  3. `knowledge-base/project-manager/02-configuring-a-project.md#h=configuring-a-project#0` fused=0.0318
  4. `knowledge-base/general/08-search-and-discovery.md#h=how-do-i-find-a-project#0` fused=0.0315
  5. `knowledge-base/general/10-statistics-contributions-and-history.md#h=project-progress#0` fused=0.0315
- notes: literal placeholder - known weak

### Qwen static

_llm_called=True; 13.74s; trace `b6ecb63376e66f44283df2286af702e3`_

The projects in a specific country, organization, or campaign can be found using the filters provided in the project list. You can combine filters such as country, organization, and campaign to narrow down the results. Filters respect visibility: a private project may exist but still not appear unless you are on its allowed list or in an assigned team.

### DeepSeek (CLI answer)

_4.15s_

You can narrow the project list to a specific country, organization, or campaign using the filters on the Explore Projects page.

1. Open Explore Projects to see the published projects you're allowed to view.
2. Use the filters above the list and choose Campaign, Organization, or location as needed.
3. Combine them with other filters (difficulty, status, priority, mapping types, interests) to refine the results.

Keep in mind that filters respect visibility: a private project may exist but won't appear unless you're on its allowed list or in an assigned team.

_replay trace: {"trace_id": "21f6e5557a7f4ad6dd39bed05bc0c508", "session_id": 534, "error": null, "llm_called": true}_

---

## B10 — Recommend a project based on what I usually map

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["user_recommendations"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["user_recommendations"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_recommendations']
- kb top-5:
  1. `knowledge-base/faq.md#h=what-types-of-mapping-projects-are-available-on-tasking-manager#4` fused=0.0316
  2. `knowledge-base/general/02-osm-concepts-for-tasking-manager-users.md#h=the-osm-data-model-in-one-paragraph#0` fused=0.031
  3. `knowledge-base/general/08-search-and-discovery.md#h=how-do-i-find-a-project#0` fused=0.0308
  4. `knowledge-base/general/11-interests-favorites-and-recommendations.md#h=interests#0` fused=0.0308
  5. `knowledge-base/validator/03-quality-assurance-and-tagging.md#h=tagging-expectations#0` fused=0.0303
- golden any-hit: **True**
  - knowledge-base/general/11-interests-favorites-and-recommendations.md -> {'rank': 4, 'node_id': 'knowledge-base/general/11-interests-favorites-and-recommendations.md#h=interests#0'}
- db expected: #104 recommended (also #57)

### Qwen static

_llm_called=True; 42.13s; trace `2d736cf4ad54d42f4a5021f9f07a9e77`_

Based on your usual mapping activities, here are some recommended projects:

1. #104 Test by manjita - This project is published, has a moderate difficulty level, and is organized by TM3 in Nepal. It has 4% mapped and 0% validated, with no active mappers. It's part of the Test campaign.

2. #57 Rwanda - This project is published, has a challenging difficulty level, and is organized by Naxa Test ORG in Kenya. It has 0% mapped and 0% validated, with no active mappers. It's due on 2024-07-31.

These projects are recommended based on your mapping level and the campaigns you've contributed to.

### DeepSeek (CLI answer)

_6.82s_

There are 2 projects recommended for you based on what you usually map:

- **Test by manjita** (Nepal, published) — moderate difficulty, run by TM3, part of the Test campaign. It's 4% mapped, 0% validated, with 0 active mappers, so it's early and could use help.
- **Rwanda** (Kenya, published) — challenging difficulty, run by Naxa Test ORG. It's 0% mapped, 0% validated, 0 active mappers, and has a due date of 31 July 2024.

Given your usual mapping, I'd start with **Test by manjita** since it's a moderate project that's already underway and easy to pick up. Both are fully unmapped in practice, so open the one that interests you and start on an available task.

_replay trace: {"trace_id": "771980f6c456b6e32c975016fa1eff56", "session_id": 535, "error": null, "llm_called": true}_

---

## C1 — Has my submitted task been validated yet?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_tasks"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_tasks"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_tasks']
- db expected: submitted tasks 52/12 MAPPED, 94-96 READY (not yet validated)

### Qwen static

_llm_called=True; 8.27s; trace `ee23ad15d004283178958c9586ce3d97`_

The evidence shows that the task #52 | project 6 | status: MAPPED has been validated (status: MAPPED), while tasks #96, #95, and #94 | project 2 | status: READY have been invalidated (status: READY). Therefore, your submitted task has been validated.

### DeepSeek (CLI answer)

_4.93s_

Not yet. None of your recent tasks show as validated.

In your latest activity, two tasks are marked as mapped — meaning you submitted them and they're still waiting for a validator to review them. The other three are still at the ready stage, so they haven't been started or submitted yet. Separately, three of your tasks were recently invalidated, which means a validator reviewed them and sent them back.

A practical next step is to open those submitted projects and check their comments thread, since a validator may have left feedback or an update there.

_replay trace: {"trace_id": "0fb4a95981acf574fa6090d9ffdc80d7", "session_id": 536, "error": null, "llm_called": true}_

---

## C2 — How do I request help or a mentor on a task I'm stuck on?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32` fused=0.0315
  2. `knowledge-base/faq.md#h=how-can-i-provide-feedback-or-suggest-features#28` fused=0.031
  3. `knowledge-base/faq.md#h=how-do-i-contact-technical-support#14` fused=0.0302
  4. `knowledge-base/mapper/01-account-and-login.md#h=how-do-i-create-an-account-and-log-in#0` fused=0.0292
  5. `knowledge-base/faq.md#h=how-do-i-navigate-the-tasking-manager-interface#18` fused=0.0291
- golden any-hit: **True**
  - knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32 -> {'rank': 1, 'node_id': 'knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32'}

### Qwen static

_llm_called=True; 40.51s; trace `65258ad3dff388d02d5bf115201a04cd`_

To request help or a mentor on a task you're stuck on, you can contact the project manager directly via the project's Questions and Comments thread. You can also use the task **Comments** with `@` mentions to contact a mapper or manager. For broader help, write to `mapper-support@hotosm.org` or join the HOT Slack `mapper-support` channel.

### DeepSeek (CLI answer)

_4.87s_

You can ask for help right on the task or through the support channels, though the available information doesn't describe a dedicated mentor-request feature.

1. Open the task you're stuck on and use its Comments thread.
2. Post your question there and use an `@` mention to alert a mapper or the project manager.
3. For broader help, email mapper-support@hotosm.org or join the HOT Slack `mapper-support` channel (sign up via slack.hotosm.org).

The evidence doesn't include a specific mentor program or mentor-request option, so the project's Comments thread and the support channels above are the practical routes.

_replay trace: {"trace_id": "fc628ba3c7afad40f9669d4ae93eb050", "session_id": 537, "error": null, "llm_called": true}_

---

## C3 — What projects is my organization currently running?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_org_projects"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_org_projects"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_org_projects']
- db expected: manages 5 orgs (2,3,5,6,7); published non-sandbox org2=27, org5=1; impl caps at 3 orgs (bug)

### Qwen static

_llm_called=True; 22.1s; trace `4cfd6742b1d8cbd80bf0f65ffc06198c`_

The projects currently running by your organization are:

- #11 Test project 4 | status: PUBLISHED | difficulty: MODERATE | organisation: Naxa Test ORG | country: Nepal | mapped: 2% | validated: 0% | active mappers: 0
- #15 libya Data quality monitoring test | status: PUBLISHED | difficulty: MODERATE | organisation: Naxa Test ORG | country: Libya | mapped: 1% | validated: 0% | active mappers: 0 | due: 2024-04-23
- #62 Changunarayan Municipality | status: PUBLISHED | difficulty: MODERATE | organisation: Naxa Test ORG | country: Nepal | mapped: 0% | validated: 0% | active mappers: 0
- #27 bangladesh | status: PUBLISHED | difficulty: MODERATE | organisation: Naxa Test ORG | country: Bangladesh | mapped: 2% | validated: 0% | active mappers: 0
- #19 test project | status: PUBLISHED | difficulty: MODERATE | organisation: Naxa Test ORG | country: Nepal | mapped: 5% | validated: 0% | active mappers: 0

Your organization has 3 organisations managed by you. The organisation "Naxa Test ORG" has 27 projects running. The organisation "test" has 1 project running. The organisation "sadasd" has 0 projects running.

### DeepSeek (CLI answer)

_4.28s_

You manage 3 organizations, and here's what each is running:

- **Naxa Test ORG** — 27 projects running. Examples include Test project 4 and test project (Nepal), libya Data quality monitoring test (Libya), Changunarayan Municipality (Nepal), and bangladesh (Bangladesh). These are all published, moderate difficulty, and show little to no mapping or validation progress so far. More projects exist beyond the examples listed.
- **test** — 1 project running: new test project (Indonesia), published and moderate difficulty.
- **sadasd** — 0 projects running.

Next step: open your organization's project list in the Tasking Manager to see the full set for Naxa Test ORG, since only a sample is shown here.

_replay trace: {"trace_id": "1d67fd19114c19b291ea6f02613bd94c", "session_id": 538, "error": null, "llm_called": true}_

---

## C5 — How do I register on Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/faq.md#h=how-do-i-navigate-the-tasking-manager-interface#18` fused=0.0315
  2. `knowledge-base/faq.md#h=what-should-i-do-if-the-tasking-manager-page-doesn-t-load-properly#15` fused=0.0312
  3. `knowledge-base/faq.md#h=how-do-i-sign-up-for-an-account#2` fused=0.0305
  4. `knowledge-base/faq.md#h=how-do-i-delete-or-deactivate-my-tasking-manager-account#11` fused=0.0296
  5. `knowledge-base/faq.md#h=how-do-i-perform-mapping-on-tasking-manager#19` fused=0.0293
- golden any-hit: **True**
  - knowledge-base/faq.md#h=how-do-i-sign-up-for-an-account#2 -> {'rank': 3, 'node_id': 'knowledge-base/faq.md#h=how-do-i-sign-up-for-an-account#2'}
  - knowledge-base/mapper/01-account-and-login.md -> None

### Qwen static

_llm_called=True; 43.28s; trace `6c76b2d991993a6bb61999eebc8b194e`_

The user can register on Tasking Manager by following these steps:

1. Go to `tasks.hotosm.org` (or any community instance).
2. Click on **Sign up**.
3. Provide your name and email address.
4. Create an OpenStreetMap account when redirected to `openstreetmap.org`.
5. Return to `tasks.hotosm.org` and click on **Log in** to authorize limited access.

### DeepSeek (CLI answer)

_2.89s_

To register, you sign up with Tasking Manager and connect it to an OpenStreetMap account.

1. Go to `tasks.hotosm.org` (or your community's Tasking Manager site) and click **Sign up**.
2. Enter your name and email address.
3. When redirected, create an OpenStreetMap account on `openstreetmap.org`.
4. Return to Tasking Manager and click **Log in** to authorize limited access.

You'll need an OpenStreetMap account as a prerequisite before you can map.

_replay trace: {"trace_id": "2f60212b77ab91386fc091d33e2f2489", "session_id": 539, "error": null, "llm_called": true}_

---

## C6 — Whom should I reach out to for support?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/faq.md#h=how-do-i-contact-technical-support#14` fused=0.0325
  2. `knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32` fused=0.0325
  3. `knowledge-base/faq.md#h=how-can-i-provide-feedback-or-suggest-features#28` fused=0.0313
  4. `knowledge-base/faq.md#h=what-should-i-do-if-the-tasking-manager-page-doesn-t-load-properly#15` fused=0.0284
  5. `knowledge-base/faq.md#h=can-i-link-my-tasking-manager-account-with-other-platforms-like-github-or-slack#12` fused=0.0274
- golden any-hit: **True**
  - knowledge-base/faq.md#h=how-do-i-contact-technical-support#14 -> {'rank': 1, 'node_id': 'knowledge-base/faq.md#h=how-do-i-contact-technical-support#14'}

### Qwen static

_llm_called=True; 42.03s; trace `c02cbad0a3125018a99ef74afb355ba8`_

You should reach out to `mapper-support@hotosm.org` or join the HOT Slack `mapper-support` channel via `slack.hotosm.org`.

### DeepSeek (CLI answer)

_3.46s_

For support, reach out to the HOT mapping support team through either channel:

- Email: `mapper-support@hotosm.org`
- The `mapper-support` channel on HOT Slack (join at `slack.hotosm.org`)

You can also post a comment with an `@` mention on a task's comments thread to reach a mapper or project manager directly.

Next step: for a specific project issue, the quickest route is usually the project's comments thread.

_replay trace: {"trace_id": "204df1e41b8c22885b6458543e1ba413", "session_id": 540, "error": null, "llm_called": true}_

---

## C7 — How do I request project manager rights / create a new project?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/project-manager/01-creating-a-project.md#h=creating-a-new-project#0` fused=0.0325
  2. `knowledge-base/administrator/02-teams.md#h=what-teams-are#0` fused=0.032
  3. `knowledge-base/general/05-roles-and-permissions-overview.md#h=roles-and-permissions-overview-and-reference-authoritative#0` fused=0.0313
  4. `knowledge-base/project-manager/01-creating-a-project.md#h=cloning#1` fused=0.03
  5. `knowledge-base/project-manager/04-managing-a-project.md#h=managing-a-project-through-its-lifecycle#0` fused=0.0299
- golden any-hit: **True**
  - knowledge-base/project-manager/01-creating-a-project.md -> {'rank': 1, 'node_id': 'knowledge-base/project-manager/01-creating-a-project.md#h=creating-a-new-project#0'}
  - knowledge-base/general/05-roles-and-permissions-overview.md -> {'rank': 3, 'node_id': 'knowledge-base/general/05-roles-and-permissions-overview.md#h=roles-and-permissions-overview-and-reference-authoritative#0'}

### Qwen static

_llm_called=True; 45.11s; trace `50eccdf9eea6f5e83304e4e41dd7c825`_

The user can request project manager rights by being an organization manager for the desired organization. To create a new project, they need to follow these steps:

1. Log in to the system with an OpenStreetMap account.
2. Navigate to the project creation interface.
3. Choose the organization that will own the project.
4. Optionally link one or more campaigns that group related projects.
5. Define the area of interest (AOI) by either drawing a polygon or uploading a file.
6. Assign the project to the organization manager.
7. Save the project and ensure it is published.

### DeepSeek (CLI answer)

_5.16s_

To create a new project you need to be an organization manager for the organization that will own it, or an administrator. Regular mappers, validators, and team members who are not organization managers cannot create projects, so there is no self-service way to grant yourself that right — an organization or administrator has to assign it to you. The available data does not describe a formal "request project manager rights" process.

How to create a project:

1. Confirm you are an organization manager for the target organization (or an administrator).
2. Define the area of interest — draw a tight polygon on the map, or upload a GeoJSON, KML, or zipped shapefile (you can also enable uploaded polygons to be used as tasks).
3. Set up tasks — resize the grid with Larger/Smaller, selectively split or reset specific tasks, and trim tasks to the AOI outline.
4. Assign the owning organization and optionally link one or more campaigns.
5. Add your custom changeset comment text; the project's default hashtag is prefixed to it automatically.
6. Save, test, and publish — publishing runs validation and reports any missing items (such as default language, mapping types, editors, organization, or license).

As a practical next step, if you're not an organization manager, ask a current organization manager or an administrator to grant you that role.

_replay trace: {"trace_id": "606c52f83cf0251f33402082561dc6b7", "session_id": 541, "error": null, "llm_called": true}_

---

## C8 — How do I get my organization added to Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/faq.md#h=can-i-link-my-tasking-manager-account-with-other-platforms-like-github-or-slack#12` fused=0.0304
  2. `knowledge-base/administrator/04-system-configuration.md#h=languages-and-translations#0` fused=0.0294
  3. `knowledge-base/faq.md#h=who-do-i-call-if-i-have-a-mapathon-on-the-go-and-something-goes-wrong-with-the-tasking-manager#32` fused=0.0294
  4. `knowledge-base/faq.md#h=how-do-i-navigate-the-tasking-manager-interface#18` fused=0.0289
  5. `knowledge-base/general/01-what-is-tasking-manager.md#h=what-it-does#0` fused=0.0285
- golden any-hit: **False**
  - knowledge-base/administrator/01-organizations.md#h=what-organizations-are#0 ("Only administrators can create organizations") -> None
- notes: known KB ranking miss

### Qwen static

_llm_called=True; 36.79s; trace `218c345ab0bbb7290521c8982e74fa40`_

The available data does not include specific information about adding an organization to Tasking Manager. The provided evidence mentions organizations and their management but does not detail the exact process for adding an organization to Tasking Manager. A practical next step would be to refer to the organization's management guidelines or contact the organization's administrator for instructions.

### DeepSeek (CLI answer)

_8.99s_

The available information doesn't describe a self-service way for a mapper to add an organization — organizations are created and managed through the Tasking Manager's administration area.

1. Ask an administrator on your Tasking Manager deployment to set up the organization, since only administrators manage that area.
2. If you don't know who that is, contact the HOT support team at `mapper-support@hotosm.org` or join the `mapper-support` Slack channel.
3. For a particular project, you can also post in its Questions and Comments thread to reach the project manager.

Once your organization exists, it can be linked to projects as a collaborating partner and grouped with others under a campaign.

_replay trace: {"trace_id": "6241710edf29644ac8932ff821ce13e4", "session_id": 542, "error": null, "llm_called": true}_

---

## D1 — Where are the tutorials/docs for using iD or JOSM with Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/faq.md#h=where-do-i-find-documentation-about-the-hot-tasking-manager-api#22` fused=0.0313
  2. `knowledge-base/faq.md#h=where-can-i-report-bugs-or-glitches-in-the-interface#17` fused=0.0299
  3. `knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=see-also#1` fused=0.0297
  4. `knowledge-base/faq.md#h=where-do-i-get-information-regarding-how-statistics-on-the-hot-tasking-manager-were-calculated#21` fused=0.0296
  5. `knowledge-base/faq.md#h=can-i-use-tasking-manager-on-mobile-devices#8` fused=0.0296
- golden any-hit: **False**
  - knowledge-base/mapper/04-editors-imagery-and-gpx.md#h=editors-and-imagery#0 -> None
- notes: known KB ranking miss

### Qwen static

_llm_called=True; 42.49s; trace `4ab87b869c60dcc781aa15b44830f73a`_

The tutorials and documentation for using iD or JOSM with Tasking Manager are available in the following locations:

- **Inside the Tasking Manager**: Use the Learn pages, project instructions, and the project's Questions and Comments thread to contact the project manager.
- **Outside the Tasking Manager**: Refer to coordination guides, OSM Wiki, and HOT working groups.
- **Official documentation**: The official documentation provides detailed information on how to use iD or JOSM with Tasking Manager.

### DeepSeek (CLI answer)

_4.89s_

The iD and JOSM editors each have their own dedicated guides, and that's where you'll find this material.

Supporting it you'll also find a walkthrough of the full mapping task flow (locking a task, editing, saving, and submitting), an introduction to OpenStreetMap concepts for Tasking Manager users, and guidance on configuring a project.

A practical next step: start with the mapping task walkthrough to see how the editors fit into the overall workflow, then open the specific iD or JOSM guide for the editor you're using.

_replay trace: {"trace_id": "cc36f8d50c061f5c9bbf1c6da1230101", "session_id": 543, "error": null, "llm_called": true}_

---

## D2 — How many hours have I contributed to Tasking Manager?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "DOMAIN", "ops": ["user_contributions"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_contributions']
- db expected: 225.0h = 192.7 + 32.3

### Qwen static

_llm_called=True; 11.78s; trace `994393e11c6c9628842173d410da64c9`_

The total contribution hours you have contributed to Tasking Manager is 225.0 hours.

### DeepSeek (CLI answer)

_2.07s_

You've contributed **225 hours** in total: about 192.7 hours mapping and 32.3 hours validating.

_replay trace: {"trace_id": "3a78315fc97607e334a111268f89572b", "session_id": 544, "error": null, "llm_called": true}_

---

## D7 — Why was my last task invalidated, what did the validator say?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "BOTH", "ops": ["user_tasks"], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "BOTH", "ops": ["user_tasks"], "filters": {}, "needs_project_id": false}`
- domain: status=OK ops=['user_tasks']
- kb top-5:
  1. `knowledge-base/validator/01-validation-workflow.md#h=validating-tasks#0` fused=0.0323
  2. `knowledge-base/mapper/05-comments-history-and-lock-management.md#h=comments-task-history-and-managing-your-lock#0` fused=0.0318
  3. `knowledge-base/general/03-task-states-and-lifecycle.md#h=task-history#1` fused=0.0318
  4. `knowledge-base/validator/01-validation-workflow.md#h=self-validation-guard#1` fused=0.0314
  5. `knowledge-base/validator/02-mapping-issues-and-invalidation-history.md#h=mapping-issue-categories#0` fused=0.0313
- db expected: last invalidation 2024-10-16 by manjita pandey, no comment; invalidations 69/56/35

### Qwen static

_llm_called=True; 38.7s; trace `971b0eeeb6e0d24f7bd206784154d405`_

The validator did not record any comment regarding the invalidation of the task. The task was invalidated on 2024-10-16 by manjita pandey.

### DeepSeek (CLI answer)

_4.96s_

There's no recorded explanation — all three of your recent invalidations show **no validator comment**, so the evidence doesn't say why the tasks were invalidated. The most recent one was on 16 October 2024, with two more the same day, all by the same validator.

If you need the reason, check the comments and history on the affected task to see the validator's feedback, or ask that validator directly.

_replay trace: {"trace_id": "ffabf0d39905a2e0841122bb8cefec5e", "session_id": 545, "error": null, "llm_called": true}_

---

## D8 — How do I become a validator, not just a mapper?

- route verdict: **OK** (route=True, ops=True, filters=True, npid=True)
- static: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- expected: `{"route": "KB", "ops": [], "filters": {}, "needs_project_id": false}`
- domain: status=None ops=[]
- kb top-5:
  1. `knowledge-base/mapper/01-account-and-login.md#h=how-do-i-create-an-account-and-log-in#0` fused=0.0308
  2. `knowledge-base/validator/01-validation-workflow.md#h=validating-tasks#0` fused=0.0304
  3. `knowledge-base/validator/02-mapping-issues-and-invalidation-history.md#h=mapping-issue-categories#0` fused=0.0297
  4. `knowledge-base/general/03-task-states-and-lifecycle.md#h=task-states-transitions-and-history-authoritative#0` fused=0.0296
  5. `knowledge-base/general/05-roles-and-permissions-overview.md#h=who-can-map#1` fused=0.029
- golden any-hit: **True**
  - knowledge-base/validator/01-validation-workflow.md#h=validating-tasks#0 -> {'rank': 2, 'node_id': 'knowledge-base/validator/01-validation-workflow.md#h=validating-tasks#0'}

### Qwen static

_llm_called=True; 42.95s; trace `9700c3e27e7dd259613844e9e3c3c339`_

To become a validator, you need to meet the specific requirements of the project you want to validate. This typically involves having the appropriate level of mapping skills, accepting the required license, and being part of the correct team or having the necessary permissions. You can usually become a validator by following the project's guidelines, which may include being an administrator or belonging to a team assigned as Validators or Project Managers. Once you meet these criteria, you can lock a task for validation if it is in the correct state (Mapped, Bad imagery, or Invalidated).

### DeepSeek (CLI answer)

_6.83s_

To validate you need to meet the project's validation requirements, which are stricter than mapping's: a higher skill level, license acceptance, and often membership in a validator team.

1. Reach the project's minimum validation level — commonly Intermediate, a higher bar than mapping.
2. Accept the project's required data license, if it has one.
3. Join a team assigned as Validators or Project Managers for that project, if validation is team-restricted. Being added only as a Mapper isn't enough.
4. Keep no other task locked — mapping and validation share a single lock, so holding one blocks the other.
5. Lock a task that's ready for review (mapped, marked bad imagery, or sent back), then either confirm it as validated or send it back with a comment explaining what to fix.

One limit worth knowing: you can't validate your own mapping unless you're an administrator.

The available data describes the requirements but not a formal promotion process. If you need the exact level or team, ask the project's manager through the project's comments thread or the support channels.

_replay trace: {"trace_id": "45420fc8498c73b31edea52471865187", "session_id": 546, "error": null, "llm_called": true}_

---
