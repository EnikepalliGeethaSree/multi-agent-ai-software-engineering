# Code Review Agent: evaluation framework

## Evaluation methodology

**Scope.** This is an **agent-level benchmark evaluation of the Code Review Agent on its own**.
It is not the system-level evaluation of the five-agent platform: that one is the SWE-bench Lite
resolve rate, and the platform is not built yet. Nothing here claims that the complete multi-agent
system works. The question is narrower: what does each component of *this* agent contribute?

### Configurations (ablation)

Each configuration switches one component of the agent on or off. Everything else (model,
temperature, seed, prompts, confidence threshold, analyzers, samples) stays identical. Code:
`evaluation/configurations.py`.

| | Configuration | Static | LLM | RAG | Settings |
|---|---|:-:|:-:|:-:|---|
| A | Static Only | ✓ | ✗ | ✗ | `review.mode=static_only` |
| B | LLM Only | ✗ | ✓ | ✗ | `review.mode=llm_only`, `rag.enabled=false` |
| C | Static + LLM | ✓ | ✓ | ✗ | `review.mode=full`, `rag.enabled=false` |
| D | Static + LLM + RAG | ✓ | ✓ | ✓ | `review.mode=full`, `rag.enabled=true` (the shipped agent) |

- **What "RAG" covers.** It is the agent's whole project-context layer: retrieved similar code,
  retrieved coding guidelines and call-graph neighbours. With RAG off, no retriever and no context
  builder are created, and the prompt contains only the code under review (plus, in C, the static
  findings the LLM is asked to triage).
- **How the configurations are verified.** Tests check this from the saved spans (`tests/unit/evaluation/test_configurations.py`):
  - A makes no LLM call and no retrieval;
  - B runs no static analyzer and no retrieval;
  - C makes no retrieval, and its prompts contain no retrieved context;
  - D retrieves (more than zero RAG queries, context in the prompt).
- **How runs are classified.** A run's configuration comes from its *effective* settings
  (`meta.json["experiment"]`, else `config.yaml`), never from its folder name. Runs saved before
  this framework are therefore classified exactly. `--mode llm_only` with RAG left on is labelled
  "LLM + RAG (no static)", not B.

### Baselines and fairness

| Benchmark | Proposed | Baselines |
|---|---|---|
| Planted issues, CodeReviewer | D | A, B, C (ablations) |
| RAG retrieval | embedding retrieval | random ranking (seed 42) |
| Risk ranking | risk model v2 | random (exact expectation), size only, finding score only, risk v1 |
| Efficiency | per-component time | A vs B vs C vs D on the same input; RAG overhead = C vs D |

- **One command per comparison.** `eval ablation` runs every configuration on identical inputs:
  CodeReviewer samples are loaded once, repeats are interleaved (repeat → configuration), and the
  same provider object is shared. Each configuration is saved as an ordinary run with a shared
  `group_id`, and a comparison record is saved for the group.
- **Paired scoring.** CodeReviewer rows are scored on the **same samples**. If any configuration's
  LLM failed on a sample (D22), that sample is removed from every row, and the table shows the
  common n and each configuration's failures. A static-only run on the full test split may be
  restricted to the LLM runs' samples, because static analysis is deterministic. Its full-split
  numbers are reported separately.
- **Fairness checks.** Every table lists them as ✓ (met), ✗ (not met) or ? (not recorded):
  - same samples;
  - same model, temperature and prompt versions;
  - same confidence threshold and evaluation rules;
  - whether the rows were run together in one group.
- **Never shown as results:** runs with the offline mock LLM (pipeline tests) and planted runs
  where an LLM unit failed (incomplete).
- **Missing configurations** appear as **N/A**, together with the command that produces them.
  Undefined ratios (for example precision with no predictions) are also N/A, never 0 or 1.

### Metrics

Kept deliberately small. Definitions are shown on the dashboard and in the generated summary.

