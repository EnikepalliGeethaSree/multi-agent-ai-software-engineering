# Execution-time analysis

How long the Code Review Agent takes, stage by stage, for files of different sizes.

## What every review records

Each review writes a `PerformanceRecord` (`core/performance.py`): `performance.json` next to its
reports, and on the job in the dashboard.

| Group | Fields |
|---|---|
| Identity | review id, file name, date, model, provider, run type (cold or warm), status |
| Size | file size (KB), lines of code, review units |
| Stages | ingestion, parsing, AST and call graph, static analysis, RAG index, RAG retrieval, prompt construction, LLM inference, evidence validation, dedup and severity, fix generation, classifier, report generation, total |
| LLM | input and output tokens, number of calls, failed calls, every call's duration and tokens, quota waiting |
| Outcome | findings, failed chunks, skipped chunks, chunks reused from cache, failed stages |

Times use `time.perf_counter()`, stored as spans in memory (one clock pair per stage), so measuring
adds almost nothing.

How the stages relate:

- The fine stages break the six evaluation components (D23) down further and do not add to them.
- Fix generation includes the LLM calls that wrote the fixes, so it overlaps LLM inference.
- Quota waiting is reported apart from LLM inference: it depends on the provider's limits, not on
  the pipeline.
- With concurrency above 1, summed stages can exceed the wall-clock total. Benchmarks use 1.

**Nothing is invented.** A value that was not measured stays null and shows as "Unavailable". A stage
that did not run is not 0 seconds. If the provider reports no token counts, tokens are unavailable,
not estimated. A stage that fails is still timed, and a review that crashes keeps what it measured.

## The file-size benchmark

```bash
python -m marl_agents.evaluation.benchmark_runtime --mode static_only --repeats 5   # no key needed
python -m marl_agents.evaluation.benchmark_runtime --config configs/gemini.yaml --repeats 5 --per-category 1 --max-llm-calls 65  # with Gemini, 20 requests a day
python -m marl_agents.evaluation.benchmark_runtime --resume experiments/results/<run>   # next day
```

| Category | Lines |
|---|---:|
| Small | 1-100 |
| Medium | 101-1,000 |
| Large | 1,001-5,000 |

**Inputs.** Three real Python files per category from the interpreter's standard library. A fixed rule
(evenly spaced by size within each category) picks them, and each is identified by SHA-256 in the
results, so the set is reproducible. They are parsed, never run. Use `--inputs <folder>` to supply
your own.

**Controlled variables.** Same machine, model, generation settings, RAG settings, static analysers and
chunking in every run; concurrency 1; fix suggestions off; files interleaved round by round so drift
hits all sizes alike; one untimed warm-up. Date, provider, model and API conditions are recorded.

**Cold and warm.** Each round runs a file twice. Cold starts from empty caches and a fresh vector store.
Warm follows immediately and may reuse them. They are reported separately.

**Failures.** Statistics use complete runs only. Partial, failed and skipped runs are counted in the
table and never enter a timing. Once the quota runs out, later LLM runs are recorded as skipped, not
as fast. `--max-llm-calls` stops early on purpose, and `--resume` continues from a saved run. A run
with the mock provider is flagged and must not be reported.

**Output.** `experiments/results/<stamp>_runtime_<mode>_r<rounds>/`: `results.csv` (one row per run),
`results.json`, `summary.csv`, `summary.md`, `metrics.json`, `meta.json`. The dashboard's Performance
page shows them.

**Reading P95.** With 15 runs per category, P95 is close to the maximum, and it is computed by linear
interpolation.

**Comparing runs.** Runs made under different API conditions (another day, model or free-tier load)
should not be compared without saying so. The recorded conditions exist for this reason.

## Results

See [results.md, section 8](results.md#8-execution-time-by-file-size).
