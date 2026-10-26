# 219q A/B summary

### Arm `qwen3-1.7b-q4`
| metric | value |
|---|---|
| questions run | 219 |
| answered (final, non-refusal) | 211 (96.3%) |
| evidence present (expected doc in top-5) | 193 |
| **no answer despite evidence present** | **7 (3.6%)** |
| raw first-pass refusal | 113 (51.6%) |
| repair recovered refusals | 105 of 113 (92.9%) |
| final refusal / low-conf | 8 / 0 |
| judge score (0-2) mean | 1.174 (n=219) |
| judge score 0% / 2% | 27.4% / 44.7% |
| hallucination rate (judge) | 31.5% |
| latency mean / p50 | 13188.691 ms / 13053.0 ms |
| avg completion / prompt tokens | 88.904 / 2623.443 |

By role:

| role | n | answered % | no-answer w/ evidence |
|---|---|---|---|
| administrator | 10 | 100.0 | 0 |
| general | 24 | 100.0 | 0 |
| mapper | 159 | 95.0 | 7 |
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
| judge score (0-2) mean | 1.502 (n=219) |
| judge score 0% / 2% | 16.0% / 66.2% |
| hallucination rate (judge) | 28.8% |
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
- `qwen3-1.7b-q4`: n=219, exact=69.4%, within-1=93.6%
- `gpt-4o-mini`: n=219, exact=75.3%, within-1=89.5%
