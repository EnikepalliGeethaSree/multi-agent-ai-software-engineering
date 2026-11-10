# Hallucination and pipeline funnel

Stages: produced -> passed schema -> quote verified at the cited lines -> actionable -> after dedupe. Hallucination rate = failed quote check / passed schema. N/A: the run was made before that counter was recorded.

## gemini / gemini-3.6-flash

| Run | Benchmark | Config | Produced | Passed schema | Quote verified | Other rejected | Actionable | After dedupe | Hallucination rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `20261108T055018Z_planted_llm_only` | planted | B | N/A | 12 | 12 (0 failed) | 0 | 12 | N/A | 0.000 |
| `20261108T055101Z_planted_static_llm` | planted | C | N/A | 11 | 11 (0 failed) | 0 | 11 | N/A | 0.000 |
| `20261108T055201Z_planted_static_llm_rag` | planted | D | N/A | 14 | 14 (0 failed) | 0 | 14 | N/A | 0.000 |

## groq / openai/gpt-oss-120b

| Run | Benchmark | Config | Produced | Passed schema | Quote verified | Other rejected | Actionable | After dedupe | Hallucination rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `20260929T194203Z_planted_full` | planted | D | N/A | 10 | 9 (1 failed) | 0 | N/A | N/A | 0.100 |
| `20261012T090444Z_planted_full` | planted | D | N/A | 11 | 10 (1 failed) | 0 | 10 | N/A | 0.091 |
| `20261012T161026Z_planted_llm_only` | planted | B | N/A | 10 | 10 (0 failed) | 0 | 10 | N/A | 0.000 |
| `20261012T161133Z_planted_static_llm` | planted | C | N/A | 7 | 7 (0 failed) | 0 | 7 | N/A | 0.000 |
| `20261012T161434Z_planted_static_llm_rag` | planted | D | N/A | 9 | 7 (2 failed) | 0 | 7 | N/A | 0.222 |

## groq / openai/gpt-oss-20b

| Run | Benchmark | Config | Produced | Passed schema | Quote verified | Other rejected | Actionable | After dedupe | Hallucination rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `20260929T194356Z_planted_full` | planted | D | N/A | 16 | 16 (0 failed) | 0 | N/A | N/A | 0.000 |

## groq / qwen/qwen3.8-27b

| Run | Benchmark | Config | Produced | Passed schema | Quote verified | Other rejected | Actionable | After dedupe | Hallucination rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `20260929T194832Z_planted_full` | planted | D | N/A | 13 | 13 (0 failed) | 0 | N/A | N/A | 0.000 |

## ollama / qwen2.5-coder:7b

| Run | Benchmark | Config | Produced | Passed schema | Quote verified | Other rejected | Actionable | After dedupe | Hallucination rate |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `20261108T074052Z_planted_llm_only` | planted | B | N/A | 7 | 6 (1 failed) | 0 | 6 | N/A | 0.143 |
| `20261108T074755Z_planted_static_llm` | planted | C | N/A | 12 | 11 (1 failed) | 0 | 11 | N/A | 0.083 |
| `20261108T075847Z_planted_static_llm_rag` | planted | D | N/A | 13 | 12 (1 failed) | 0 | 12 | N/A | 0.077 |