| Metric | Definition | Scale | Used for |
|---|---|---|---|
| Precision | TP / (TP + FP) | 0-1 | planted, CodeReviewer cls |
| Recall | TP / (TP + FN) | 0-1 | planted, CodeReviewer cls |
| F1 | 2·P·R / (P + R) | 0-1 | planted, CodeReviewer cls |
| ROC-AUC | P(score of a random positive > score of a random negative); 0.5 = chance | 0-1 | CodeReviewer cls, risk ranking |
| BLEU-4, ROUGE-L, chrF | similarity of the agent's comment to the human comment, averaged over samples, **×100** | 0-100 | comment generation |
| Coverage | share of diffs with an agent comment | 0-1 | comment generation |
| Recall@10, MRR | retrieval of call-graph-relevant chunks | 0-1 | RAG |
| Precision@Top10% | share of commented hunks among the 10% ranked riskiest | 0-1 | risk ranking |

- **Planted ROC-AUC is N/A.** The suite labels positives only; there are no scored negative cases,
  so no ROC curve exists.
- **Planted TP has two meanings.** For precision, TP counts the defect findings that match a
  planted issue. For recall, TP counts the planted issues detected. These are the project's
  existing definitions.
- **CodeReviewer cls is reported RAW and ADJUSTED.** Adjusted drops the five rules that cannot be
  judged from one hunk.
- **Scales checked (2026-10-12).** BLEU-4, ROUGE-L and chrF are intentionally ×100, following the
  CodeReviewer reporting convention, and are consistent with each other. Coverage is a 0-1 share.
  No scaling bug was found, so nothing was changed.

### Timing

- **Clock.** `time.perf_counter()` spans record total, static, RAG, LLM, validation, report
  generation and other time (section 5).
- **Reported configurations.** `eval timing` now covers all four configurations: `static_only`,
  `llm_only`, `llm_no_rag` (C) and `llm_rag` (D). It reports the median, with mean, min and max
  stored.
- **Active time** is total minus LLM quota waiting. It is defined only at concurrency 1, because
  waits are summed over parallel workers. Otherwise it is N/A, never negative.
- **RAG overhead** = (T_D − T_C) / T_C × 100 on median active time. It is computed only for runs
  of the same input, model and run group; otherwise it is N/A.

### Limitations

1. The planted suite is small (17 issues) and has only **one** issue that needs semantic
   reasoning. Its LLM-only recall can only be 0 or 1 per run, and a single run is not evidence
   either way.
2. LLM CodeReviewer runs are limited to about 40 samples per day by the Groq free-tier quota.
   Differences of a few points at n ≈ 40 are within sampling noise.
3. In CodeReviewer each sample is one file, so RAG can retrieve only other parts of that file and
   the guidelines. CodeReviewer C vs D therefore under-tests project context. The planted
   repository (8 files) tests it better.
4. Even at temperature 0, hosted LLM output varies between runs. Use `--repeats` (mean ± SD) for
   claims about the LLM.
5. The usefulness judge is **supplementary**: one judge model, a small sample, and agent comments
   that are longer than human ones (judges tend to reward length). Judge-human agreement has not
   been measured yet.
6. The retrieval benchmark is built from this project's own `src/`, so its query set changes as
   the code grows. On 2026-10-12 it had 316 queries in the morning run and 381 after the
   comparison modules were added. Compare Recall@10 only within one run, RAG vs random, never
   across dates.

### Ablation results (2026-10-12)

Model: Groq `openai/gpt-oss-120b`, temperature 0, seed 42. Generated by `eval summary`; source runs
are listed in `experiments/evaluation_summary/comparison.md`.

**Planted issues.** One ablation group, `abl-20261012T161020Z`: one run per configuration,
concurrency 1, fix suggestions off. All fairness checks pass.

| Configuration | Precision | Recall | F1 | Semantic issue (P13) | Active time |
|---|---:|---:|---:|:-:|---:|
| A Static Only | 1.000 | 0.941 | 0.970 | missed | 5.62 s |
| B LLM Only | 1.000 | 0.588 | 0.741 | found | 16.00 s |
| C Static + LLM | 1.000 | 1.000 | 1.000 | found | 22.69 s |
| D Static + LLM + RAG | 1.000 | 1.000 | 1.000 | found | 26.53 s |

How to read it:
- **Static analysis and the LLM are complementary.** Static analysis finds 16 of 17 issues but not
  the semantic one. The LLM alone finds the semantic one but only 10 of 17. Together (C) they find
  all 17, with no false positives.
