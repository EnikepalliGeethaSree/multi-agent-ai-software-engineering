# Review time by file size

LLM: none (static analysis only). Mode: static_only, RAG off. 5 rounds per file, concurrency 1, fixes off. Date 2026-11-06. API conditions: no API used.
Hardware: Windows-10-10.0.26300-SP0, 12 CPUs, Python 3.11.7.

No LLM was used, so these times exclude LLM inference and token use.

| Size | Run | Complete | Partial/failed/skipped | Mean | Median | P95 | Min | Max | LLM | RAG | Static | Tokens in | Tokens out | Findings | Chunks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| small | cold | 15/15 | 0/0/0 | 2.42 | 2.39 | 2.56 | 2.32 | 2.75 | - | - | 2.35 | - | - | 11.67 | - |
| small | warm | 15/15 | 0/0/0 | 0.07 | 0.06 | 0.10 | 0.04 | 0.11 | - | - | 0.02 | - | - | 11.67 | - |
| medium | cold | 15/15 | 0/0/0 | 2.56 | 2.46 | 2.87 | 2.29 | 2.97 | - | - | 2.45 | - | - | 16.00 | - |
| medium | warm | 15/15 | 0/0/0 | 0.12 | 0.07 | 0.25 | 0.03 | 0.27 | - | - | 0.03 | - | - | 16.00 | - |
| large | cold | 15/15 | 0/0/0 | 4.69 | 4.83 | 6.37 | 2.91 | 6.39 | - | - | 4.35 | - | - | 64.67 | - |
| large | warm | 15/15 | 0/0/0 | 0.39 | 0.19 | 0.80 | 0.15 | 0.81 | - | - | 0.07 | - | - | 64.67 | - |

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
