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
| `20261111T111106Z_planted_llm_only` | planted | B | 12 | 12 | 12 (0 failed) | 0 | 12 | 12 | 0.000 |
| `20261111T111123Z_planted_static_llm` | planted | C | 7 | 7 | 7 (0 failed) | 0 | 7 | 7 | 0.000 |
| `20261111T111144Z_planted_static_llm_rag` | planted | D | 13 | 13 | 13 (0 failed) | 0 | 13 | 13 | 0.000 |
| `20261111T111217Z_planted_llm_only` | planted | B | 11 | 11 | 11 (0 failed) | 0 | 11 | 11 | 0.000 |
| `20261111T111237Z_planted_static_llm` | planted | C | 8 | 8 | 8 (0 failed) | 0 | 8 | 8 | 0.000 |
| `20261111T111306Z_planted_static_llm_rag` | planted | D | 15 | 15 | 15 (0 failed) | 0 | 15 | 13 | 0.000 |
| `20261111T111338Z_planted_llm_only` | planted | B | 12 | 12 | 12 (0 failed) | 0 | 12 | 12 | 0.000 |
| `20261111T111358Z_planted_static_llm` | planted | C | 10 | 10 | 10 (0 failed) | 0 | 10 | 10 | 0.000 |
| `20261111T111430Z_planted_static_llm_rag` | planted | D | 7 | 7 | 7 (0 failed) | 0 | 7 | 7 | 0.000 |
| `20261111T111615Z_codereviewer_msg_test_llm_only_n40` | codereviewer | B | 41 | 41 | 40 (1 failed) | 11 | 29 | 29 | 0.024 |
| `20261111T111914Z_codereviewer_msg_test_static_llm_n40` | codereviewer | C | 49 | 49 | 48 (1 failed) | 28 | 20 | 20 | 0.020 |
| `20261111T112247Z_codereviewer_msg_test_static_llm_rag_n40` | codereviewer | D | 69 | 69 | 68 (1 failed) | 36 | 32 | 32 | 0.015 |
| `20261111T112702Z_codereviewer_msg_test_llm_only_n40` | codereviewer | B | 40 | 40 | 39 (1 failed) | 13 | 26 | 26 | 0.025 |
| `20261111T113024Z_codereviewer_msg_test_static_llm_n40` | codereviewer | C | 61 | 61 | 60 (1 failed) | 32 | 28 | 28 | 0.016 |
| `20261111T113432Z_codereviewer_msg_test_static_llm_rag_n40` | codereviewer | D | 61 | 61 | 61 (0 failed) | 31 | 30 | 30 | 0.000 |
| `20261111T113839Z_codereviewer_msg_test_llm_only_n40` | codereviewer | B | 38 | 38 | 37 (1 failed) | 9 | 28 | 28 | 0.026 |
| `20261111T114143Z_codereviewer_msg_test_static_llm_n40` | codereviewer | C | 62 | 62 | 61 (1 failed) | 30 | 31 | 31 | 0.016 |
| `20261111T114545Z_codereviewer_msg_test_static_llm_rag_n40` | codereviewer | D | 69 | 69 | 69 (0 failed) | 42 | 27 | 27 | 0.000 |
| `20261111T115458Z_cleanrepo_requests_static_llm_rag` | cleanrepo | D | 66 | 66 | 66 (0 failed) | 0 | 66 | 66 | 0.000 |
| `20261111T115751Z_cleanrepo_flask_static_llm_rag` | cleanrepo | D | 79 | 79 | 76 (3 failed) | 0 | 76 | 76 | 0.038 |
| `20261111T120830Z_cleanrepo_pydantic_static_llm_rag` | cleanrepo | D | 264 | 264 | 262 (2 failed) | 0 | 262 | 262 | 0.008 |

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