- **RAG adds no detection gain on this suite.** C and D are identical. Its active-time overhead is
  +16.9% in this single run. Retrieval itself took 0.18 s; the remaining difference is longer
  LLM inference (19.52 s vs 16.80 s) from prompts that carry the retrieved context.
- **These are single runs**, and the semantic recall rests on one issue. Repeat the comparison
  (`--repeats 3`) before claiming more.

**CodeReviewer classification** (group `abl-20261012T161828Z`, n = 10 requested): **not a
result.** The Groq daily quota ran out during the run:
- C evaluated 3 of 10 samples (7 failed with HTTP 429);
- D evaluated 0 of 10.

The paired table therefore has n = 3. The summary marks it as a pipeline check only, and the
master table withholds it (minimum n = 30). For a real comparison, run the 40-sample command
below on a fresh quota.

```bash
python -m marl_agents.cli eval ablation --benchmark planted --config configs/gemini.yaml          # A-D
python -m marl_agents.cli eval ablation --benchmark codereviewer --task cls --limit 40 --seed 42 --config configs/gemini.yaml
python -m marl_agents.cli eval summary    # master comparison table + per-benchmark sections
```

---

**Research question.** How accurately can the Code Review Agent detect and prioritise
review-worthy issues? How well does RAG retrieve relevant context? What computational cost does
the complete review pipeline introduce?

The evaluation has **five components**. Each metric is there for a reason, and every number comes
from a saved run in `experiments/results/<run>/`. Each run folder holds the config, git commit,
model, prompt versions, sample IDs, raw predictions and metrics. If a configuration was never run,
the summary says **"not run"** and gives the command to run it. It never estimates a value.

| # | Component | Data | Metrics | Question it answers |
|---|---|---|---|---|
| 1 | Detection quality | planted-issue suite (17 labelled issues) | precision, recall, F1 (TP/FP/FN) | Does it find known problems without false alarms? |
| 2 | CodeReviewer benchmark | CodeReviewer test split, Python | precision, AUC (cls); coverage, chrF (msg) | Does it agree with real human reviewers? |
| 3 | RAG retrieval | call-graph relevance on our own `src/` | Recall@10 vs random | Does RAG fetch the relevant project context? |
| 4 | Risk ranking | CodeReviewer cls hunks, test split | Precision@top 10% (+ AUC) | Does "review these hunks first" put the right hunks first? |
| 5 | Efficiency | timing benchmark (fixed inputs, repeated runs) | total, static, RAG, LLM, validation, report time | What does a review cost in time, and where does the time go? |

Generate the tables at any time:

```bash
python -m marl_agents.cli eval summary   # -> experiments/evaluation_summary/{summary.md, records.json}
```

---

## 1. Detection quality (planted issues)

**Data.**
- `tests/fixtures/repos/planted/` contains 17 hand-placed issues: SQL injection, hard-coded
  secrets, swallowed exceptions, mutable defaults, a division by zero, and others.
- The answer key is `planted_expected.json`. It also lists a clean file used as a negative control.

**Matching.** A finding matches a planted issue when all three hold:
- it is in the same file;
- it starts within ±2 lines of the issue;
- its category is compatible with the issue's.

**Definitions** (code: `evaluation/metrics/detection.py`):

| Quantity | Definition |
|---|---|
| TP | defect findings (bug, security, error handling, edge case) that match a planted issue |
| FP | defect findings that match no planted issue |
| FN | planted issues that no finding matched |
| Precision | TP / (TP + FP) |
| Recall | planted issues detected / all planted issues |
| F1 | 2 · P · R / (P + R) |

**Why precision counts only defect findings.** The answer key lists defects. Findings such as
"missing docstring" are often correct but are not in the key. Counting them as false positives
would punish correct output, so they are left out of precision in both directions. This is the
project's existing definition (`defect_precision`), kept unchanged.

```bash
python -m marl_agents.cli eval planted --mode static_only
python -m marl_agents.cli eval planted --mode full          # static + LLM (uses GROQ_API_KEY)
```

## 2. CodeReviewer benchmark (primary benchmark)

