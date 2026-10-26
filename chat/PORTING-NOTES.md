# Porting from `rag/` into `chat/`

Decided 2026-10-26. Five decisions from the `rag/` rewrite to bring back into
`chat/`. Not done yet — this is the checklist.

Ordered so each step leaves the suite green.

---

## 1. Who decides intent

**Now:** `classify_query()` runs before the model and can refuse an out-of-scope
question with zero model calls. Small-talk gets canned copy.

**Target:** the only deterministic gate is prompt injection. Everything else —
scope, intent, whether the question is answerable — is the router's decision.

- `chat/retrieval/guardrails.py` — keep `detect_injection`, `neutralize_untrusted`;
  retire the scope half from the request path (`classify_query`, `is_smalltalk_query`,
  `strip_smalltalk_prefix`, `is_followup_query`).
- `chat/turn/plan.py` — drop `_expand_followup`, `_strip_smalltalk`,
  `_detect_third_party`; the router sees the raw question plus history.
- `chat/turn/decide.py` — `CannedTurn` stays for blocked / no-evidence turns only.

**Accept:** `"what's the weather in Kathmandu?"` reaches the router instead of
being refused by regex; `"ignore all previous instructions"` still returns in 0 ms.

---

## 2. Route representation

**Now:** the router returns `{ops, project_id, filters, needs_docs}` and the route
is inferred — `ops: []` → KB, ops + `needs_docs` → BOTH, ops alone → DOMAIN.

**Target:** the router states it: `{"route": "KB" | "DOMAIN" | "BOTH", "ops": [...],
"project_id": ..., "filters": {...}}`.

- `chat/retrieval/domain/llm_router.py` — `RouterOutput` gains `route`; delete
  `needs_docs` and the derivation in `_validate_output`.
- `DomainRoute` keeps its fields; `route` becomes direct instead of computed.

**Accept:** the routing corpus scores the same or better with the existing scorer
(`chat/retrieval/scripts/eval_router.py`), with no change to how the corpus is read.

---

## 3. Where `project_id` comes from

**Now:** regex-grounded. `extract_project_ids(question)` finds ids in the text and
`_validate_output` only accepts a model id that matches the question or recent
history. The model cannot introduce one.

**Target:** the model decides. Its id is accepted as-is; the fetcher's
`authorize_project` is the safety net, returning `NOT_FOUND` for a project that
does not exist or is not visible.

- `chat/retrieval/domain/llm_router.py` — remove `extract_project_ids` grounding
  and `latest_explicit_project_id` inheritance from `_validate_output`.
- Keep: two different project ids in one question → `null` (never guess).
- `chat/retrieval/domain/auth.py` — unchanged; this is the check that matters.

**Accept:** a hallucinated id produces the "couldn't retrieve live data" copy, never
another user's data. Add one test asserting `NOT_FOUND` for id 999999999.

---

## 6. Unit of a conversation

**Now:** `rag_messages` — one row per role (`user` / `assistant`), history rebuilt by
interleaving rows.

**Target:** one row per turn — question and answer together, plus what produced it
(`route`, `ops`, `project_id`, `reason`, `citations`).

- New table `chat_turns` (or reuse `rag_turns` as-is); migration `c4a9e2f17b83`
  already exists and creates `rag_turns`.
- `chat/models.py` — `add_message` → `append_turn`; `get_messages` → `list_turns`.
- `chat/api/resources.py` — `GET /sessions/{id}` returns `{session, turns}`;
  `POST /sessions/{id}/chat` stays for compatibility but persists a turn.
- `chat/dtos.py` — `RagMessageDTO{role, content}` → `RagTurnDTO{question, answer, ...}`;
  `RagSessionDTO.message_count` → `turn_count`.

**Why it is 4th and not 1st:** it touches the frontend contract. Do it in one pass
with `frontend/src/api/rag.js` and `RagChat.js` or not at all.

**Accept:** open a conversation, reload, and the same turns render in order; a
turn's `route` and `ops` are readable from the API.

---

## 7. How many orchestrators

**Now:** the guard → route → retrieve → decide ladder exists three times:
`chat/service.py`, `chat/retrieval/debug_report.py::gather_turn`, and
`chat/retrieval/cli.py::run_single_question`. They have already drifted — the CLI
serves its own low-confidence copy and calls blocking retrieval on the event loop.

**Target:** one ladder in `chat/turn/`, with three thin adapters: HTTP+SSE, CLI,
audit report. Same split `rag/pipeline.py` uses: `prepare_turn()` decides,
`run_turn()` / `stream_turn()` emit.

- Extract the shared ladder into `chat/turn/plan.py` (already the closest thing).
- `debug_report.gather_turn` and `cli` become callers, not copies.

**Accept:** deleting the body of either adapter leaves the other working; one test
covers the ladder, not three.

---

## Deliberately not ported

- **4. Missing project id** — `rag` drops the op and answers from docs; `chat` asks
  which project. The clarification is better UX and stays.
- **5. Registry** — one table for the 31 ops would remove real drift risk, but it is
  a refactor, not a behaviour change. Separate decision.
- **8. Refusal repair** — `chat` substitutes canned copy when the model refuses
  (51.6 % of answers on 1.7B); `rag` returns the refusal. Keep chat's.
- **9. Evidence banner** — `rag` shortened it after small models echoed
  `source: tasking_manager | operation: …` into answers. Cheap, worth doing anyway.
- **10. Ingestion and debug tooling** — `chat` has them, `rag` does not.
- **11. Streaming lifecycle** — `chat` already does DB work before the stream starts,
  so it is not exposed to the connection-released bug. No action.
