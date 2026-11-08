# Results

Every number below is copied from a saved run in `experiments/results/<run>/metrics.json`
(each run also stores config, package versions, sample IDs, raw predictions and errors). Each section
names its own runs. Sections 1-5 were run on 2026-09-29. All runs come from an **uncommitted working
tree** (`git_commit: uncommitted` in `meta.json`); commit the code and re-run to get commit-traceable
numbers.

> **Scope of these results:** Code Review Agent. Sections 1-4 are `review.mode = static_only`
> (Ruff + Radon + custom AST checks + secret scanning; no LLM): the **baseline** the LLM modes must
> beat. Sections 5 and 7 have Groq runs, and section 11 has the first, preliminary Gemini runs. Full
> mode on CodeReviewer `cls` and complete Gemini runs are still to do. Mock-LLM runs verify the pipeline
> only and are never reported.

**Status of each section.** Old results are kept as recorded. Nothing below has been edited to look
newer than it is.

| Section | Status | Note |
|---|---|---|
| 1. Planted issues | Current | Static-only baseline |
| 2. RAG retrieval | **Superseded in part** | Table below is the first of 4 runs; the latest is noted there |
| 3. CodeReviewer `cls` | Current | Static-only. Re-run 2026-10-12: identical (see 6a) |
| 4. CodeReviewer comments | Current | Static-only. Re-run 2026-10-12: identical (see 6a) |
| Next runs | Historical | Plan written during the Groq phase |
| 5. Planted issues, Groq | Historical | Groq is no longer the default provider |
| 6. Hunk risk | **Superseded in part** | Test rows replaced by 6a; the validation row has the same bug |
| 6a. Hunk-risk correction | Current | Replaces the test rows of section 6 |
| 7. Comments and usefulness, Groq | Historical | Groq, n = 36. No Gemini equivalent yet |
| 8. Execution time | Current, **static-only** | No LLM time. Preliminary Gemini times are in section 11 |
| 9. Fine-tuned classifier | Current | Does not depend on the LLM provider |
| 10. Pending Gemini experiments | **Pending** | Work still to run |
| 11. First live Gemini runs | **Preliminary** | `gemini-3.6-flash`. Incomplete, and under the old token limit |
| 12. Planted issues on Gemini | Current | `gemini-3.6-flash`, all four configurations in one group |

## 1. Planted-issue benchmark

Run `20260929T193007Z_planted_static_only`. Fixture repo `tests/fixtures/repos/planted` with 17
hand-labelled issues (16 detectable by rules, 1 needs semantic reasoning) and one clean
negative-control file. Ground truth is stored outside the analyzed folder.

| Metric | Value |
|---|---:|
| Recall, all issues | 0.941 (16/17) |
| Recall, static-detectable issues | 1.000 |
| Recall, LLM-only issues | 0.000 (the missed issue is P13: division by zero on an empty list) |
| Defect-finding precision | 1.000 (13/13) |
| False positives in the negative-control file | 0 |
| Mean line error of matched findings | 0.0 |

Caveat: a small benchmark written by the same team that wrote the rules. It is a regression gate
and a sanity check, not evidence of general accuracy.

**Reading the counts.** Recall counts labelled issues of every category (16 of 17 here). Defect
precision counts findings of the defect classes only (13 of 13). The answer key has 14 defect-class
issues and 3 others (quality, maintainability, standards), so a run can find 17 of 17 issues with 14
correct defect findings. Those are separate counts, and the F1 built from them has mixed denominators.
Rule-detectable recall covers 16 issues. Semantic recall covers 1, so it is 0 or 1 in any run.

## 2. RAG retrieval (call-graph relevance)

Run `20260929T193008Z_retrieval_src`. Repository = this project's `src/` (315 code chunks,
138 queries). Query = a function's chunk; relevant = chunks containing the functions it calls
(from the AST call graph).

| Method | Recall@1 | Recall@5 | Recall@10 | Hit@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| Random baseline | 0.002 | 0.020 | 0.031 | 0.058 | 0.036 | 0.016 |
| Hashing (lexical) embedder | 0.116 | 0.404 | 0.541 | 0.797 | 0.412 | 0.379 |

