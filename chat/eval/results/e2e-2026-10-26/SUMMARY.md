# E2E model comparison — 2026-10-26

Sets: **KB 50** (first 50 of the 219 curated questions), **router 33** (first 33
scorable routing cases), **domain 32** (the full 32-question live-data set).
KB index: 83 curated chunks. User: 10250456.

| model | KB F1¹ | KB abstain | KB p50 | router pass | route | ops | router p50 | domain | abst | domain p50 |
|---|---|---|---|---|---|---|---|---|---|---|
| gpt-4o-mini | 0.270 | 4% | 1.6 s | **0.727** | **0.879** | 0.818 | 1.0 s | 32/32 | 0 | **2.2 s** |
| deepseek-flash | 0.256 | 0% | 2.7 s | **0.758** | 0.848 | **0.879** | 1.3 s | 32/32 | 1 | 3.4 s |
| Qwen3-1.7B (llama.cpp) | 0.277 | 12% | 2.8 s | 0.636 | 0.848 | 0.758 | **0.6 s** | 32/32 | 0 | 2.8 s |
| Qwen3-4B (llama.cpp) | 0.290 | 12% | 10.0 s | 0.636 | 0.848 | 0.758 | 1.4 s | 32/32 | 0 | 11.1 s |

¹ Token-overlap F1 against the reference answer. It does **not** separate these
models (0.256–0.290 across the board); it is not a quality ranking.

## Findings

- **Hosted models route best** (0.727 / 0.758 pass-all vs 0.636 for both Qwens).
  The gap is almost entirely `ops` selection; `project_id` is 1.0 for everyone.
- **Qwen3-1.7B and 4B score identically on routing**, which suggests the misses
  are prompt/few-shot bound rather than model-capacity bound.
- **4B is 4-5× slower than 1.7B** on the same prompts (11.1 s vs 2.8 s p50).
- **4B returns empty completions** on long KB prompts when thinking is disabled:
  17/50 failed first, 12/50 after adding a one-shot retry with thinking on.
  The bytes come back empty with a 200 and no server-side error, so the pipeline
  reports `error` and the answer is lost. This is the strongest argument against
  4B with `enable_thinking: false` for KB traffic.
- **KB abstention**: 1.7B/4B abstain on 12% of curated questions vs 0-4% hosted —
  the 83-chunk index has no coverage for some, but the local models also abstain
  more readily.

## Not measured

- Cost (token usage is recorded per turn in the JSON, not aggregated).
- Answer correctness beyond F1 — no judge ran; domain answers were not adjudicated.

## Files

`kb_*.json`, `router_*.json`, `domain_*.json` per model. `kb_qwen4b_nothinking.json`
is the 4B run before the retry was added (17 failures).