**Data.** CodeReviewer (Li et al., ESEC/FSE 2022), test split, Python only. The dataset is used
**only for evaluation**: nothing is trained on it, and its labels and comments never enter the RAG
index.

**Task `cls`: does this hunk need a review comment?** Each sample is one changed hunk.
Label `y = 1` means a human reviewer commented on it.
- **Precision:** the agent "flags" a hunk when it raises at least one finding of severity low or
  above. Precision is the share of flagged hunks that humans actually commented on.
- **AUC:** ROC-AUC of the agent's per-hunk score against the human label. The score is the best
  finding's priority, from 0 to 1. AUC measures ranking ability across all thresholds; 0.5 is
  chance.
- **Sensitivity analysis (existing, always shown alongside).** A sample is one hunk applied to the
  old file, so imports and names added in the commit's *other* hunks are missing. The rules F401,
  F403, F405, F811 and F821 then misfire on correct code. Precision and AUC are therefore also
  reported with those rules excluded.

**Task `msg`: write the review comment.** Each sample is a diff with the human reviewer's comment.
- **Coverage** (the project's existing definition): the share of diffs for which the agent
  produced a review comment. If the agent finds nothing in scope, the comment is empty. This
  measures how often the agent has something to say about a change.
- **chrF:** the character n-gram F-score (×100) between the agent's comment (title plus suggested
  fix) and the human comment. Character-level matching is more forgiving of wording differences
  than BLEU.
- BLEU-4 is still computed and stored in `metrics.json`, because the approved deck lists it.
  The headline table uses coverage and chrF.

```bash
python -m marl_agents.cli eval codereviewer --task cls --mode static_only                # full test set
python -m marl_agents.cli eval codereviewer --task msg --mode static_only
python -m marl_agents.cli eval codereviewer --task cls --limit 40 --seed 42 --mode full --workers 1
python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --mode full --workers 1
```

LLM runs use random subsets because Groq's free tier allows about 200k tokens per day per model,
which is roughly 40-45 reviewed samples. Every number states its n. Samples where the LLM failed
(quota or size) are counted as failures, never scored as static-only.

## 3. RAG retrieval

**Question.** Does retrieval find the project context a reviewer would need?

**Benchmark** (`eval retrieval`): self-supervised from the AST call graph of our own `src/`.
- For each function, the *relevant* chunks are those containing the functions it calls.
- The query is the function's own chunk.

**Recall@10:** the share of a function's relevant chunks that appear in the top 10 retrieved. It is
averaged over queries. We report the system's embedder (`hashing`, the default) against a random
ranking. Retrieval is measured separately from the LLM's final quality.

```bash
python -m marl_agents.cli eval retrieval --path src
```

## 4. Risk ranking ("review these hunks first")

**Question.** If a reviewer reads the hunks in the order the agent ranks them, do the ones that
deserve comments come first?

**Precision@top 10%:** of the 10% of hunks the scorer ranks riskiest, the share a human commented on.
The existing AUC is reported too. Four scorers are evaluated on the same 4,195 test hunks:

| Scorer | What it is |
|---|---|
| Risk v2 (calibrated) | the shipped model; 4 weights fitted on the **validation** split, test used once |
| Risk v1 (hand-set) | the original additive points, frozen as a baseline (`evaluation/runners/risk_v1.py`) |
| Size only | number of changed lines (a no-analysis baseline) |
| Random (expected) | the expected value of a random order: precision = base rate, AUC = 0.5 |

```bash
python -m marl_agents.cli eval hunkrisk --split test
```

---

## 5. Efficiency (time analysis)

### What is measured

| Component | Exactly what is timed |
|---|---|
| **Total review time** | from the start of the review request to the final result, **including writing the reports** when reports are produced |
| Static analysis | each analyser's `analyze()` call: Ruff, Radon, AST checks, secrets, test gaps, mypy (reported per tool and summed) |
| RAG retrieval | **index:** chunking, embedding and vector-store insert. **Queries:** query embedding and vector search, for both similar code and guidelines, every unit. Reported as index + queries. |
| LLM inference | from sending each request to receiving the response, summed over calls. Measured inside the provider *after* the rate limiter, so waiting for quota is **not** inference. |
| Validation | JSON/Pydantic schema parsing of LLM replies, evidence validation, actionability filter, deduplication, severity rubric, confidence and ranking |
| Report generation | writing JSON, Markdown, PDF and SARIF |
| Other / orchestration | total − sum of the above: ingestion and parsing, context assembly, waiting for the LLM quota, scheduling. **Not forced to zero.** |
| of which: LLM quota waiting | time the client waited for the provider's rate limit (free-tier Groq), summed over concurrent workers, so it can exceed the elapsed time when concurrency > 1 (the timing benchmark uses concurrency 1) |

