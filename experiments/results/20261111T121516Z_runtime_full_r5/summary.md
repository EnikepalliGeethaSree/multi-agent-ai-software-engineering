# Review time by file size

LLM: groq / openai/gpt-oss-120b. Mode: full, RAG on. 5 rounds per file, concurrency 1, fixes off. Date 2026-11-11. API conditions: groq (provider reply cache off; per-run unit cache only); throttling appears in llm_quota_wait_sec.
Hardware: Windows-10-10.0.26300-SP0, 12 CPUs, Python 3.11.7.

| Size | Run | Complete | Partial/failed/skipped | Mean | Median | P95 | Min | Max | LLM | RAG | Static | Tokens in | Tokens out | Findings | Chunks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small | cold | 5/5 | 0/0/0 | 9.76 | 9.36 | 12.29 | 7.11 | 12.33 | 6.72 | 0.01 | 2.35 | 2410.00 | 2350.00 | 18.40 | 1.00 |
| small | warm | 5/5 | 0/0/0 | 0.16 | 0.16 | 0.17 | 0.16 | 0.17 | 0.00 | 0.01 | 0.02 | - | - | 18.40 | 1.00 |
| medium | cold | 5/5 | 0/0/0 | 20.35 | 20.05 | 23.60 | 17.70 | 24.46 | 17.41 | 0.03 | 2.41 | 11369.00 | 6247.20 | 30.40 | 2.00 |
| medium | warm | 5/5 | 0/0/0 | 0.33 | 0.33 | 0.37 | 0.30 | 0.38 | 0.00 | 0.03 | 0.04 | - | - | 30.40 | 2.00 |
| large | cold | 3/5 | 2/0/0 | 73.77 | 73.28 | 78.08 | 69.41 | 78.62 | 65.98 | 0.16 | 6.77 | 55179.67 | 18388.33 | 19.33 | 10.00 |
| large | warm | 4/5 | 1/0/0 | 5.44 | 0.89 | 16.55 | 0.70 | 19.30 | 4.64 | 0.16 | 0.03 | 6715.00 | 4015.00 | 19.50 | 10.00 |

Files (SHA-256 prefix in results):
- small: `tty.py`, 36 lines, 0.89 KB
- medium: `lzma.py`, 356 lines, 13.31 KB
- large: `locale.py`, 1790 lines, 78.99 KB

Times are seconds. Statistics use complete runs only. P95 with few runs is close to the maximum. '-' means not measured.
