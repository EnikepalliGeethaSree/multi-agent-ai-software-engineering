# Estimate for the pending Groq experiments

- Model: `openai/gpt-oss-120b`
- Prices (USD per 1M tokens, from .env): input 0.15, output 0.6
- Rate limits (from .env): RPM 1000, TPM 250000
- Hard token cap: 8100000; spending cap: 4.5
- Assumes cache misses (every request sent); repeated runs use --no-cache.

| Experiment | Calls | Input tokens | Output tokens | Total tokens | Input cost | Output cost | Total cost | Worst-case tokens | Time at the limits |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3.1 Planted issues B/C/D x 3 runs | 39 | 63,808 | 62,798 | 126,606 | $0.01 | $0.04 | $0.05 | 244,821 | 1 min |
| 3.1 CodeReviewer comments B/C/D x 3 runs x 40 | 360 | 1,198,608 | 573,570 | 1,772,178 | $0.18 | $0.34 | $0.52 | 3,072,704 | 7 min |
| 3.10 Clean repos (requests, flask, pydantic), D: 339 units + fixes | 363 | 1,043,434 | 658,391 | 1,701,825 | $0.16 | $0.40 | $0.55 | 2,878,093 | 7 min |
| 3.12 Runtime benchmark (cap 200 calls) | 200 | 574,895 | 362,750 | 937,645 | $0.09 | $0.22 | $0.30 | 1,585,726 | 4 min |
| 4 BugsInPy localization B/C/D, 40 bugs (dev + test) | 120 | 671,592 | 191,190 | 862,782 | $0.10 | $0.11 | $0.22 | 1,386,976 | 3 min |
| 4 BugsInPy detection B/C/D, 40 bugs x buggy + fixed | 240 | 570,104 | 382,380 | 952,484 | $0.09 | $0.23 | $0.31 | 1,743,179 | 4 min |
| TOTAL (all pending) | 1,322 | 4,122,441 | 2,231,079 | 6,353,520 | $0.62 | $1.34 | $1.96 | 10,911,499 | 25 min |

Per-call profiles (tokens) and their source runs:

- planted_B: input 1270, output 1428 (20261012T161026Z_planted_llm_only (Groq))
- planted_C: input 1452, output 1538 (20261012T161133Z_planted_static_llm (Groq))
- planted_D: input 2076, output 1814 (20261012T161434Z_planted_static_llm_rag (Groq))
- crmsg_B: input 2742, output 1428 (20261109T084547Z_codereviewer_msg_test_llm_only_n40 (input))
- crmsg_C: input 2858, output 1538 (20261109T100904Z_codereviewer_msg_test_static_llm_n40 (input))
- crmsg_D: input 4389, output 1814 (20261109T114916Z_codereviewer_msg_test_static_llm_rag_n40 (input))
- runtime: input 2874, output 1814 (20261106T162014Z_runtime_full_r5 (input per call))
- loc_B: input 5390, output 1428 (20261108T091827Z_bugsinpy_localization_dev_llm_only_n5 (input))
- loc_C: input 5689, output 1538 (20261108T091827Z_bugsinpy_localization_dev_static_llm_n5 (input))
- loc_D: input 5711, output 1814 (20261108T091827Z_bugsinpy_localization_dev_static_llm_rag_n5 (input))
- det_B: input 1649, output 1428 (20261108T095449Z_bugsinpy_detection_dev_llm_only_n5 (input))
- det_C: input 1671, output 1538 (20261108T095449Z_bugsinpy_detection_dev_static_llm_n5 (input))
- det_D: input 3806, output 1814 (20261108T095449Z_bugsinpy_detection_dev_static_llm_rag_n5 (input))
