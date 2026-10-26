# rag — the minimal Tasking Manager assistant

Five stages, one path. Everything semantic is the model's decision; only the
injection guard and the response contract are deterministic.

```
question
  → rag.guard       deterministic injection check (the only non-LLM step)
  → rag.router      one LLM call → route: KB | DOMAIN | BOTH (+ ops, project_id, filters)
  → rag.retrieval   cosine + BM25, fused with RRF      (KB, BOTH)
  → rag.domain      read-only service calls            (DOMAIN, BOTH)
  → rag.generate    one LLM call → answer + citations
```

A **turn** is one question and its answer, stored as a single row and exchanged
as a single object. A session is a list of turns — not a stream of role-tagged
messages.

## Layout

| File | Role |
|---|---|
| `pipeline.py` | `run_turn()` — the five stages, `Turn` result |
| `router.py` | router prompt, JSON contract, validation, KB fallback |
| `retrieval.py` | hybrid pgvector + BM25 retriever (RRF) |
| `generate.py` | passage cleaning, prompt fitting, generation (one-shot and stream) |
| `guard.py` | injection detection and untrusted-text neutralization |
| `sessions.py` | session + turn store; ownership enforced here |
| `rate_limit.py` | per-user fixed window in Postgres |
| `domain/registry.py` | **the** op catalogue: one record per operation |
| `domain/dispatch.py` | runs selected ops with per-op timeout, merges evidence |
| `domain/*.py` | 31 read-only operation handlers |
| `api.py` | `/rag` routes: sessions, turns, one-shot |
| `cli.py` | `python -m rag.cli "question"` |
| `smoke.py` | `python -m rag.smoke --user-id … --project …` |

## Sessions, turns, ownership

`POST /rag/sessions` starts a conversation. `POST /rag/sessions/{id}/turns` sends
one turn — the body is just `{"question": "..."}` and the response is the
completed turn with its answer, route, ops, and citations. History is read from
the session's stored turns; the client never sends message history.

Ownership lives in the store. Every public function in `sessions.py` resolves the
session through `_owned(session_id, user_id, db)`, which raises `SessionNotFound`
for an unknown id **or** an id owned by someone else — the two are deliberately
indistinguishable. A new endpoint gets the 404 rule by construction.

The table is `rag_turns` (question and answer in one row), created by migration
`c4a9e2f17b83`. `rag_sessions.message_count` now counts turns; the API exposes it
as `turn_count`.

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

`rag.api.router` carries the `/rag` prefix and is mounted in
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
python -m rag.cli "how many tasks are mapped in project 6?" --user-id 10250456 --stream
python -m rag.smoke --user-id 10250456 --project 6
pytest rag/tests
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
  python -m rag.smoke --user-id 10250456 --project 6
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `RAG_RETRIEVAL_TOP_K` | 5 | fused passages handed to the prompt (0 = all) |
| `RAG_PROMPT_TOKEN_BUDGET` | 11776 | generation prompt budget (set for a 16k context) |
| `RAG_HISTORY_MAX_TURNS` | 6 | prior turns fitted into the generation prompt |
| `RAG_DOMAIN_TIMEOUT` | 5 | per-operation seconds |
| `RAG_CHUNKS_PATH` | `../chat/retrieval/data/chunks.json` | KB chunk build |
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
