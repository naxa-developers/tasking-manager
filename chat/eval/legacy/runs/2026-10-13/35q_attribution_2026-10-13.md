# TMBot 35-question E2E attribution — Qwen3-1.7B vs DeepSeek v4.1 Flash

**Date:** 2026-10-13 · **User:** 10250456 (OSMNAXA) · **Stack:** tm-backend + llama.cpp Qwen3-1.7B-Q4_K_M (2 threads) + embeddinggemma-2, KB `kb_nodes_gemma2_q8` (83 nodes) · **Branch:** feature/langfuse-tracing @ cf333f655 · **Run stamp:** `2026-10-13-e2e`

---

## TL;DR (one page)

We ran all 35 cases through the real production turn path (`RagService.chat`, stream=False) with every turn traced to Langfuse: **Qwen static (35/35)**, **DeepSeek static (35/35, opencode CLI + in-container replay)**, and the **corrected-route arm** for the only routing miss (G8lit). Mean latency per turn: **Qwen 20.4s vs DeepSeek 3.9s**.

**Where the failures originate (first failing stage, scored set = 33 cases + 2 placeholders):**

| First failing stage | Qwen | DeepSeek |
|---|---|---|
| Generation (evidence correct, answer wrong/absent/incomplete) | **6** (A1~, A3✗, A4✗, B4~, C1✗, C7~) | **0** |
| Retrieval / KB ranking | **2** (C8✗, D1~) | 1 (D1~; C8 became a pass on model knowledge, ungrounded) |
| Pipeline / domain evidence | **4** (C3~, C4✗, G16b~, G16c✗) | **4** (same cases) |
| Routing | 1 (G8lit static; corrected arm fixes it) | 1 (same) |
| Pass | 21/35 | 28/35 |

**The money slide — 10 of Qwen's 13 non-passes improved or fixed under DeepSeek:** all **6 generation-staged problems fixed** (A3, A4, C1 fail→pass; A1, B4, C7 partial→pass), the **C8 retrieval failure answered correctly** (from model knowledge; golden chunk was *not* retrieved — flagged as ungrounded), C4 → partial (honest "no contact in data"), and G16b/C3 → partial **with truncation disclosed**.

**Residual failures on both models = the known pipeline/evidence bugs, not the model:** G16c (campaign filter silently falls back to text search: evidence says 35, exact membership is 5), C3 (org op caps 3 of 5, undisclosed), C4 (`summary` op carries no author/org manager), G16b (op lists 8 of 27), plus D1/C8 KB ranking.

**Bottom line:** the local 1.7B is the dominant generation failure source **and** DeepSeek fixes every generation-attributable failure with ~5× lower latency; upgrading generation alone will not fix G16c/C3/C4/G16b — those are product bugs to fix in the pipeline.

---

## Method

1. **Cases:** `chat/eval/cases_35.json` (35 cases; questions identical to the 2026-10-13 E2E run; corpus expectations mapped where ids differ — `G8a←B9, G8lit←G8, G16a←D4, G16c←D6, G16lit←G16`; G16b expectations set by hand: DOMAIN `project_search` `organisation="Naxa Test ORG"`).
2. **Arms:** Qwen static (all), DeepSeek static (all), corrected route (G8lit only — the single static routing miss). Corrected arm injects the golden `DomainRoute` via `chat.turn.plan.route_query` + `chat.retrieval.debug_report.route_query`.
3. **Turn path:** capture pass (`gather_turn(generate=False)` — exact prompt + KB/domain evidence) then `RagService.chat(session_id, user_id, question, stream=False, db)`. One `rag_sessions` row per case per arm (`e2e-<variant>-<gen>-<id>`).
4. **Tracing:** every arm goes through the production `start_turn_trace`; tags injected: `e2e-eval`, `gen:qwen|deepseek`, `variant:static|corrected`; metadata `case_id`, `eval_run=2026-10-13-e2e`, `transport`. Step-0 smoke gate passed before the batch (trace + tags verified via the Langfuse v2 observations API).
5. **DeepSeek transport:** `opencode run -m opencode-go/deepseek-v4.1-flash --format json "<system>\n\n<user>"` on the captured production prompt (host), then replayed in-container so Langfuse gets a production-shaped trace with the answer injected (`LLMService` replaced; routing/retrieval/domain real). Metadata `transport=opencode-cli` on every replayed trace.
6. **Retry policy:** retry-once after 10s on any turn failure; fired once (C3, `Loading model` 503 from tm-llm).
7. **Adjudication:** curated (this report), per model per case, first-failing-stage; KB soft check = golden chunk in top-5 (9/11 goldens hit; misses C8, D1).

