# Review time by file size

LLM: gemini / gemini-3.6-flash. Mode: full, RAG on. 5 rounds per file, concurrency 1, fixes off. Date 2026-11-06. API conditions: free tier; throttling appears in llm_quota_wait_sec.
Hardware: Windows-10-10.0.26300-SP0, 12 CPUs, Python 3.11.7.

| Size | Run | Complete | Partial/failed/skipped | Mean | Median | P95 | Min | Max | LLM | RAG | Static | Tokens in | Tokens out | Findings | Chunks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small | cold | 3/15 | 0/0/12 | 20.82 | 20.04 | 22.33 | 19.84 | 22.59 | 17.42 | 0.01 | 2.28 | 2238.00 | 909.00 | 10.67 | 1.00 |
| small | warm | 3/15 | 0/0/12 | 0.12 | 0.11 | 0.14 | 0.11 | 0.14 | 0.00 | 0.01 | 0.02 | - | - | 10.67 | 1.00 |
| medium | cold | 1/15 | 2/0/12 | 23.08 | 23.08 | 23.08 | 23.08 | 23.08 | 20.44 | 0.01 | 2.35 | 2689.00 | 192.00 | 2.00 | 1.00 |
| medium | warm | 1/15 | 1/0/13 | 0.09 | 0.09 | 0.09 | 0.09 | 0.09 | 0.00 | 0.01 | 0.02 | - | - | 2.00 | 1.00 |
| large | cold | 0/15 | 0/0/15 | - | - | - | - | - | - | - | - | - | - | - | - |
| large | warm | 0/15 | 0/0/15 | - | - | - | - | - | - | - | - | - | - | - | - |

Files (SHA-256 prefix in results):
- small: `decimal.py`, 11 lines, 0.32 KB
- small: `tty.py`, 36 lines, 0.89 KB
- small: `signal.py`, 92 lines, 2.47 KB
- medium: `bisect.py`, 110 lines, 3.17 KB
- medium: `shlex.py`, 350 lines, 13.53 KB
- medium: `aifc.py`, 984 lines, 34.37 KB
- large: `cgi.py`, 1012 lines, 34.6 KB
- large: `locale.py`, 1790 lines, 78.99 KB
- large: `turtle.py`, 4157 lines, 145.04 KB

Times are seconds. Statistics use complete runs only. P95 with few runs is close to the maximum. '-' means not measured.