Reading: lexical dense retrieval is far better than random, but still misses ~46% of a function's
direct dependencies in the top 10. This motivated design decision CR5: structural call-graph context
is added before dense retrieval. Neural embeddings (sentence-transformers) were not run yet
(`--embedders hashing,sentence-transformers/all-MiniLM-L6-v2` after installing the `rag` extra).

> **Superseded in part.** The table above is the first of 4 saved runs. The repository grew between them
> (138, 277, 316, then 381 queries), so they are not comparable. The latest,
> `20261012T163120Z_retrieval_src` (665 chunks, 381 queries, hashing embedder), gives Recall@10 0.365 and
> MRR 0.312, against random 0.012 and 0.020. The dashboard shows the latest. All of these measure
> retrieval quality, not final review accuracy.

## 3. CodeReviewer: diff quality estimation ("does this hunk need a review comment?")

Run `20260929T192259Z_codereviewer_cls_test_static_only_n4196`. Test split, Python only, all 4,196
samples; 4,195 evaluated (1 patch did not apply to its `oldf` and is recorded in `errors.jsonl`).
Labels: 2,033 positive / 2,162 negative. Prediction = at least one in-scope finding of severity >= low.

| Rule set | Accuracy (95% CI) | Precision (95% CI) | Recall | F1 (95% CI) | ROC-AUC |
|---|---:|---:|---:|---:|---:|
| All rules | 0.437 (0.422-0.453) | 0.384 (0.358-0.412) | 0.266 | 0.314 (0.295-0.335) | 0.417 |
| Without cross-hunk rules* | 0.541 (0.525-0.555) | 0.592 (0.552-0.636) | 0.167 | 0.261 (0.237-0.285) | 0.539 |
| Majority-class baseline | 0.515 | - | - | - | - |
| Always-positive baseline | 0.485 | 0.485 | 1.000 | 0.653 | - |

\* F401, F403, F405, F811, F821. Each CodeReviewer sample is **one hunk** of a larger commit, applied
to the old file. Imports and definitions added in *other* hunks are missing, so "undefined name"
(F821) and "unused import" (F401) fire on correct code. F821 alone fired 706 times on negative
samples vs 61 on positive ones, which is what inverted the all-rules result (AUC < 0.5). The
sensitivity analysis is computed in the same run from the same predictions and is always reported
next to the raw numbers.

Findings:
- With all rules the static baseline is **worse than chance** on this benchmark; that is an artefact
  of hunk-level evaluation, not of the rules on real code.
- Without cross-hunk rules it is **slightly better than chance** (AUC 0.539, accuracy above the
  majority baseline, CI excludes 0.515) with **precision 0.59 but recall 0.17**: when static analysis
  flags a hunk it is usually one reviewers also commented on, but most reviewer comments (naming,
  design, logic, API usage) are not rule-detectable. That gap is what the LLM stage must close.
- The always-positive F1 (0.653) is higher than ours because F1 rewards flagging everything on a
  balanced set; accuracy / precision / AUC are the more informative metrics here.

## 4. CodeReviewer: review comment generation

Run `20260929T192630Z_codereviewer_msg_test_static_only_n1403`. Test split, Python only, all 1,403
samples, 0 failures. The generated comment is the top-ranked in-scope finding.

| Rule set | Comment coverage | BLEU-4 smoothed (title + fix) (95% CI) | ROUGE-L | chrF |
|---|---:|---:|---:|---:|
| All rules | 0.281 | 1.18 (1.05-1.30) | 3.03 | 4.83 |
| Without cross-hunk rules | 0.182 | 0.74 (0.65-0.84) | 1.82 | 2.99 |

(Other comment renderings, `title` and `description`, are in `metrics.json`; `title + fix` scored highest.)

