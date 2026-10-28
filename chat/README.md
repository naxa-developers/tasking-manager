# chat — the minimal Tasking Manager assistant

Six stages, one path. The router decides the route; the injection guard, the
retrieval gate, and the canned responses are deterministic.

```
question
  → chat.guard        deterministic injection check (the only non-LLM input gate)
  → chat.router       one LLM call → route: KB | DOMAIN | BOTH | OUT_OF_SCOPE
  → chat.retrieval    cosine + BM25, fused with RRF      (KB, BOTH)
  → chat.retrieval_gate  dense/lexical relevance gate    (KB, BOTH)
  → chat.domain       read-only service calls            (DOMAIN, BOTH)
  → chat.generate     one LLM call → answer + citations
```

`OUT_OF_SCOPE` and a failed retrieval gate never reach generation; they return
canned copy. A `BOTH` turn whose KB arm fails the gate can still answer from
the domain evidence.

A **turn** is one question and its answer, stored as a single row and exchanged
as a single object. A session is a list of turns — not a stream of role-tagged
messages.

## Layout

| File | Role |
|---|---|
| `pipeline.py` | `run_turn()` — the five stages, `Turn` result |
| `router.py` | router prompt, JSON contract, validation, `OUT_OF_SCOPE`, KB fallback |
| `retrieval.py` | hybrid pgvector + BM25 retriever (RRF) |
| `retrieval_gate.py` | dense/lexical relevance gate before generation |
| `generate.py` | passage cleaning, prompt fitting, generation (one-shot and stream) |
| `guard.py` | injection detection and untrusted-text neutralization |
| `sessions.py` | session + turn store; ownership enforced here |
| `rate_limit.py` | per-user fixed window in Postgres |
| `domain/registry.py` | **the** op catalogue: one record per operation |
| `domain/dispatch.py` | runs selected ops with per-op timeout, merges evidence |
| `domain/*.py` | 31 read-only operation handlers |
| `api.py` | `/rag` routes: sessions, turns, one-shot |
| `cli.py` | `python -m chat.cli "question"` |
| `smoke.py` | `python -m chat.smoke --user-id … --project …` |

## Sessions, turns, ownership

`POST /rag/sessions` starts a conversation. `POST /rag/sessions/{id}/turns` sends
one turn — the body is `{"question": "...", "client_message_id": "..."}` and the
response is the completed turn with its answer, route, ops, and citations.
`client_message_id` is optional; when supplied, a retried POST (streaming or not)
returns the already-stored turn instead of generating again. A streaming replay
is one SSE delta followed by `meta` and `done`. History is read from the
session's stored turns; the client never sends message history.

Ownership lives in the store. Every public function in `sessions.py` resolves the
session through `_owned(session_id, user_id, db)`, which raises `SessionNotFound`
for an unknown id **or** an id owned by someone else — the two are deliberately
indistinguishable. A new endpoint gets the 404 rule by construction.

The table is `rag_turns` (question and answer in one row), created by migration
`c4a9e2f17b83`; `9e7c1a4b2d6f` adds the idempotency key. `rag_sessions.message_count`
now counts turns; the API exposes it as `turn_count`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/rag/health` | index + config diagnostics (503 when the index is unavailable) |
| GET | `/rag/ready` | strict probe: `/health` plus reachable providers (503 otherwise) |
| POST | `/rag/sessions` | create |
| GET | `/rag/sessions` | list the caller's sessions |
| GET | `/rag/sessions/{id}` | one session (404 if not yours) |
| PATCH | `/rag/sessions/{id}` | rename |
| DELETE | `/rag/sessions/{id}` | delete, cascading turns |
| GET | `/rag/sessions/{id}/turns` | the conversation as turns |
| POST | `/rag/sessions/{id}/turns` | **send a turn** (`"stream": true` for SSE) |
| POST | `/rag/ask` | stateless one-shot, no persistence (`"stream"` supported) |

Rate limiting is per user, `RAG_CHAT_RATE_LIMIT` turns per
`RAG_CHAT_RATE_WINDOW_SECONDS`, counted in `rag_rate_limits` so workers share one
window. It fails open: a counter-store error allows the turn.

### Streaming

Add `"stream": true` to either POST and the endpoint answers with
`text/event-stream`. The same endpoint, the same persistence — only the encoding
changes.

```
data: {"delta": "170 tasks are"}          ← repeated as the model generates
event: meta
data: {"session_id":"552","turn_id":"6","route":"DOMAIN","ops":["stats"],
       "project_id":6,"reason":"ok","candidate_count":0,"model":"...","degraded":false}