### How it is measured
- **Clock:** `time.perf_counter()` (monotonic), never wall-clock timestamps. Every measurement is a
  span with start, end and duration in seconds (`core/timing.py`).
- **Overhead:** spans are appended to an in-memory list under a lock. There is no logging, no disk
  write and no extra LLM call or embedding in the critical path.
- **Integration test:** a review with instrumentation and one with a no-op timer produce identical
  findings (`tests/integration/test_timing_instrumentation.py`).
- **Where breakdowns appear:** every review stores its breakdown in `result.stats["timing"]`
  (shown on the dashboard and printed by the CLI). CodeReviewer runs also report per-sample
  mean, median, min and max.

### Timing benchmark (`eval timing`): fair comparison rules
- **Inputs** are fixed:
  - the planted repository (8 files, 6 Python);
  - `examples/order_service.py` (one 114-line file).
- **Configurations:**
  - `static_only`;
  - `llm_rag`: static + LLM + RAG, the product default;
  - `llm_no_rag`: static + LLM without retrieval.
- **Repeats:** 3 per input and configuration (`--repeats`). Rounds are interleaved
  (round → input → configuration), so network or machine drift hits every configuration alike.
  We report **median (min-max)** and also store the mean.
- **Concurrency 1,** so components are sequential and "other" is meaningful.
- **A fresh, empty vector store per run.** The persistent index is keyed by a content hash, so
  without this, repeat 2+ would skip embedding and look faster than a first review.
- **One untimed warm-up** per input (imports, tool caches).
- **Suggested fixes are off** (`--with-fixes` turns them on): they are extra LLM calls, not part
  of the review.
- **Conditions recorded per run:**
  - files, Python files, lines reviewed, review units, LLM calls;
  - provider and model, RAG on/off, vector store;
  - hardware: platform, processor, CPU count, Python version.
- **Incomplete runs** (an LLM unit failed: quota, size) are kept in predictions but **excluded**
  from aggregates.

**RAG latency overhead:** `(T_with_RAG − T_without_RAG) / T_without_RAG × 100`. It uses each
configuration's median *active* time (total minus quota waiting) on the same input and model. It
is reported only when both configurations have complete runs. Quota waiting depends on earlier
traffic on the API key, not on the pipeline, so it is excluded from this comparison only.

```bash
python -m marl_agents.cli eval timing --repeats 3                       # needs GROQ_API_KEY
python -m marl_agents.cli eval timing --repeats 3 --timing-configs static_only   # offline
python -m marl_agents.cli review examples/order_service.py              # one review, prints its breakdown
```

### Reading the breakdown
- **Total versus LLM time.** Total minus LLM inference is the agent's own cost. LLM inference is
  the model's.
- **Static analysis is mostly mypy.** On these inputs mypy dominates static analysis because it
  starts cold for every review. Ruff and Radon take tens of milliseconds.
- **Quota waiting** appears only on rate-limited free tiers. It is environmental, not
  computational.

---

## Results

See [`experiments/evaluation_summary/summary.md`](../experiments/evaluation_summary/summary.md),
which is regenerated by `eval summary`, and the results section below (last updated from the runs
it lists).

### Results (2026-10-12)

Every value below is from a saved run, listed under "Source runs" in the generated summary.
LLM: `openai/gpt-oss-120b` on Groq, unless stated otherwise.