Reading: rule messages do not resemble human review comments, and 72% of hunks get no static
finding at all (scored as an empty comment). Comment generation is inherently an LLM task; these
numbers are the floor. The CodeReviewer paper reports its own scores with a similar smoothed
BLEU-4, so compare with it when writing up; our tokenizer is a simple word/punctuation split
(see `evaluation/metrics/text.py`), so small differences are expected.

## Next runs

> **Historical.** This list dates from the Groq phase, so the provider, default model and
> quota below are out of date. Current pending work is in [section 10](#10-pending-gemini-experiments).

1. **Done** for comment generation, on a subset (section 7). Still to run: `--mode full` on
   CodeReviewer `cls`, and comment generation on a larger subset with the default model
   (gpt-oss-120b). Groq's free tier allows 200k tokens/day per model, about 40-45 reviewed samples,
   so spread larger runs over days or models and reuse `sample_ids` from `meta.json`.
2. Human ratings for the usefulness kit (section 7b) to validate the LLM judge.
3. Ablations on the planted benchmark and real repositories: `--no-rag`, `--no-structural`,
   `--mode llm_only`.
4. Retrieval with neural embeddings vs hashing.

## 5. First LLM runs: planted benchmark with Groq models (full mode, RAG on)

> **Historical.** Results stand, but Groq is no longer the default provider (decision D27). The
> default-model choice below applied to Groq only.

Runs `20260929T194203Z_planted_full` (gpt-oss-120b), `20260929T194356Z_planted_full` (gpt-oss-20b),
`20260929T194832Z_planted_full` (qwen3.8-27b). Same fixture and settings as section 1, temperature 0,
prompts v1.0, Groq API, default rate limits (30 req/min, 6000 tokens/min).

| Model | Recall (all) | Recall (LLM-only) | Defect precision | Mean line error | LLM findings (rejected) | Tokens in + out | LLM time |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static only (section 1) | 0.941 | 0.000 | 1.000 (13/13) | 0.00 | - | - | - |
| openai/gpt-oss-120b | 1.000 | 1.000 | 1.000 (14/14) | 0.29 | 10 (1) | 8,305 + 6,934 | 65 s |
| openai/gpt-oss-20b | 1.000 | 1.000 | 0.933 (14/15) | 0.53 | 16 (0) | 16,949 + 12,392 | 270 s |
| qwen/qwen3.8-27b | 1.000 | 1.000 | 1.000 (14/14) | 0.82 | 13 (0) | 8,570 + 4,371 | 185 s |

- Every model found the semantic issue static analysis cannot (P13, division by zero on an empty
  list) and confirmed all static findings (triage verdicts: 100% "confirm").
- gpt-oss-20b's one false positive: it labelled `discount == None` (a style issue, E711) as a bug.
- **Chosen default: `openai/gpt-oss-120b`** (best precision and localization, 3-4x faster).
- **Recall is not stable between runs.** `20261012T090444Z_planted_full` is a complete run of the same
  configuration and model, and it found 16 of 17, missing P13. Do not quote 1.000 as a stable result.
- Caveat: 17 issues is far too small to rank models statistically; speed and token cost differences
  are the robust part of this comparison. The CodeReviewer runs in full mode are the real test.

## 6. Change review: does "review these hunks first" point at the right hunks?

> **Superseded in part.** A line-ending bug affected these runs. Section 6a replaces every test row
> below, and its finding that size alone is slightly better replaces the conclusion here that v2 wins
> at the top. The rows and text are kept as the historical record.

Task: CodeReviewer `cls` (Python). The label is 1 if a human reviewer commented on the hunk. For each
sample the real change-review pipeline runs (`review_change`, static only, as shipped). The sample
is scored by its top hunk's risk. Baselines: hunk size (no analysis at all) and the finding score.

| Status | Run | Split | Risk model | n | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---|---|---|---:|---:|---:|---:|---:|
| Superseded | `20261005T110341Z_hunkrisk_cls_test_n4196` | test | v1 (hand-set points) | 4,195 | 0.434 (0.418-0.452) | 0.373 | 0.365 | 0.357 |
| Same bug, not re-run | `20261005T111337Z_hunkrisk_cls_valid_n4220` | valid | v1 (hand-set points) | 4,219 | 0.453 (0.436-0.470) | 0.343 | 0.354 | 0.376 |
| Superseded | `20261005T112307Z_hunkrisk_cls_test_n4196` | test | **v2 (calibrated on valid)** | 4,195 | **0.624 (0.608-0.641)** | **0.612** | **0.671** | 0.604 |
| Superseded | same run | test | size-only baseline | 4,195 | 0.624 (0.607-0.641) | 0.344 | 0.530 | 0.635 |
| Superseded | same run | test | finding-score baseline | 4,195 | 0.407 (0.392-0.424) | 0.325 | 0.279 | 0.327 |

Base rate (share of hunks that were commented on) is 0.485, which is what a random order achieves.
One patch per split did not apply and is recorded in `errors.jsonl`.

What happened:
- **v1 was worse than chance.** Its heaviest signal, static findings inside the hunk, points the
  wrong way on this benchmark (validation: commented 0.402 when it fires, 0.538 when it does not).
  Part of this is the cross-hunk artefact from section 3. Even without it, medium/high findings had
  negative weight.
- **v2.** Inputs were fixed in advance and four weights were fitted by logistic regression on
  **validation only** (`scripts/calibrate_hunk_risk.py`, output `calibration.json` in the valid
  run). Signals with weight zero or below were dropped, because a signal must never lower risk.
  The guardrail lifts critical/high findings. The test split was then run **once** with the shipped
  code.
- **v2 ties size on overall ranking but wins where it matters.** "Review these first" is used from
  the top. Of the 10% of hunks v2 puts first, 67.1% got a human comment, against 53.0% for size and
  48.5% at random. Its "high" level (10.4% of hunks) was commented 67.8% of the time.
- **The "medium" level is barely informative** (commented 45.7%, against 46.5% for "low"). Treat it
  as "not high". Level thresholds are validation-split percentiles and were not tuned on test.
- **Limits.** The label is "a reviewer commented", which is a proxy for "needs attention". Each
  sample is one file, so the cross-file signals (broken callers) cannot be measured here. Their
  weights are expert-set and covered by unit and integration tests instead.

## 7. First LLM run on CodeReviewer comment generation, and comment usefulness

> **Historical provider.** This run used Groq. No Gemini equivalent exists yet
> ([section 10](#10-pending-gemini-experiments)).

**Run** `20261005T120433Z_codereviewer_msg_test_full_n40`. Settings:
- Test split, Python, n=40 random samples (seed 42).
- `--mode full`, RAG on, suggested fixes off.
- Reviewer **`qwen/qwen3.8-27b`** on Groq, temperature 0, prompts v1.0.

Why not the default model: an earlier attempt with gpt-oss-120b exhausted that model's Groq daily
token quota mid-run and was aborted unscored (see the `ABORTED.txt` file in its run folder; decision
D22).

**Failures.** 36 samples were evaluated and 4 failed, all because the LLM did not review them:
- 3 × request size (one 413, two 429 responses after 6 attempts). The 413 path is now handled by
  retrying without project context (D21), but this run predates the fix.
- 1 × daily quota.

These failures are counted (D22), not scored as static-only.

### 7a. Similarity to the human comment (same 36 samples, both configurations)

The static numbers come from run `20261005T115807Z_codereviewer_msg_test_static_only_n1403`,
restricted to the same sample IDs (`paired_static_baseline.json` in the LLM run).

| Configuration | Comment coverage | BLEU-4 (95% CI) | ROUGE-L | chrF |
|---|---:|---:|---:|---:|
| Static only | 0.472 | 1.98 (1.13-2.90) | 5.45 | 8.73 |
| Static + LLM (qwen3.8-27b) | **0.778** | 2.14 (1.52-2.74) | 6.91 | **13.60** |

- The LLM produces a review comment for 78% of diffs, against 47%.
- chrF and ROUGE-L rise.
- **BLEU-4 does not improve significantly** (the CIs overlap at n=36). One human reference comment
  per diff is a narrow target: a correct comment about a *different* real issue scores near zero.
  That is why usefulness is also measured directly (7b).

### 7b. Usefulness (LLM judge)

Run `20261005T154602Z_usefulness_codereviewer_msg_test_full_n40`:
- Judge **`openai/gpt-oss-20b`**, a different model family from the reviewer, `reasoning_effort=low`.
- Blind (it never knows who wrote a comment) and reference-free (it sees only the diff).
- Criteria: CodeReviewer's human-evaluation criteria, 1-5.
- 64 of 64 items judged. The agent produced no comment on 8 of the 36 diffs, so those have no
  agent rating.

| Comment author | n | Relevance (95% CI) | Informativeness (95% CI) | Relevance >= 4 | Informativeness >= 4 |
|---|---:|---:|---:|---:|---:|
| Agent | 28 | 4.71 (4.29-5.00) | 4.64 (4.21-4.96) | 0.93 | 0.93 |
| Human reviewer (dataset) | 36 | 3.67 (3.22-4.08) | 3.00 (2.61-3.42) | 0.67 | 0.39 |

Paired, on the 28 diffs with both comments (agent minus human):
- relevance **+0.96** (95% CI +0.25 to +1.61);
- informativeness **+1.57** (+0.89 to +2.18).

**Do not read this as "better than human reviewers".** Known biases point the same way:
- Agent comments are about 7× longer (median 490 vs 72 characters), and the informativeness rubric
  rewards explicit explanation.
- Half of the human comments (14/28) are questions ("Could you split this?"). These are legitimate
  review moves that the rubric scores low.
- The judge sees one hunk, just as the agent does. It cannot spot cross-hunk false positives such as
  an "unused import" that is used in another hunk of the same commit.
- Some tool comments repeated their title; that rendering was fixed after the run.
- n=28 pairs, one judge model.

What the result *does* support: the agent's comments are specific, actionable, and judged correct
about the changed code by an independent model.

**Next step (needs people, ~1 hour):** two raters fill in the blinded sheet
`human_kit/rating_sheet.csv` (56 rows: 28 diffs × agent/human comment, shuffled), then run
`python -m marl_agents.cli eval agreement --key <run>/human_kit/key.csv --sheets r1.csv,r2.csv`.
Cite the judge's numbers only if judge-human agreement (weighted kappa) is comparable to
human-human agreement.

### 6a. Correction (2026-10-12): hunk-risk numbers after the line-ending fix

On 2026-10-05 a Windows bug was fixed: in-memory files were written with CRLF translation (decision
D21 era). In the hunk-risk evaluation this affected **the 330 of 4,195 samples (7.9%) whose old file
has CRLF line endings**. Their whole file appeared changed, so "hunk size" was inflated by a median
factor of 230. This was verified sample by sample: exactly those 330 samples changed size, and no
others did.

The CodeReviewer cls and msg results (sections 3, 4 and 7) are **unaffected**. They were re-run on
2026-10-12 and are identical: the benchmark writes each file only once, and the bug needed a second
write.

Re-run `20261012T085812Z_hunkrisk_cls_test_n4196` (test, n = 4,194; 2 failed). This **supersedes**
the 2026-10-05 test rows in section 6.

| Scorer | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| Risk v2 (calibrated, shipped) | 0.644 (0.627-0.662) | 0.761 | 0.733 | 0.662 |
| Size only | **0.651 (0.634-0.669)** | **0.823** | **0.792** | **0.677** |
| Risk v1 (hand-set, frozen baseline) | 0.431 (0.415-0.449) | 0.230 | 0.305 | 0.353 |
| Finding score | 0.407 (0.392-0.423) | 0.282 | 0.224 | 0.321 |
| Random (expected) | 0.500 | 0.484 | 0.484 | 0.484 |

What this changes:
- **v2 still clearly beats v1 and random.** At the top 10%, 73.3% of v2's hunks were commented on,
  against 30.5% for v1 and 48.4% at random.
- **The earlier claim "v2 beats size at the top" no longer holds.** With correct line counts, size
  alone is slightly better: 79.2% at the top 10%, and AUC 0.651 against 0.644 (the CIs overlap).
  The v2 weights were fitted on the 2026-10-05 validation run, which had the same bug, so size got
  a very small weight (0.055 per doubling).
- **Next step (not done, to avoid tuning against test results we have now seen).** Re-fit v2 on a
  re-run *validation* split with the corrected sizes, then evaluate on test once. Until then the
  product keeps v2. Its guardrail and its explicit reasons (security-sensitive code, error
  handling, signature changes, broken callers) are what a reviewer sees; raw size gives no reason.

## 8. Execution time by file size

> **Static-only.** Everything in the table below excludes LLM time. Full Gemini review times are
> pending, and these numbers are no estimate of them.

| Measurement | Status | LLM time included? |
|---|---|---|
| Static-only file-size benchmark (this section) | Measured | No |
| Full Gemini review by file size | **Preliminary: see section 11** | Yes |
| Earlier Groq timing (`20261012T090910Z_timing_r3`) | Historical | Yes, but another provider |

Run `20261106T122017Z_runtime_static_only_r5`, 2026-11-06. **Static analysis only: no LLM was used**,
because no Gemini key was configured. So these times exclude LLM inference and tokens, and they are
not the time of a full review. Nine real files from Python's standard library (three per category),
5 rounds, concurrency 1, 12-CPU Windows machine, Python 3.11.7, mypy included. Cold = empty caches.
Warm = immediately after, with the cached static-analysis results. All 90 runs completed.

| Size | Run | Mean (s) | Median | P95 | Min | Max | Static analysis (mean) | Findings (mean) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Small (1-100 lines) | cold | 2.42 | 2.39 | 2.56 | 2.32 | 2.75 | 2.35 | 11.67 |
| Small | warm | 0.07 | 0.06 | 0.10 | 0.04 | 0.11 | 0.02 | 11.67 |
| Medium (101-1,000) | cold | 2.56 | 2.46 | 2.87 | 2.29 | 2.97 | 2.45 | 16.00 |
| Medium | warm | 0.12 | 0.07 | 0.25 | 0.03 | 0.27 | 0.03 | 16.00 |
| Large (1,001-5,000) | cold | 4.69 | 4.83 | 6.37 | 2.91 | 6.39 | 4.35 | 64.67 |
| Large | warm | 0.39 | 0.19 | 0.80 | 0.15 | 0.81 | 0.07 | 64.67 |

- Static analysis takes more than 90% of the time in every cold category. Time grows slowly with
  size: large files here average about 50 times the lines of small ones, yet cost about twice as
  long. That suggests tool start-up dominates, though this run does not separate start-up from work.
- Reusing cached static results cuts a repeat review by 92-97% with identical findings. This only
  applies to unchanged code.
- **Pending, only partly measured (section 11):** LLM inference and token use by file size:
  `python -m marl_agents.evaluation.benchmark_runtime --config configs/gemini.yaml --repeats 5 --per-category 1 --max-llm-calls 65`.
  On Groq, LLM inference and quota waits took most of each review (run
  `20261012T090910Z_timing_r3`), but that is a different provider and is no estimate for Gemini.

## 9. Fine-tuned change classifier

Run `20261106T144800Z_classifier_cls_test_n1771`, 2026-11-06. CodeBERT, partially fine-tuned on CPU:
16,000 training changes (7,299 Python, 8,701 other languages), 1.15 of 2 epochs, stopped by the
110-minute budget on the training loop (115.1 minutes elapsed, including the final dev check and
save). Threshold 0.44, chosen on dev. The test set was used once, after the model and threshold were
frozen. The label is "a human commented on this change", a proxy for "needs review". Python only.
Method and limits: [fine-tuning.md](fine-tuning.md).

Primary set: repository-disjoint test, n = 1,771 (979 commented, 792 not). Dev and test were split by
project name wherever the data has one. The 3,383 Python training positives have no project name, so
complete repository separation cannot be guaranteed. The audit found no shared project or patch
where it could check, including the 8,701 non-Python training records, which come from `valid`, the
same raw file as dev (`separation_audit.json` in the run).

| Scorer | Accuracy | Precision | Recall | F1 | FPR | ROC-AUC (95% CI) |
|---|---:|---:|---:|---:|---:|---:|
| Fine-tuned classifier | 0.665 | 0.707 | 0.672 | 0.689 | 0.345 | 0.723 (0.699-0.748) |
| TF-IDF + logistic regression | 0.591 | 0.678 | 0.494 | 0.572 | 0.290 | 0.645 (0.619-0.670) |
| Original static analysis (adjusted rules) | 0.500 | 0.674 | 0.184 | 0.289 | 0.110 | 0.541 |
| Change size alone | - | - | - | - | - | 0.635 |
| Majority class | 0.553 | - | - | - | - | - |

Confusion matrix: 658 TP, 273 FP, 519 TN, 321 FN. Official Python test (secondary, n = 3,634; 14 of
its 29 projects are dev projects and 3 Python training negatives share a patch with it): F1 0.699,
ROC-AUC 0.724 (0.707-0.741).

ROC-AUC intervals are percentile bootstrap intervals: 300 resamples of single changes with
replacement, Python `random.Random` seed 42, unstratified. They assume changes are independent, so
they may be too narrow. Static analysis and change size have no interval. The static row covers the
same 1,771 changes, taken from run `20261012T163153Z_codereviewer_cls_test_static_only_n4196`, so it
differs from section 3, which covers 4,195.

- The classifier ranks changes better than every baseline. It recalls far more than static analysis,
  and pays with more false alarms: FPR 0.345 against 0.110.
- It learned more than change size: within size bands its weighted AUC is 0.693, while size alone gives
  about 0.50-0.57, and it beats size in 11 of 12 projects (median AUC 0.72, lowest 0.457 at n = 42).
  This check ran after the test and is descriptive (`confound_check.json` in the run).
- Ranking is its strongest use: 93.8% of its top 10% of changes drew a comment, against a base rate of
  55.3% and 80.8% for the largest changes.
- **Not shown:** better review comments, or any saving in LLM calls. The classifier writes no comments,
  and no Gemini run exists. Those rows stay N/A in `eval before-after`.

## 10. Pending Gemini experiments

**No final result exists for anything in this section.** Preliminary runs are in section 11. The free
limit is 20 requests per day, per project, per model, so these runs take several days.

| Experiment | Status | Command |
|---|---|---|
| Key and model check | Done on `gemini-3.6-flash` (section 11) | `python -m marl_agents.cli check` |
| Live provider test | Pending | `pytest -m llm tests/integration/test_gemini_live.py` |
| Full review time by file size | Preliminary only (section 11) | `python -m marl_agents.evaluation.benchmark_runtime --config configs/gemini.yaml --repeats 5 --per-category 1 --max-llm-calls 65` |
| Planted issues on Gemini, A-D | **Done** (section 12) | `python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml` |
| Comment generation on Gemini, A-D | Pending | `python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --reuse-llm-cache --config configs/gemini.yaml` (repeat daily) |
| Classifier off, prioritize and gate, dev samples only | Started: 2 of 15 samples (section 12) | `python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml` |

Earlier Groq results (sections 5 and 7) are a different provider and are no estimate for Gemini.

## 11. First live Gemini runs

> **Preliminary.** Incomplete, and measured with `llm.max_tokens = 4096`, since raised to 16,384. Do not
> quote these as the file-size benchmark, and do not mix them with Groq results.

All successful runs used `gemini-3.6-flash`, 2026-11-06, free tier, temperature 0, seed 42.

**Smoke test.** Run `20261106T161948Z_gemini_smoke`, synthetic code. All live checks passed: model
access, JSON and Pydantic validation (20 + 5 tokens), one full agent review (1 call, 0 failed units,
1 validated LLM finding), invalid key (400, one attempt, no key in the message), a failed request not
crashing a review, and timeout with retry. The per-minute 429 path was not provoked and is simulated.

**`gemini-3.8-flash`.** Run `20261106T161252Z_gemini_smoke`. Listed for the key, but all generation
failed after 6 tries, twice, 30 minutes apart: "This model is currently experiencing high demand."

**File-size benchmark.** Run `20261106T162014Z_runtime_full_r5`. 90 runs planned, 11 measured (8
complete, 3 partial), 79 skipped after the daily quota. 19 LLM calls including 6 failed. Tokens: 54,615
input, 4,919 output, 43,796 reasoning. Public standard-library files, RAG on, one round reached.

| Size | Run | Complete runs | Total (s) | LLM (s) | RAG (s) | Static (s) | Cache hit rate |
|---|---|---:|---:|---:|---:|---:|---:|
| Small | Cold | 3 | 20.82 | 17.42 | 0.01 | 2.28 | 0% |
| Small | Warm | 3 | 0.12 | 0.00 | 0.01 | 0.02 | 100% |
| Medium | Cold | 1 | 23.08 | 20.44 | 0.01 | 2.35 | 0% |
| Medium | Warm | 1 | 0.09 | 0.00 | 0.01 | 0.02 | 100% |
| Large | Cold and warm | 0 | Not measured | - | - | - | - |

- **Each small row covers three files once; each medium row covers `bisect.py` only.** `shlex.py` and
  `aifc.py` were partial and are excluded from these means.
- **Quota.** Google's 429: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20.
- **Replies were cut off on larger units.** On `shlex.py`, output plus reasoning reached 4,091 tokens per
  successful call, with reasoning about 93% of that. All 3 units failed, and failed units are not
  cached, so its warm run called the LLM again (0% hit rate).

## 12. Planted issues on Gemini, all four configurations

Group `abl-20261108T055008Z`, 2026-11-08, `gemini-3.6-flash`, temperature 0, `llm.max_tokens = 16384`,
free tier. All four configurations ran together on the same fixture and answer key, and every fairness
check passed. Runs: `20261108T055008Z_planted_static_only`, `20261108T055018Z_planted_llm_only`,
`20261108T055101Z_planted_static_llm`, `20261108T055201Z_planted_static_llm_rag`; comparison
`20261108T055341Z_ablation_planted`. 12 LLM requests, 0 failed units.

| Configuration | Issue recall | Found | Rule-detectable recall | Semantic recall | Defect precision | Correct / defect findings | Mean line error |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. Static Only | 0.941 | 16 | 1.000 | 0.000 | 1.000 | 13 / 13 | 0.00 |
| B. LLM Only | 0.706 | 12 | 0.688 | 1.000 | 1.000 | 11 / 11 | 1.25 |
| C. Static + LLM | 1.000 | 17 | 1.000 | 1.000 | 0.933 | 14 / 15 | 0.53 |
| D. Static + LLM + RAG | 1.000 | 17 | 1.000 | 1.000 | 1.000 | 14 / 14 | 0.53 |

- **What it shows:** static analysis finds every rule-detectable issue but not the semantic one, and the
  LLM finds the semantic one but misses rule-detectable issues on its own. Together (C and D) they find
  all 17. This matches the Groq runs in sections 1 and 5, which used other models and are kept apart.
- **C's one false positive** is "Missing request timeout in requests.get", not in the answer key. D did
  not report it. With one run each, that single difference is not evidence that RAG raises precision.
- **No clean-file false positives** in any configuration.
- **Limits:** 17 issues written by the project team, one run per configuration, one model.
- **Timing** from these single runs is in the run summaries; it is not the timing benchmark.
- **Commit:** the tree was clean at `ff1b67c` when the group started. The saved runs say `-dirty`
  because the recorder then counted its own new output folder; that was fixed in the next commit.

**Classifier ablation, started.** Run `20261108T055537Z_classifier_ablation_valid_n15`: 2 of 15
development samples complete in all three modes before the daily quota. No result is reported until the
run finishes; continue it with `--resume`.