event: done
data: {}
```

`error` (`{"error": "..."}`) can appear before `done` when generation broke. A
turn whose `reason` is `error` is not persisted, and a stream that failed after
some text was sent finishes with that partial text marked incomplete.

**Canned answers stream too.** A blocked prompt, a route whose evidence never
arrived, or a low-confidence turn is emitted as a single `data: {"delta": …}`
followed by `meta` and `done`. The client needs one code path whether or not the
model was called.

### Mounting

`chat.api.router` carries the `/rag` prefix and is mounted in
`backend/routes.py`, so the app serves `/api/v2/rag/*`. It replaced the
`chat/` router; both claim the same paths, so only one can be mounted.

The frontend client (`frontend/src/api/rag.js`) posts to
`/rag/sessions/{id}/turns`, and `RagChat.js` flattens the returned turns into
messages for display.

### Passage cleaning

`generate.clean_passage()` is the single place that decides what a retrieved
chunk looks like inside the prompt. It strips titles, repository paths, `.md`
links, `SubCode`s, chunk ids, "needs verification" annotations and LearnOSM
labels; it flattens headings, links and emphasis; and it neutralizes `<evidence>`
fence tags so a passage cannot close its own section. Provenance stays in the
citations, which is the only place it is useful.

Cleaning runs on the raw text and **before** injection neutralization, because
the `Title:` rule is line-aware and neutralization collapses newlines.

## Adding an operation

One record in `domain/registry.py`. The router prompt, the dispatcher, and the
parity test all read that table, so nothing else needs editing and the prompt
cannot drift from what dispatch can execute.

```python
Op("my_op", "What it answers, in one line.", "project",
   _loader("my_module", "get_my_op_evidence"))
```

Scope picks the call shape: `project` → `(user_id, project_id, db)`,
`optional_project` → same but the id may be None, `personal` → `(user_id, db)`,
`filter` → `(user_id, project_id, db, filters)`.

## Running

Needs the stack from the repo root (`tm-db`, `tm-embedding`, `tm-llm`) and
`LITELLM_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`, `PGVECTOR_*` set in
`tasking-manager.env`. Apply the migration once:

```bash
docker compose run --rm --no-deps tm-migration
```

```bash
python -m chat.cli "how many tasks are mapped in project 6?" --user-id 10250456 --stream
python -m chat.smoke --user-id 10250456 --project 6
pytest chat/tests
```

Inside Docker (the containers live on `tm-net`):

```bash
docker run --rm --network tm-net -e PYTHONPATH=/usr/src/app \
  -e RAG_CHUNKS_PATH=/data/chunks.json \
  -v "$PWD/rag:/usr/src/app/rag:ro" \
  -v "$PWD/tasking-manager.env:/usr/src/app/tasking-manager.env:ro" \
  -v "$PWD/backend:/usr/src/app/backend:ro" \
  -v "$PWD/chat/retrieval/data/chunks.json:/data/chunks.json:ro" \
  ghcr.io/hotosm/tasking-manager/backend:main \
  python -m chat.smoke --user-id 10250456 --project 6
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_ENABLED` | 1 | set 0 to disable `/rag` routes (health/readiness stay up) |
| `RAG_RETRIEVAL_TOP_K` | 5 | fused passages handed to the prompt (0 = all) |
| `RAG_RETRIEVAL_ARM_TOP_K` | 30 | candidates fetched from each retrieval arm before RRF |
| `RAG_DENSE_SCORE_THRESHOLD` | 0.35 | top-1 dense similarity accepted without lexical rescue |
| `RAG_DENSE_SCORE_FLOOR` | 0.20 | minimum dense similarity for lexical rescue |
| `RAG_TERM_COVERAGE_THRESHOLD` | 0.75 | query-term coverage required for lexical rescue |
| `RAG_PROMPT_TOKEN_BUDGET` | 11776 | generation prompt budget (set for a 16k context) |
| `RAG_HISTORY_MAX_TURNS` | 6 | prior turns fitted into the generation prompt |
| `RAG_DOMAIN_TIMEOUT` | 5 | per-operation seconds |
| `RAG_CHUNKS_PATH` | `chat/data/chunks.json` | KB chunk build |
| `RAG_ROUTER_MODEL` | generation model | set only to route with a different model |
| `RAG_GENERATION_EXTRA_BODY` | `{}` | provider body for generation, e.g. `{"chat_template_kwargs":{"enable_thinking":false}}` |
| `RAG_ROUTER_EXTRA_BODY` | `{}` | same for the routing call |
| `RAG_CHAT_RATE_LIMIT` | 20 | turns per user per window (0 disables) |
| `RAG_CHAT_RATE_WINDOW_SECONDS` | 60 | window length |
| `RAG_READY_CACHE_TTL` | 30 | seconds a provider probe result is reused |
| `RAG_READY_REQUIRE_PROBE` | off | fail readiness when a provider has no api_base |

## Deliberate non-features

- **No clarification branch.** A project-scoped op with no project id is dropped
  and generation asks which project.
- **No regex project-id grounding.** The model may not invent an id per the
  prompt, and every fetcher runs `authorize_project`, so an invented id returns
  `NOT_FOUND` rather than another user's data.
- **No refusal repair.** A model that answers with a refusal gets its text
  returned; `chat/` substituted canned copy instead.

## After consolidation (2026-10-26)

This package is now the implementation that was prototyped as `rag/`. The old
`chat/` pipeline (message-based sessions, scope classifier, clarification turns,
refusal repair, multi-orchestrator ladder) was removed; branch
`consolidate/rag-into-chat` and tag `pre-consolidation` hold the previous state.

- Knowledge-base data lives in `chat/data/` (`chunks.json`,
  `embeddings_tmkb.npz`); `chat/retrieval.py` defaults to it.
- Ingestion tooling lives in `chat/kb/`: `chunk.py` plus
  `scripts/index_kb.py`, `import_tm_kb.py`, `index_qwen_npy.py`, `dump_bm25.py`.
- **Not yet wired:** `chat/kb/debug_report.py` and
  `chat/kb/scripts/debug_turn.py` still target the old pipeline API and need
  porting onto `chat.pipeline.prepare_turn()`.
- **Not yet ported** from the old implementation: project-id clarification
  (falls back to KB today) and refusal repair (a refusal reaches the user
  verbatim). See `PORTING-NOTES.md`.
