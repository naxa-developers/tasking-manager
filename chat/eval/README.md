# Model comparison evals

Compares generation models across three question sets. The model is passed by
environment, so this exercises the production code path.

## Question sets

| Set | File | Cases | What it measures |
|---|---|---|---|
| `kb` | `data/kb.jsonl` | 219 | retrieval + answer quality on documentation questions |
| `router` | `data/router.jsonl` | 80 scorable | route / ops / project-id decisions (7 guardrail rows excluded) |
| `domain` | `data/domain.jsonl` | 32 | full turn against the live database: route, ops, abstention, latency |

`data/kb.jsonl` came from `chat/eval/runs/prepared_219q.json`; `router.jsonl` is
`chat/eval/routing_corpus.jsonl`; `domain.jsonl` is the 32 questions from
`chat/eval/runs/32q_manjita_deploy-rag-dev_2026-10-08.json`.

**Known scoring caveat.** The `kb` set's `expected_docs` were written against a
knowledge-base layout that no longer exists (0 of 258 still resolve), so the set
scores answer overlap with the reference answer, not retrieval recall. The
`router` `ops` metric also penalises this package slightly: `chat/` kept the
requested ops in its decision when a project id was missing (route KB +
`needs_project_id`), while `rag/` drops them. The behaviour is equivalent; the
ops set comparison is not.

## Running against Ollama

Models live outside Docker so the Docker VM memory ceiling stops killing the
model mid-run.

```bash
# Ollama needs a writable home; /tmp is fine but does not survive a reboot.
mkdir -p /tmp/ollama-home
HOME=/tmp/ollama-home OLLAMA_MODELS=/tmp/ollama-home/models \
  OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_HOST=0.0.0.0:11434 OLLAMA_KEEP_ALIVE=30m \
  nohup ollama serve > /tmp/ollama.log 2>&1 &

HOME=/tmp/ollama-home OLLAMA_MODELS=/tmp/ollama-home/models ollama pull qwen3:1.7b
HOME=/tmp/ollama-home OLLAMA_MODELS=/tmp/ollama-home/models ollama pull qwen3:4b
```

Verify the 16k context actually applies (a truncated prompt silently caps at 4096):

```bash
python -c "import litellm; print(litellm.completion(model='ollama/qwen3:1.7b', messages=[{'role':'user','content':'x '*9000+'\nSay OK'}], api_base='http://localhost:11434', drop_params=True, max_tokens=8).usage.prompt_tokens)"
# expect ~9000, not 4096
```

**Thinking is stack-specific — this matters more than the model choice.**

| stack | switch | effect |
|---|---|---|
| llama.cpp | `chat_template_kwargs: {enable_thinking: false}` | honoured: 0 reasoning tokens, clean content, ~50× faster |
| llama.cpp | `/no_think` in the user message | honoured, same result |
| Ollama | `think: false` | removes the thinking channel, so reasoning is written **into the answer** |
| Ollama | no flag | thinking returned separately, content clean, but slow (4B ≈ 105 s/turn) |
| Ollama | `chat_template_kwargs` | ignored |

So: on llama.cpp, disable thinking and get both clean and fast. On Ollama there
is no setting that gives both — that limitation is what made 4B look unusable
(105 s/turn), not the model itself.

## Running the evals

```bash
docker run --rm --network tm-net --add-host=host.docker.internal:host-gateway \
  -e PYTHONPATH=/usr/src/app -e RAG_CHUNKS_PATH=/data/chunks.json \
  -v "$PWD/rag:/usr/src/app/rag:ro" \
  -v "$PWD/tasking-manager.env:/usr/src/app/tasking-manager.env:ro" \
  -v "$PWD/backend:/usr/src/app/backend:ro" \
  -v "$PWD/chat/retrieval/data/chunks.json:/data/chunks.json:ro" \
  -v "$PWD/rag/eval/results:/out" \
  ghcr.io/hotosm/tasking-manager/backend:main \
  python -m rag.eval.run router --model ollama/qwen3:4b \
    --api-base http://host.docker.internal:11434 --out /out/router_4b.json
```

Modes: `kb`, `router`, `domain`, `compare`. `domain` needs `--user-id`.

## Results so far (2026-10-25)

Router, 80 scorable cases:

| | qwen3:1.7b | qwen3:4b |
|---|---|---|
| pass all | 0.525 | **0.675** |
| route | 0.613 | **0.800** |
| ops | 0.613 | **0.750** |
| filters | 0.900 | 0.912 |
| project id | 0.912 | **0.975** |
| latency p50 | 0.3 s | 0.9 s |

KB, 219 cases:

| | qwen3:1.7b | qwen3:4b |
|---|---|---|
| answered | 99.5% | not run |
| abstained | 0.5% | not run |
| answer F1 vs reference | 0.235 | not run |
| latency p50 | 2.3 s | not run |

Domain, 32 cases: 1.7B ran before the `user_tasks` fix (32/32 answered, 0
abstentions, routes KB 16 / DOMAIN 13 / BOTH 3, 2.05 s mean). Needs a re-run.

## Open issues for next session

1. **Killing the runner leaves containers behind.** `docker run` does not die
   with the shell that started it, so a killed eval keeps generating against
   Ollama and steals the model slot. Check `docker ps` before re-running — the
   712-token generations blamed on a `max_tokens` bug were an orphaned
   container from the previous run. `max_tokens` itself is honoured by
   LiteLLM's Ollama adapter (verified: 60 requested, 60 produced).
2. **Re-run `domain` for both models** after the `user_tasks` scope fix
   (registry said `optional_project`, handler takes `(user_id, db)`).
3. **Run `kb` for 4B** (219 cases, ~15–25 min).
4. Router families that fail for both models: `E-deictic-followups` 2/8 and
   `G-adversarial-bounds` 9/15. The follow-up failures are mostly over-selection
   (DOMAIN→BOTH) plus the ops-in-KB convention above; the adversarial ones are
   partly expectations that `chat/`'s scope classifier answered, which this
   package deliberately dropped.
