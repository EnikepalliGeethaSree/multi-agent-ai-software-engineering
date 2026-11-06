# Implementation report: Gemini, execution-time analysis and fine-tuning

Team 23UG082, Code Review Agent. Date: 6 November 2026.

This report covers three improvements requested by the project guide: replacing Groq with the free
Gemini tier, measuring execution time by file size, and fine-tuning for accuracy.

## Status at a glance

| Status | Meaning |
|---|---|
| **Tested** | Built, and exercised by automated tests or a real run |
| **Implemented, unproven** | Built and tested with stand-ins, but never run against the real thing |
| **Planned** | Not done |

| Item | Status | Evidence |
|---|---|---|
| Gemini provider code (retries, limits, quota handling) | Tested, live and with fakes | Live smoke test; the per-minute 429 path is still simulated |
| Live Gemini review | Tested on `gemini-3.6-flash` | Smoke test, plus real files in the benchmark |
| Default Gemini model `gemini-3.8-flash` | Google lists it as Stable; **failed live** | Listed for the key, but every generation request failed with Google's high-demand error |
| Execution-time recording | Tested | Every review writes `performance.json` |
| Static-only file-size benchmark | Tested | 90 of 90 runs complete; no LLM involved |
| Full Gemini file-size benchmark | **Preliminary only** | 11 of 90 runs measured before the daily quota ended; no large file measured |
| Dashboard Performance section | Tested | 53 frontend tests, real-server smoke test without an LLM |
| Classifier fine-tuning | Tested | Trained, then tested once on held-out repositories (split by project name where available) |
| Classifier inside a change review | Tested with the mock LLM | Real weights scored 15 units |
| Classifier savings in real LLM reviews | **Planned** (pending Gemini) | Runner built and dry-run with the mock LLM; no live run yet |
| Generative fine-tuning | **Not done** | Assessed and not recommended |
| Remaining four agents, LangGraph | **Planned** | Out of scope for this work |

## Main results

