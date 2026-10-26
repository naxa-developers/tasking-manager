# 219q A/B summary

### Arm `qwen3-1.7b-q4`
| metric | value |
|---|---|
| questions run | 219 |
| answered (final, non-refusal) | 219 (100.0%) |
| evidence present (expected doc in top-5) | 193 |
| **no answer despite evidence present** | **0 (0.0%)** |
| raw first-pass refusal | 113 (51.6%) |
| repair recovered refusals | 113 of 113 (100.0%) |
| final refusal / low-conf | 0 / 0 |
| judge score (0-2) mean | 0.927 (n=219) |
| judge score 0% / 2% | 27.4% / 20.1% |
| hallucination rate (judge) | 45.2% |
| latency mean / p50 | 13246.425 ms / 13122.3 ms |
| avg completion / prompt tokens | 88.904 / 2623.443 |

By role:

| role | n | answered % | no-answer w/ evidence |
|---|---|---|---|
| administrator | 10 | 100.0 | 0 |
| general | 24 | 100.0 | 0 |
| mapper | 159 | 100.0 | 0 |
| project_manager | 13 | 100.0 | 0 |
| validator | 13 | 100.0 | 0 |

### Arm `gpt-4o-mini`
| metric | value |
|---|---|
| questions run | 219 |
| answered (final, non-refusal) | 219 (100.0%) |
| evidence present (expected doc in top-5) | 193 |
| **no answer despite evidence present** | **0 (0.0%)** |
| raw first-pass refusal | 3 (1.4%) |
| repair recovered refusals | 3 of 3 (100.0%) |
| final refusal / low-conf | 0 / 0 |
| judge score (0-2) mean | 1.356 (n=219) |
| judge score 0% / 2% | 10.5% / 46.1% |
| hallucination rate (judge) | 37.0% |
| latency mean / p50 | 2147.134 ms / 2049.7 ms |
| avg completion / prompt tokens | 113.626 / 2608.963 |

By role:

| role | n | answered % | no-answer w/ evidence |
|---|---|---|---|
| administrator | 10 | 100.0 | 0 |
| general | 24 | 100.0 | 0 |
| mapper | 159 | 100.0 | 0 |
| project_manager | 13 | 100.0 | 0 |
| validator | 13 | 100.0 | 0 |

### Judge agreement (gpt-4o audit sample)
- `qwen3-1.7b-q4`: n=219, exact=59.8%, within-1=97.3%
- `gpt-4o-mini`: n=219, exact=56.6%, within-1=95.9%
