# Efficiency: time per review and per component

Repeats: 3 per input and configuration (median, min-max shown, seconds). LLM: groq / openai/gpt-oss-120b. Concurrency 1; vector store chroma (fresh per run); suggested fixes off; one untimed static-only run per input; order interleaved: round -> input -> configuration.
Hardware: Windows-10-10.0.26200-SP0, AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD, 12 CPUs, Python 3.11.7.

## planted_repo

8 files (6 Python), 146 lines reviewed.

| Component | static_only | llm_rag | llm_no_rag |
|---|---:|---:|---:|
| Static analysis | 5.99 (5.14-6.35) | 5.53 (4.84-5.64) | 5.02 (4.72-5.42) |
| RAG (index + retrieval) | 0.00 (0.00-0.00) | 0.31 (0.22-0.34) | 0.00 (0.00-0.00) |
| LLM inference | 0.00 (0.00-0.00) | 18.53 (17.86-25.56) | 18.50 (15.00-19.77) |
| Validation | 0.00 (0.00-0.00) | 0.01 (0.01-0.01) | 0.00 (0.00-0.00) |
| Report generation | 0.10 (0.08-0.14) | 0.11 (0.11-0.13) | 0.11 (0.11-0.13) |
| Other / orchestration | 0.02 (0.02-0.02) | 204.53 (163.99-274.76) | 164.80 (161.84-166.01) |
|   of which: LLM quota waiting | - | 204.44 (163.78-267.92) | 161.83 (160.05-164.78) |
| **Total** | 6.10 (5.24-6.51) | 228.34 (188.64-305.49) | 186.75 (186.56-188.12) |
| Complete runs | 3/3 | 3/3 | 3/3 |
| LLM review units | 0 | 4 | 4 |
| LLM calls (incl. JSON retries) | 0.00 (0.00-0.00) | 4.00 (4.00-5.00) | 4.00 (4.00-4.00) |

Static analysis by tool (median s): ast 0.01 (0.01-0.01), mypy 5.91 (5.04-6.27), radon 0.01 (0.01-0.01), ruff 0.06 (0.06-0.08), secrets 0.00 (0.00-0.00), test_gap 0.00 (0.00-0.00)

RAG latency overhead: -0.3% (24.92s -> 24.86s; median active time (total minus LLM quota waiting), same input and model).
RAG's own cost (index + queries): 0.31s, 1.3% of active time with RAG. Median JSON retries: 0.0 without RAG, 0.0 with RAG; a retry repeats the LLM call, so differing retries, not retrieval, can dominate a small-n comparison.

## order_service_file

1 files (1 Python), 114 lines reviewed.

| Component | static_only | llm_rag | llm_no_rag |
|---|---:|---:|---:|
| Static analysis | 5.43 (5.31-6.21) | 5.22 (5.22-5.87) | 5.37 (5.11-5.63) |
| RAG (index + retrieval) | 0.00 (0.00-0.00) | 0.16 (0.16-0.23) | 0.00 (0.00-0.00) |
| LLM inference | 0.00 (0.00-0.00) | 9.89 (4.85-12.14) | 5.92 (5.92-5.93) |
| Validation | 0.00 (0.00-0.00) | 0.00 (0.00-0.01) | 0.00 (0.00-0.00) |
| Report generation | 0.05 (0.05-0.07) | 0.06 (0.06-0.10) | 0.06 (0.06-0.06) |
| Other / orchestration | 0.01 (0.01-0.01) | 105.25 (0.07-119.35) | 49.29 (48.61-49.98) |
|   of which: LLM quota waiting | - | 99.48 (0.00-113.45) | 49.28 (48.59-49.97) |
| **Total** | 5.49 (5.37-6.29) | 121.35 (10.36-136.93) | 60.65 (60.22-61.08) |
| Complete runs | 3/3 | 3/3 | 2/3 |
| LLM review units | 0 | 1 | 1 |
| LLM calls (incl. JSON retries) | 0.00 (0.00-0.00) | 2.00 (1.00-2.00) | 1.00 (1.00-1.00) |

Static analysis by tool (median s): ast 0.00 (0.00-0.01), mypy 5.36 (5.24-6.13), radon 0.01 (0.01-0.01), ruff 0.05 (0.05-0.06), secrets 0.00 (0.00-0.00), test_gap 0.00 (0.00-0.00)

RAG latency overhead: +92.4% (11.37s -> 21.87s; median active time (total minus LLM quota waiting), same input and model).
RAG's own cost (index + queries): 0.16s, 0.7% of active time with RAG. Median JSON retries: 0.0 without RAG, 1.0 with RAG; a retry repeats the LLM call, so differing retries, not retrieval, can dominate a small-n comparison.

Components are sums of measured spans; 'Other' = total - components (ingestion and parsing, context assembly, waiting for the LLM quota, scheduling).