| Evaluation | Metric | Result | Configuration / n |
|---|---|---:|---|
| Planted issues | Precision | **1.000** | static + LLM; 13 TP, 0 FP |
| Planted issues | Recall | **0.941** | 16 of 17 issues; FN = P13 (see note 1) |
| Planted issues | F1 | **0.970** | |
| CodeReviewer cls | Precision | 0.384 / **0.592** | static, n = 4,195 (all rules / cross-hunk rules excluded) |
| CodeReviewer cls | AUC | 0.417 / **0.539** | same |
| CodeReviewer msg | Coverage | 0.281 → **0.778** | static n = 1,403 → static + LLM (qwen3.8-27b), n = 36 |
| CodeReviewer msg | chrF | 4.83 → **13.60** | same |
| RAG | Recall@10 | **0.417** vs 0.021 random | 316 call-graph queries on `src/` |
| Risk ranking | Precision@top 10% | **0.733** (v2) vs 0.305 (v1), 0.484 random; size alone 0.792 | 4,194 test hunks |
| Risk ranking | AUC | 0.644 (v2) vs 0.431 (v1); size 0.651 | same |
| Efficiency | Total time, repository review | 228.3 s median, of which **24.9 s active** | planted repo, LLM + RAG, 3 runs |
| Efficiency | Total time, static-only review | **6.1 s** | planted repo, 3 runs |

**Where the time goes** (planted repository: 8 files, 146 lines, 4 LLM review units; median of 3
runs; seconds):

| Component | Static only | LLM, no RAG | LLM + RAG |
|---|---:|---:|---:|
| Static analysis | 5.99 | 5.02 | 5.53 |
|   of which mypy | 5.91 | | |
| RAG (index + queries) | 0 | 0 | 0.31 |
| LLM inference (4 calls) | 0 | 18.50 | 18.53 |
| Validation | 0.002 | 0.004 | 0.005 |
| Report generation | 0.10 | 0.11 | 0.11 |
| Other / orchestration | 0.02 | 164.80 | 204.53 |
|   of which LLM quota waiting | - | 161.83 | 204.44 |
| **Total** | **6.10** | **186.75** | **228.34** |
| Active time (total − quota waiting) | 6.10 | 24.92 | 24.86 |

How to read it:
1. **Quota waiting dominates the wall-clock time** on Groq's free tier: 160–270 s per review. It is
   the provider throttling, not computation, and is reported separately. The agent's **active**
   time for a repository review is about **25 s**.
2. **Within active time, the LLM is about 75%** (18.5 s for 4 calls) and **static analysis about
   22%**. Static analysis is almost entirely **mypy** (5.9 s, cold start on every review). Ruff
   takes 0.06 s, Radon 0.01 s, the AST checks 0.01 s, and the secret and test-gap checks under
   0.01 s each.
   Validation (10 ms) and reports (0.1 s) are negligible. Running mypy only on changed or
   impacted files, or caching it, is the cheapest optimisation available.
3. **RAG costs 0.3 s per review (about 1% of active time).** End-to-end RAG overhead on the
   repository is −0.3%, which is within noise.
   - On the single file the overhead formula gives **+92.4%**. That figure is explained by
     JSON-schema retries, not by retrieval. Two of the three RAG runs needed one retry of the LLM
     call (median 1 retry with RAG, 0 without), and RAG's own cost there is 0.16 s (0.7%).
   - Comparing runs without a retry, the LLM call took 4.9 s with RAG and 5.9 s without.
   - With n = 3 and a model that sometimes returns invalid JSON, this single-file comparison is not
     evidence that RAG slows reviews.
4. **Static-only reviews** (CI and pre-commit default) take **about 6 s**. In the CodeReviewer
   benchmark (one hunk, mypy off, 8 parallel workers) a static review takes **0.19–0.23 s per
   sample** (median).

**Notes**
1. **LLM run-to-run variation.** The same configuration on 2026-09-29 found P13 (recall 1.000).
   On 2026-10-12 it did not (0.941), even at temperature 0. With a single LLM-only issue in the
   suite, LLM-only recall can only be 0/1 or 1/1, so the summary lists earlier runs next to the
   latest.
2. **Risk ranking: v2 versus size.** After the line-ending fix (`results.md` 6a), size alone ranks
   slightly better than v2. v2 still beats v1 and random by a wide margin. Re-fitting v2 on a
   corrected validation run is the documented next step.
3. **Not run yet:** CodeReviewer cls with the LLM. The command is in the summary. Run it when the
   daily Groq quota allows (about 40 samples per day).
