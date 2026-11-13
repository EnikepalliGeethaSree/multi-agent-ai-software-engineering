# Review time by file size

LLM: groq / openai/gpt-oss-120b. Mode: full, RAG on. 5 rounds per file, concurrency 1, fixes off. Date 2026-11-11. API conditions: free tier; throttling appears in llm_quota_wait_sec.
Hardware: Windows-10-10.0.26300-SP0, 12 CPUs, Python 3.11.7.

| Size | Run | Complete | Partial/failed/skipped | Mean | Median | P95 | Min | Max | LLM | RAG | Static | Tokens in | Tokens out | Findings | Chunks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small | cold | 5/5 | 0/0/0 | 4.23 | 2.74 | 8.84 | 2.60 | 10.35 | 1.09 | 0.01 | 2.34 | 2410.00 | 1886.00 | 18.00 | 1.00 |
| small | warm | 5/5 | 0/0/0 | 0.16 | 0.16 | 0.17 | 0.15 | 0.17 | 0.00 | 0.01 | 0.02 | - | - | 18.00 | 1.00 |
| medium | cold | 5/5 | 0/0/0 | 8.71 | 3.01 | 20.18 | 2.85 | 22.03 | 5.68 | 0.03 | 2.44 | 8579.50 | 4858.50 | 30.40 | 2.00 |
| medium | warm | 5/5 | 0/0/0 | 0.31 | 0.29 | 0.36 | 0.28 | 0.37 | 0.00 | 0.03 | 0.05 | - | - | 30.40 | 2.00 |
| large | cold | 5/5 | 0/0/0 | 21.03 | 7.49 | 61.82 | 7.30 | 75.38 | 13.48 | 0.16 | 6.43 | 54933.00 | 19341.00 | 20.00 | 10.00 |
| large | warm | 5/5 | 0/0/0 | 0.77 | 0.73 | 0.88 | 0.71 | 0.91 | 0.00 | 0.16 | 0.04 | - | - | 20.00 | 10.00 |

Files (SHA-256 prefix in results):
- small: `tty.py`, 36 lines, 0.89 KB
- medium: `lzma.py`, 356 lines, 13.31 KB
- large: `locale.py`, 1790 lines, 78.99 KB

Times are seconds. Statistics use complete runs only. P95 with few runs is close to the maximum. '-' means not measured.