**Fine-tuning** (1,771 held-out Python changes, test set used once). Dev and test were split by project
name wherever the data has one. 3,383 training positives have no project name, so complete repository
separation cannot be guaranteed. Details are under [Fine-tuning results](#fine-tuning-results).

| Scorer | Precision | Recall | F1 | False positive rate | ROC-AUC (95% CI) |
|---|---:|---:|---:|---:|---:|
| Fine-tuned classifier | 0.707 | 0.672 | 0.689 | 0.345 | 0.723 (0.699-0.748) |
| TF-IDF + logistic regression | 0.678 | 0.494 | 0.572 | 0.290 | 0.645 (0.619-0.670) |
| Original static analysis | 0.674 | 0.184 | 0.289 | 0.110 | 0.541 |
| Change size alone | - | - | - | - | 0.635 |

Intervals are 95% percentile bootstrap intervals (300 resamples, seed 42). The fine-tuned model
predicts which changes draw a human comment better than every baseline. It has
more false alarms than static analysis. **This does not show that review comments improved.** The
classifier writes no comments, and its label is a proxy for "needs review".

**Execution time: static-only runs** (measured, no LLM, mean seconds):

| File size | Cold | Warm |
|---|---:|---:|
| Small (1-100 lines) | 2.42 | 0.07 |
| Medium (101-1,000) | 2.56 | 0.12 |
| Large (1,001-5,000) | 4.69 | 0.39 |

These exclude all LLM time, so they are **not** the time of a full review.

| Measurement | Status | LLM time included? |
|---|---|---|
| Static-only file-size benchmark | Measured | No |
| Full Gemini review by file size | **Preliminary: small and one medium file** | Yes |
| Earlier Groq timing | Historical | Yes, but another provider, so not an estimate for Gemini |

## Live Gemini validation (6 November 2026)

**Live integration works on `gemini-3.6-flash`. It has not been shown to work on `gemini-3.8-flash`.**
The full benchmark and the classifier ablation did not finish, because the free quota is 20 requests
per day per model.

**Model used:** `gemini-3.6-flash`, chosen explicitly after `gemini-3.8-flash` failed. It is listed by
Google as free and Stable. All Gemini numbers in this report come from it.

### Smoke test

Run `20261106T161948Z_gemini_smoke`, on one synthetic file written for the test.

| Check | Kind | Result |
|---|---|---|
| Missing key gives a clear error, no request | Local | Pass |
| Model listed for the key | Live | Pass |
| JSON reply parsed and validated by Pydantic | Live | Pass (20 + 5 tokens) |
| Full agent review | Live | Pass: 1 call, 0 failed units, 1 validated LLM finding |
| Invalid key | Live | Pass: rejected with 400, one attempt, key not in the message |
| Failed request does not crash a review | Live | Pass: failure recorded. The file has no static findings, so this run does not show them surviving; unit tests cover that |
| Timeout and retry | Live | Pass: 2 attempts, both classified as transient |
| Per-minute limit (429) | Simulated | Not provoked. Unit tests only |
| Daily quota stop | Simulated in the smoke test, **then seen live** | The benchmark hit the real limit, stopped at once and marked later runs as skipped |

Secrets: the saved runs were scanned and hold no key.

### What failed

- **`gemini-3.8-flash` generation.** Run `20261106T161252Z_gemini_smoke`. The model is listed for the key,
  but every generation request failed, in two attempts 30 minutes apart, after 6 tries each: *"This
  model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again
  later."* This is a capacity error, not a denial of access. No model was switched silently.
- **Replies cut off at 4,096 tokens.** On `shlex.py` and `aifc.py`, reasoning used most of the budget
  (about 93% on `shlex.py`), and output plus reasoning reached 4,091-4,092 tokens per successful call.
  Replies stopped mid-JSON, so all 3 units of `shlex.py` failed. `llm.max_tokens` is now 16,384. **This
  fix has not been tested live**, because the quota had run out.
- **Benchmark and ablation incomplete.** See below.

### Actual API use and timing

Run `20261106T162014Z_runtime_full_r5`, `gemini-3.6-flash`, RAG on, public standard-library files. The
limit was `llm.max_tokens = 4096`, so **treat these as preliminary**. They are not the final benchmark.

| Measure | Value |
|---|---:|
| Runs planned / measured / skipped | 90 / 11 / 79 |
| Complete / partial | 8 / 3 |
| LLM calls, including 6 failed | 19 |
| Tokens: input / output / reasoning | 54,615 / 4,919 / 43,796 |

| Size | Run | Complete runs | Total (s) | LLM (s) | RAG (s) | Static (s) | Cache hit rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Small | Cold | 3 | 20.82 | 17.42 | 0.01 | 2.28 | 0% |
| Small | Warm | 3 | 0.12 | 0.00 | 0.01 | 0.02 | 100% |
| Medium | Cold | 1 | 23.08 | 20.44 | 0.01 | 2.35 | 0% |
| Medium | Warm | 1 | 0.09 | 0.00 | 0.01 | 0.02 | 100% |
| Large | Cold and warm | 0 | Not measured | - | - | - | - |

These are means over one round, so each small row covers three different files and each medium row
covers only `bisect.py`. `shlex.py` was partial and its warm run had a 0% hit rate, because failed units
are not cached. Five rounds were not reached.

### Classifier ablation

**No live result exists.** The runner is built and tested. A dry run on 6 real dev samples, with real
weights and the mock LLM, finished all three modes. Its numbers test the wiring only and are not results.
It reads `dev.jsonl` only, and the classifier test set still has exactly one run.

**Risks of gate mode**, which the run is designed to measure:

- It can skip a change a human would comment on. On the held-out test, 32.8% of commented changes scored
  below the threshold.
- An LLM-only finding in a skipped unit is simply never found. No static check can bring it back.
- Critical, high and high-confidence static findings are protected. The ablation counts any such finding
  lost in a skipped unit, and that count must be 0.
- Dev chose the threshold, so dev results will flatter the classifier.

## What already existed

The Code Review Agent was complete before this work: ingestion, AST parsing and call graph, static
analysis, ChromaDB retrieval, LLM review, evidence validation, deduplication, severity rubric, reports,
change review, FastAPI and React dashboard, and the evaluation framework with ablations A-D. All of it
was kept. Static analysis, ChromaDB and evidence validation were not removed or weakened.

## What changed

**Gemini.** Default provider is now Gemini, with Groq kept as an option. The provider classifies
failures (rate limit, daily quota, too large, fatal, transient), honours the server's retry delay and
stops cleanly when the daily quota ends. A stopped review keeps its work and can be resumed the next
day.

**Execution time.** Every review records each stage, plus tokens and every LLM call. A value that was
not measured stays empty and shows as "Unavailable", never as 0.

**Reduced LLM use.** Identical units are reviewed once, finished units are cached so a resume does not
repeat them, and static results are cached for unchanged code.

**Classifier.** A new configuration E adds the classifier. It orders LLM work or, in gate mode, skips
low-scoring units. It can never remove a finding or gate a unit with a critical, high or
high-confidence static finding.

**Dashboard.** New Performance page, a before/after table, a Resume review button, and new API routes:
`/api/performance/reviews`, `/api/performance/reviews/{id}`, `/api/performance/benchmarks`,
`/api/performance/benchmarks/{name}`, `/api/evaluation/before-after`, `/api/reviews/{id}/units` and
`POST /api/reviews/{id}/resume`.

### Problems found and fixed along the way

| Problem | Effect if left | Fix |
|---|---|---|
| `lang == "py"` selects negatives only | No usable Python positives; "39,630 examples" were all label 0 | Python recognised from content |
| Metadata presence reveals the label | Falsely high scores | Metadata never reaches the model |
| Validation and test share projects and patches | Tuning would reach into test | Split by project name where available; held-out test is primary |
| Train positives are unrealistically large | Model learns size, fails on real data | Size matching, project caps, same-source data |
| Best-F1 threshold chose 0.05 | Flags almost everything | Balanced accuracy on dev |
| Gating used 0.5, not the tested 0.44 | Gate would run at an untested point | Gating now uses the model's own threshold |
| Evaluation saved no per-sample scores | Numbers could not be traced | Scores and weights' hash are now saved |
| Classifier commands pointed at the test split | A second look at held-out data | New dev-only `eval classifier-ablation` |
| ChromaDB 1.5.9 read failure across saved collections | Reviews after the first in one process crashed, which affects the dashboard | Store reopens its client once and retries; 8 of 8 reviews then passed |
| `llm.max_tokens` 4096 too small for reasoning | Replies cut off, units failed | Raised to 16,384; not yet tested live |
| Partial runs did not say why | Causes were invisible | Failure reason and reasoning tokens are saved |

## Files changed

**New, backend:** `llm/gemini.py` (rewritten), `llm/classifier.py`, `core/performance.py`,
`agents/code_review/scheduling.py`, `static_analysis/cache.py`, `evaluation/benchmark_runtime.py`,
`evaluation/gemini_smoke.py`, `evaluation/runners/classifier_eval.py`,
`evaluation/runners/classifier_ablation.py`, `evaluation/comparison/before_after.py`, `training/` (`data.py`,
`prepare.py`, `train.py`, `baseline.py`), `api/performance.py`.

**New, other:** `configs/gemini.yaml`, four scripts in `scripts/`, `frontend/src/pages/Performance.tsx`,
`frontend/src/components/PerformancePanels.tsx`, `frontend/src/components/ScatterChart.tsx`, new tests,
and `docs/llm-gemini.md`, `docs/performance.md`, `docs/fine-tuning.md`, this report.

**Modified, backend:** `llm/base.py`, `llm/rate_limit.py`, `llm/factory.py`, `config.py`, `core/timing.py`,
`parsing/repo_index.py`, `rag/retriever.py`, `rag/store.py`, `agents/code_review/agent.py`, `agents/code_review/context.py`,
`reports/renderers.py`, `api/jobs.py`, `api/app.py`, `cli.py`, and the evaluation configuration, runner and
comparison modules.

**Modified, other:** `configs/default.yaml`, `.env.example`, `pyproject.toml`, `.gitignore`, the dashboard
pages, API client and types, and the project docs (D27-D29 in `docs/decisions.md`, `docs/results.md` sections
8 and 9).

All paths are under `src/marl_agents/` unless a top-level folder is shown. **Nothing is committed**, so run
records show `git_commit: uncommitted`.

## New dependencies

| Package | Why | Group |
|---|---|---|
| `google-genai` | Gemini SDK | `llm` extra |
| `tzdata` (Windows only) | Daily quotas reset at midnight Pacific | Core |
| `torch`, `transformers`, `peft`, `accelerate`, `scikit-learn` | Fine-tuning and inference | New `train` extra |

No paid API or paid hosting was added. Cerebras is not used.

## Test results

| Check | Result |
|---|---|
| Backend tests (`pytest`) | 531 passed, 2 deselected (tests that call a real API or need the datasets) |
| Frontend tests (`npm test`) | 53 passed |
| Types (`mypy src`) | Clean |
| Lint and format (`ruff`) | Clean |
| Frontend build | Succeeded |

These offline tests do not call Gemini. Live results are under
[Live Gemini validation](#live-gemini-validation-6-november-2026).

## Benchmark results

**Static-only, measured.** Run `20261106T122017Z_runtime_static_only_r5`: nine real standard-library files, 5 rounds, 90 of 90 runs
complete. Static analysis takes over 90% of cold time. Time grows slowly with size: large files have
about 50 times the lines of small ones and take about twice as long. Reusing cached results cuts repeat
runs by 92-97%, for unchanged code only. Details: [results.md, section 8](results.md#8-execution-time-by-file-size).

**Full Gemini review, preliminary.** Only small files and `bisect.py` completed, under the old token
limit. Large files are unmeasured, and no static-only figure is an estimate of them.

## Fine-tuning results

Run `20261106T144800Z_classifier_cls_test_n1771`. Partial fine-tuning of CodeBERT on CPU, with 16,000
training changes (7,299 Python, 8,701 from other languages). It stopped at 1.15 of 2 epochs on its time
budget. The 110-minute budget covers the training loop. The final dev check and save took about 5 more
minutes, which gives the reported 115.1. Dev AUC 0.712, test AUC 0.723, threshold 0.44 from dev.

Confusion matrix: 658 true positives, 273 false positives, 519 true negatives, 321 false negatives.
Accuracy 0.665 against 0.553 for the majority class.

| Check | Result |
|---|---|
| Learned more than size? | Yes: AUC 0.693 within size bands, where size alone gives about 0.50-0.57 |
| Beats size per project? | 11 of 12 projects; lowest AUC 0.457 (n = 42) |
| Ranking | 93.8% of its top 10% drew a comment, against a base rate of 55.3% |
| Metrics reproduced? | Yes: recomputed with scikit-learn from saved predictions, exact match |

The size and project checks ran after the test and are descriptive. Full method:
[fine-tuning.md](fine-tuning.md).

**Separation of the sets** (`separation_audit.json` in the run; compares names and patches, scores
nothing):

- Dev and the held-out test share 0 projects and 0 patches.
- The 8,701 non-Python records come from `valid`, the same raw file as dev. None is in a dev or
  held-out test project, and none shares a patch with dev, the held-out test or the official test.
- The 3,916 named Python training negatives include none from dev or held-out test projects.
- The 3,383 Python training positives have no project name, so their project cannot be checked.
  None shares a patch with dev or the held-out test.
- The official test set is secondary: 14 of its 29 projects are dev projects, and 3 Python training
  negatives share a patch with it.

## Before and after

| Comparison | Status |
|---|---|
| Needs-review classification, original vs classifier | Measured: table above |
| Precision, recall and false positives on planted issues, Gemini | Pending Gemini (N/A) |
| Comment coverage, BLEU-4, ROUGE-L, chrF, Gemini | Pending Gemini (N/A) |
| Average LLM calls, tokens and time, with vs without classifier | Pending Gemini (N/A) |

| System configuration | Status on Gemini |
|---|---|
| Single LLM baseline | Pending |
| Existing agent | Pending |
| Improved with classifier | Pending |
| Improved with RAG + Gemini | Pending |

These are shown as N/A rather than filled in. Earlier Groq runs are historical, and
[results.md, section 10](results.md#10-pending-gemini-experiments) lists the pending runs. `python -m
marl_agents.cli eval before-after` prints the command for each missing row.

## Known limitations

- **The free tier is very small.** Google's 429 gave 20 requests per day, per project, per model, for
  `gemini-3.6-flash`. Other models may differ. It is not guaranteed, and it is not unlimited.
- **Free-tier content may be used by Google,** so do not send confidential code.
- **`gemini-3.8-flash` has never answered here.** Google's model page lists it as Stable, its changelog
  records general availability on 2 September 2026, and its pricing page shows a free tier. Every
  generation request failed with a high-demand error on 6 November 2026, so no result applies to it.
  It is still the configured default, so set `GEMINI_MODEL` until it responds.
- **The token-limit fix is not tested live,** and neither is the ChromaDB fix with a real LLM.
- **The classifier label is a proxy,** and the result is Python only, from one seed and one split.
- **Repository separation is not complete proof.** It applies wherever project names exist, and 3,383
  training positives have none. Forks and renamed repositories would also go unnoticed.
- **The intervals assume independent changes,** so they may be too narrow.
- **Training was cut short** at 1.15 epochs and 128 tokens.
- **Gate mode can miss work:** 32.8% of commented changes scored below the threshold. Protection may
  also limit savings. `prioritize` is the safer default.
- **Gemini timing is preliminary:** one round, no large files, and the old token limit.
- **Code is uncommitted,** so no run can be traced to a commit.

## Remaining work

**Limit to plan around:** 20 generate requests per day, per project, per model. It resets at midnight
Pacific, which is 13:30 in India. Do not use extra accounts or keys to get around it.

Add these to `.env`:

```
LLM_PROVIDER=gemini
GEMINI_MODEL=gemini-3.6-flash
```

**1. Rerun the file-size benchmark with the new token limit** (one file per size, about 13 requests per
round by unit count):

```bash
python -m marl_agents.evaluation.benchmark_runtime --config configs/gemini.yaml --repeats 5 --per-category 1 --max-llm-calls 65
```

Continue on later days by adding `--resume experiments/results/<run>`. The first day also shows whether
16,384 tokens stopped the cut-off replies. Replace today's preliminary table with the result.

**2. Run the classifier ablation** on development samples:

```bash
python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml
```

Continue with `--resume experiments/results/<run>`. Together these need about 110 requests, so at least
six days. That is a plan, not a measurement: retries and larger units can raise it.

**3. Other work:**

- Retry `gemini-3.8-flash` with `python -m marl_agents.cli check --config configs/gemini.yaml` when
  demand falls, using `GEMINI_MODEL=gemini-3.8-flash`. Results from different models must not be mixed.
- Run the Gemini versions of the planted and comment benchmarks (`docs/results.md`, section 10).
- Run `pytest -m llm tests/integration/test_gemini_live.py`. It was not run, because the quota was spent.
- Complete the human rating kit.
- Commit the code. Runs still show `git_commit: uncommitted`.

**Not started, by design:** the Bug Detection, Security, Test Generation and Documentation agents, and
LangGraph orchestration.