## Verified in the run (controls)

- **Router:** 34/35 static decisions exact (route+ops+filters+needs_project_id vs corpus). Only G8lit misses (placeholder id → answered from KB instead of asking; corrected arm → clarification question).
- **Retrieval:** golden chunk in top-5 for 9/11 KB-golden cases; misses exactly C8 and D1 (as pre-registered).
- **DB evidence:** all DOMAIN ops returned `status=OK`; spot-checked values match the pre-run expectations (118 projects, 507/241 tasks, 28 users, 9 teams, 225.0h, locked_by=0, etc.).

## Money slide — what DeepSeek fixed (side-by-side)

**A4 — "How is my contribution this month compared to last month?"** (evidence contains `contributions_this_month: 0`, `contributions_last_month: 0`)
> **Qwen:** "The available data does not include specific information about your contribution this month compared to last month. A practical next step would be to check the *contributions_this_month* and *contributions_last_month* fields in the evidence." — **fail (generation)**

> **DeepSeek:** "You have no contributions this month or last month — both are zero." — **pass**

**C1 — "Has my submitted task been validated yet?"** (evidence: 2×MAPPED, 3×READY, 3 recent invalidations)
> **Qwen:** "…task #52 … has been validated (status: MAPPED), while tasks #96, #95, and #94 … have been invalidated (status: READY). Therefore, your submitted task has been validated." — **fail (generation; statuses misread)**

> **DeepSeek:** "Not yet. … two tasks are marked as mapped — meaning you submitted them and they're still waiting for a validator… three are still at the ready stage … three of your tasks were recently invalidated…" — **pass**

**C8 — "How do I get my organization added to Tasking Manager?"** (golden chunk *not* retrieved)
> **Qwen:** "The available data does not include specific information… refer to the organization's management guidelines…" — **fail (retrieval)**

> **DeepSeek:** "…organizations are created and managed through the Tasking Manager's administration area… only administrators manage that area… ask an administrator…" — **pass, but NOT grounded in retrieved chunks** (model knowledge compensating a retrieval miss — needs the ranking fix to be trustworthy)

**C4 — "Who's the contact for project 1?"** (summary op has no author/manager field)
> **Qwen:** "The contact for project 1 is `mapper-support@hotosm.org`…" — **fail (pipeline; presents generic support email as the project contact)**

> **DeepSeek:** "The available data doesn't include a contact name for that project…" — **partial (pipeline; honest about the gap)**

## Residual failures — product bugs, not the model (fix these)

| # | Case | What breaks | Evidence |
|---|---|---|---|
| 1 | **G16c** | Campaign filter `campaign="Test"` finds no exact campaign → **silent text-search fallback** → domain evidence says 35 / lists 8; correct exact membership is **5**. Both models faithfully repeat the wrong evidence. | `filters: campaign=Test` / `matching_projects_total: 35` in span output |
| 2 | **C3** | `user_org_projects` **caps at 3 of 5 managed orgs** and reports "organisations_managed_by_you: 3"; counts per org OK (Naxa 27, test 1, sadasd 0). | plan vs evidence |
| 3 | **C4** | `get_project_summary` **carries no author / org manager**; contact question unanswerable from evidence. | summary field list |
| 4 | **G16b** | `project_search` **lists 8 of 27** (total present); Qwen omits the total, DeepSeek discloses. Cap behavior should be explicit. | span output |
| 5 | **C8 / D1** | KB ranking: golden chunks absent from top-5 (C8: `administrator/01-organizations.md`; D1: `mapper/04-editors-imagery-and-gpx.md#editors-and-imagery`). | capture top-5 |

**Recommended fix order:** (1) campaign filter → resolve exact campaign or surface "no exact match" instead of silent fallback; (2) C3/G16b caps → return totals + truncation flags (and prompt models to disclose); (3) C4 → add author/manager to the summary op; (4) KB ranking (section-aware/keyword hybrid for C8/D1); (5) generation upgrade path — this run shows it converts every generation-attributable failure at ~5× lower latency; (6) router: adopt the DeepSeek router only if desired (static router already 34/35 here).

## Langfuse exhibits (filter tag `e2e-eval`)

1. **Generation-only failure** — A4 Qwen [ce23e97db731…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/ce23e97db7314e8fce3b77070b4376f7): same evidence block, answer claims data missing.
2. **The fix, traced** — A4 DeepSeek [48f40066bc2d…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/48f40066bc2d6e520936632fe4ceb17f): `gen:deepseek`, `transport=opencode-cli`.
3. **Retrieval miss** — C8 Qwen [218c345ab0bb…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/218c345ab0bbb7290521c8982e74fa40): golden chunk absent from `kb-retrieval` span output.
4. **Pipeline bug** — G16c Qwen [a56bf0444d75…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/a56bf0444d750bab915ad3cf5624fdba): `domain-routing` span shows `filters campaign=Test` but fallback evidence `total=35`.
5. **Pass control** — A5 Qwen [570605cdcea9…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/570605cdcea98c49d16819a83d968a13) / B8 DeepSeek [f20c6551a1dd…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/f20c6551a1ddf75c719273ff0a5648b9).
6. **Routing fix (corrected arm)** — G8lit Qwen corrected [909704d79f36…](https://cloud.langfuse.com/project/cmue9qyna032wad0dbvfty0ks/traces/909704d79f36321a31efca6508c79192): clarification instead of KB guess.

## Caveats

- **DeepSeek transport:** OpenCode CLI harness wraps the model (single concatenated system+user message; temperature not pinned); answers were then **injected** into the production path for the traced replay (`transport=opencode-cli` in trace metadata). Routing/retrieval/domain evidence in the replay are real.
- Single run per arm; Qwen is 1.7B Q4 on 2 threads (1 `Loading model` retry on C3 consumed).
- Scored set = 33 cases; G8lit (routing placeholder, scored via corrected arm) and G16lit (literal placeholder) are marked known-weak.
- Eval turns persisted to `rag_sessions`/`rag_messages` for user 10250456 (one session per case/arm — see raw JSONLs for ids).

---

## Appendix A — full per-case table

Legend: ✓ pass · ~ partial · ✗ fail · — n/a (placeholder). Stage shown for non-passes: gen=generation, retr=retrieval, pipe=domain pipeline, route=routing.

| case | question | route | kb | evidence | Qwen | DeepSeek | conversion |
|---|---|---|---|---|---|---|---|
| A1 | What's my mapper level, and what do I need to… | ok | hit | ok | ~ (gen) | ✓ | improved |
| A2 | What task do I currently have locked? | ok | - | ok | ✓ | ✓ | same |
| A3 | What badges have I earned? | ok | - | ok | ✗ (gen) | ✓ | fixed |
| A4 | How is my contribution this month compared to… | ok | - | ok | ✗ (gen) | ✓ | fixed |
| A5 | What are the projects I have contributed to? | ok | - | ok | ✓ | ✓ | same |
| A6 | What's my current mapping streak? | ok | - | ok | ✓ | ✓ | same |
| A7 | What's my validation-vs-mapping split? | ok | - | ok | ✓ | ✓ | same |
| A8 | What teams am I part of? | ok | - | ok | ✓ | ✓ | same |
| B1 | How many projects are there on Tasking Manager… | ok | - | ok | ✓ | ✓ | same |
| B2 | How many health-oriented projects are there? | ok | - | ok | ✓ | ✓ | same |
| B3 | How many users are registered on Tasking Manag… | ok | - | ok | ✓ | ✓ | same |
| B4 | How many tasks have been mapped/validated in t… | ok | - | ok | ~ (gen) | ✓ | improved |
| B5 | What are the most active/trending projects rig… | ok | - | ok | ✓ | ✓ | same |
| B6 | Which projects are beginner-friendly / match m… | ok | hit | ok | ✓ | ✓ | same |
| B7 | Which projects are expiring soon or short on m… | ok | - | ok | ✓ | ✓ | same |
| B8 | What's the status of project 1 (% mapped, % va… | ok | - | ok | ✓ | ✓ | same |
| G8a | What's project 1's difficulty level and requir… | ok | hit | ok | ✓ | ✓ | same |
| G8lit | What's project X's difficulty level and requir… | miss | - | - | ✗ (route) | ✗ (route) | same |
| C4 | Who's the contact for project 1? | ok | hit | missing_field | ✗ (pipe) | ~ (pipe) | improved |
| G16a | Which projects are in Kenya? | ok | - | ok | ✓ | ✓ | same |
| G16b | Which projects are run by Naxa Test ORG? | ok | - | capped | ~ (pipe) | ~ (pipe) | improved |
| G16c | Which projects are in the Test campaign? | ok | - | wrong | ✗ (pipe) | ✗ (pipe) | same |
| G16lit | Which projects are in a specific country, org,… | ok | - | - | — | — | same |
| B10 | Recommend a project based on what I usually ma… | ok | hit | ok | ✓ | ✓ | same |
| C1 | Has my submitted task been validated yet? | ok | - | ok | ✗ (gen) | ✓ | fixed |
| C2 | How do I request help or a mentor on a task I'… | ok | hit | - | ✓ | ✓ | same |
| C3 | What projects is my organization currently run… | ok | - | capped | ~ (pipe) | ~ (pipe) | improved |
| C5 | How do I register on Tasking Manager? | ok | hit | - | ✓ | ✓ | same |
| C6 | Whom should I reach out to for support? | ok | hit | - | ✓ | ✓ | same |
| C7 | How do I request project manager rights / crea… | ok | hit | - | ~ (gen) | ✓ | improved |
| C8 | How do I get my organization added to Tasking… | ok | miss | - | ✗ (retr) | ✓ | fixed |
| D1 | Where are the tutorials/docs for using iD or J… | ok | miss | - | ~ (retr) | ~ (retr) | same |
| D2 | How many hours have I contributed to Tasking M… | ok | - | ok | ✓ | ✓ | same |
| D7 | Why was my last task invalidated, what did the… | ok | hit | ok | ✓ | ✓ | same |
| D8 | How do I become a validator, not just a mapper… | ok | hit | - | ✓ | ✓ | same |

## Appendix B — artifacts (all in `chat/eval/runs/2026-10-13/`)

- `cases_35.json` (input) · `capture_static.jsonl` (prompt+evidence per case) · `qwen_static.jsonl` · `deepseek_answers.jsonl` (CLI) · `deepseek_static.jsonl` (replay) · `qwen_corrected.jsonl` / `capture_corrected.jsonl` / `deepseek_corrected.jsonl` (G8lit) · `meta.jsonl`
- `joined_2026-10-13.json` (machine-readable join) · `worktable_2026-10-13.md` · `evidence_pack.md` · `trace_index.json` (all trace URLs) · `verdicts_2026-10-13.json` (this adjudication)
- Harnesses: `chat/retrieval/scripts/eval_e2e_attribution.py` (container runner), `chat/eval/harness/deepseek_gen.py` (CLI generator), `chat/eval/harness/attribution_report.py` (join/check)
- Logs: `qwen_static.log`, `deepseek_static.log`, `deepseek_answers.jsonl.log`

*Generated 2026-10-13T07:04:23.635303+00:00 by the executing session.*
