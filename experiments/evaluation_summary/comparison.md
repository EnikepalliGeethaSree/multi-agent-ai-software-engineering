# Code Review Agent: baseline comparison

- Agent-level benchmark evaluation of the Code Review Agent on its own. These numbers are not system-level results of the five-agent platform (SWE-bench Lite resolve rate), which is not built yet.
- Configuration D (Static + LLM + RAG) is the shipped Code Review Agent; A-C are ablations that switch one component off.
- Every value comes from a saved run in experiments/results/ (run ids are listed per row). A configuration without a valid run is N/A with the command that produces it. Runs made with the offline mock LLM test the pipeline and are never shown as results.

## Evaluation status

- **complete**: Planted-issue benchmark. 4 of 4 configurations on 17 issues, run with gemini-3.6-flash. Small benchmark.
- **preliminary**: CodeReviewer classification, paired. 3 of 10 requested samples paired; no scored samples for Static + LLM + RAG.
- **incomplete**: Review comment generation, paired. 36 of 40 requested samples paired; no scored samples for LLM Only, Static + LLM.
- **complete**: CodeReviewer classification, static only. Full Python test split, n = 4195. Not paired with the LLM runs.
- **complete**: Comment generation, static only. Full Python test split, n = 1403. Not paired with the LLM runs.
- **complete**: RAG retrieval. Retrieval quality on this repository, hashing embedder. It does not measure final review accuracy.
- **complete**: Risk ranking. 4194 hunks. Size-only is the better ranker.
- **complete**: Timing, historical Groq. Separate provider. Not an estimate for Gemini.
- **complete**: File-size benchmark, static only. 90 of 90 planned runs complete (0 partial, 0 failed, 0 skipped); 5 of 5 rounds finished.
- **incomplete**: File-size benchmark, gemini-3.6-flash. 8 of 90 planned runs complete (3 partial, 0 failed, 79 skipped); 0 of 5 rounds finished.
- **complete**: Fine-tuned change classifier. Held-out test, n = 1771, used once. Predicts human comments, not review quality.
- **complete**: Gemini smoke test. Live checks on gemini-3.6-flash. Failed on: gemini-3.8-flash
- **preliminary**: Comment usefulness (LLM judge). Supplementary. One judge model, not yet checked against human ratings.
- **pending**: Comment generation on Gemini. All four configurations on identical samples. About 120 requests, so repeat the command each day: cached replies carry the run forward.

### Code Review evaluation summary

Status: Gemini: gemini-3.6-flash

> **Small benchmark: 17 issues written by the project team. It is a regression check, and a score of 1.000 is not evidence of 100% bug detection in real code.**

Detection quality of each configuration. Planted issues: ROC-AUC is not applicable (positives only). CodeReviewer: raw metrics on the paired sample set; adjusted metrics are in section 2.

- **planted issues:** 17 labelled issues
- **CodeReviewer samples (paired):** 3
- **minimum paired n for a headline:** 30

| Configuration | Static | LLM | RAG | Planted issues (n = 17) Issue recall | Planted issues (n = 17) Defect precision | Planted issues (n = 17) F1 (mixed basis) | CodeReviewer classification (raw) Precision | CodeReviewer classification (raw) Recall | CodeReviewer classification (raw) F1 | CodeReviewer classification (raw) ROC-AUC | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.941 | 1.000 | 0.970 | N/A | N/A | N/A | N/A | - |
| LLM Only | ✗ | ✓ | ✗ | 0.706 | 1.000 | 0.828 | N/A | N/A | N/A | N/A | gemini-3.6-flash |
| Static + LLM | ✓ | ✓ | ✗ | 1.000 | 0.933 | 0.966 | N/A | N/A | N/A | N/A | gemini-3.6-flash |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.000 | 1.000 | 1.000 | N/A | N/A | N/A | N/A | gemini-3.6-flash |

N/A:
- Static Only / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- LLM Only / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- Static + LLM / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- Static + LLM + RAG / CodeReviewer classification (raw) (all): incomplete

- Model, sample counts, failures and the exact runs behind every cell are in the benchmark sections below.

Source runs: `20261108T055008Z_planted_static_only`, `20261108T055018Z_planted_llm_only`, `20261108T055101Z_planted_static_llm`, `20261108T055201Z_planted_static_llm_rag`

## 1. Planted issues

### Planted-issue benchmark: detection by configuration

Status: Complete | Small benchmark (n = 17) | Gemini: gemini-3.6-flash

> **Small benchmark: 17 issues written by the project team. It is a regression check, and a score of 1.000 is not evidence of 100% bug detection in real code.**

17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 needing semantic reasoning) plus a clean negative-control file.

- **answer key:** tests/fixtures/repos/planted_expected.json (17 issues)
- **negative control:** shop/utils.py
- **matching:** same file, start within +-2 lines, compatible category
- **precision counts:** defect findings only (bug, security, error handling, edge case)

| Configuration | Static | LLM | RAG | Labelled issues Issue recall | Labelled issues Found | Labelled issues Missed | Labelled issues Rule-detectable recall | Labelled issues Semantic recall | Defect findings Precision | Defect findings Correct | Defect findings False positives | Defect findings FP in clean file | Other F1 (mixed basis) | Other ROC-AUC | Other Mean line error | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.941 | 16 | 1 | 1.000 | 0.000 | 1.000 | 13 | 0 | 0 | 0.970 | N/A | 0.00 | 17 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.706 | 12 | 5 | 0.688 | 1.000 | 1.000 | 11 | 0 | 0 | 0.828 | N/A | 1.25 | 17 | 0 | 1 | gemini-3.6-flash |
| Static + LLM | ✓ | ✓ | ✗ | 1.000 | 17 | 0 | 1.000 | 1.000 | 0.933 | 14 | 1 | 0 | 0.966 | N/A | 0.53 | 17 | 0 | 1 | gemini-3.6-flash |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.000 | 17 | 0 | 1.000 | 1.000 | 1.000 | 14 | 0 | 0 | 1.000 | N/A | 0.53 | 17 | 0 | 1 | gemini-3.6-flash |

N/A:
- Static Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- LLM Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM + RAG / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined

Fairness checks:
- ✓ Same samples (answer key): one fixture repository and answer key for every configuration
- ✓ Same LLM model: gemini-3.6-flash
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'line_tolerance': 2, 'match': 'same file, start within +-2 lines, compatible category', 'precision_over': 'defect findings (bug, security, error_handling, edge_case)'}
- ✓ Run together (one ablation group): abl-20261108T055008Z

Observations (computed from the numbers above):
- Static + LLM has a higher recall than Static Only (1.000 vs 0.941).
- Static + LLM and Static + LLM + RAG have the same recall (1.000).
- Static Only has a higher recall than LLM Only (0.941 vs 0.706).
- Static Only has a higher precision than Static + LLM (1.000 vs 0.933).
- Static + LLM + RAG has a higher precision than Static + LLM (1.000 vs 0.933).
- Static Only and LLM Only have the same precision (1.000).
- Static Only: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- LLM Only: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM + RAG: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).

- Why 14 correct findings can sit beside 17 issues found: the answer key has 14 defect-class issues and 3 others (quality, maintainability, standards). Found counts issues of every category. Correct counts findings of the defect classes only. They are separate counts, so Correct + Missed need not equal the number of issues.
- Rule-detectable recall covers 16 issues. Semantic recall covers 1, so it can only be 0 or 1 in a run.
- F1 here mixes defect precision and issue recall, which have different denominators. Treat it as a summary of this benchmark, not a standard F1.
- Precision is N/A, not 1.0, when a configuration reports no defect findings at all.
- Run all four together: python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml

Source runs: `20261108T055008Z_planted_static_only`, `20261108T055018Z_planted_llm_only`, `20261108T055101Z_planted_static_llm`, `20261108T055201Z_planted_static_llm_rag`

## 2. CodeReviewer classification

### CodeReviewer: does this change need a review comment? (classification)

Status: Preliminary | Historical: Groq (openai/gpt-oss-120b)

> **Preliminary: only 3 of 10 requested samples are paired. No conclusion about any configuration can be drawn from this table, and ROC-AUC is not reported.**

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **paired samples:** 3 of 10 requested
- **evaluated per configuration:** A 10/10, B 10/10, C 3/10, D 0
- **requested samples:** 10
- **samples in every row:** 3
- **sampling seed:** 42
- **limit:** 10
- **flagged:** at least one finding of severity >= low
- **score (ROC-AUC):** highest finding priority / 5
- **ADJUSTED:** excludes F401, F403, F405, F811, F821

| Configuration | Static | LLM | RAG | RAW Precision | RAW Recall | RAW F1 | RAW ROC-AUC | ADJUSTED Precision | ADJUSTED Recall | ADJUSTED F1 | ADJUSTED ROC-AUC | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.000 | 0.000 | 0.000 | N/A | N/A | 0.000 | N/A | N/A | 3 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.667 | 1.000 | 0.800 | N/A | 0.667 | 1.000 | 0.800 | N/A | 3 | 0 | 1 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 0.667 | 1.000 | 0.800 | N/A | 1.000 | 1.000 | 1.000 | N/A | 3 | 7 | 1 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 10 | incomplete | openai/gpt-oss-120b |

N/A:
- Static Only / ADJUSTED Precision, ADJUSTED F1: undefined on these samples (zero denominator or one class only)
- Static Only / RAW ROC-AUC, ADJUSTED ROC-AUC: not reported: 3 paired samples are too few for ROC-AUC (minimum 30)
- LLM Only / RAW ROC-AUC, ADJUSTED ROC-AUC: not reported: 3 paired samples are too few for ROC-AUC (minimum 30)
- Static + LLM / RAW ROC-AUC, ADJUSTED ROC-AUC: not reported: 3 paired samples are too few for ROC-AUC (minimum 30)
- Static + LLM + RAG / all metrics: every sample failed in run 20261012T163034Z_codereviewer_cls_test_static_llm_rag_n10 (llm: 10); nothing to score

To run:
- Static + LLM + RAG: `python -m marl_agents.cli eval codereviewer --task cls --limit 10 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml`

Fairness checks:
- ✗ Same samples: 3 of 10 requested samples evaluated by Static Only, LLM Only, Static + LLM; no scored samples for Static + LLM + RAG (reference run 20261012T162634Z_codereviewer_cls_test_static_llm_n10)
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'flag_threshold': 'at least one finding of severity >= low', 'score': 'highest finding priority (severity rank + confidence) / 5', 'adjusted_excludes_rules': ['F401', 'F403', 'F405', 'F811', 'F821']}
- ✓ Run together (one ablation group): abl-20261012T161828Z

- RAW counts every finding. ADJUSTED drops the rules that cannot be judged from one hunk (imports/names defined in the commit's other hunks); both are always reported, neither replaces the other.
- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task cls --limit 10 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 3: far too few samples for any conclusion; this table only shows that the pipeline runs end to end. ROC-AUC is not reported. Each run's saved scores are unchanged in its predictions.jsonl.
- Static + LLM: 7 of 10 samples failed (llm: 7).
- Static + LLM + RAG: 10 of 10 samples failed (llm: 10).
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 10 samples need at least 30 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.
- That command reads the CodeReviewer cls test split, which contains the CodeBERT classifier's held-out samples. It does not run the classifier, but use --split valid for new work so that test set is not reused.

Source runs: `20261012T161828Z_codereviewer_cls_test_static_only_n10`, `20261012T161832Z_codereviewer_cls_test_llm_only_n10`, `20261012T162634Z_codereviewer_cls_test_static_llm_n10`, `20261012T163034Z_codereviewer_cls_test_static_llm_rag_n10`

### Static Only on the full Python test split (n = 4195)

Status: Complete | Static only, full test split | Not paired

Static analysis is cheap enough to run on every sample; LLM configurations are limited by API quota, so they are compared on the subset above. These samples are not paired with that subset, so do not compare this row with the table above.

- **dataset:** CodeReviewer, test split, Python only (all samples)

| Configuration | Static | LLM | RAG | RAW Precision | RAW Recall | RAW F1 | RAW ROC-AUC | ADJUSTED Precision | ADJUSTED Recall | ADJUSTED F1 | ADJUSTED ROC-AUC | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.384 | 0.266 | 0.314 | 0.417 | 0.592 | 0.167 | 0.261 | 0.539 | 4195 | 1 | 1 | - |

Source runs: `20261012T163153Z_codereviewer_cls_test_static_only_n4196`

## 3. Review comment generation

### CodeReviewer: review comment generation

Status: Incomplete | Historical: Groq (qwen/qwen3.8-27b)

> **Incomplete comparison: LLM Only, Static + LLM have no results; the rows were run separately; prompt versions were not fully recorded. This table does not show that RAG improves comment quality.**

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **paired samples:** 36 of 40 requested
- **evaluated per configuration:** A 40/40, B not run, C not run, D 36/40
- **requested samples:** 40
- **samples in every row:** 36
- **sampling seed:** 42
- **limit:** 40
- **comment:** top finding's title + recommendation
- **scale:** BLEU-4, ROUGE-L, chrF: 0-100; coverage: 0-1

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.98 | 5.45 | 8.73 | 0.472 | 36 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | N/A | N/A | N/A | N/A | - | - | not run | ? |
| Static + LLM | ✓ | ✓ | ✗ | N/A | N/A | N/A | N/A | - | - | not run | ? |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 2.14 | 6.91 | 13.60 | 0.778 | 36 | 4 | 1 | qwen/qwen3.8-27b |

N/A:
- LLM Only / all metrics: no saved run
- Static + LLM / all metrics: no saved run

To run:
- LLM Only: `python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration llm_only --workers 1 --config configs/gemini.yaml`
- Static + LLM: `python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm --workers 1 --config configs/gemini.yaml`

Fairness checks:
- ✗ Same samples: 36 of 40 requested samples evaluated by Static Only, Static + LLM + RAG; no scored samples for LLM Only, Static + LLM (reference run 20261005T120433Z_codereviewer_msg_test_full_n40)
- ✓ Same LLM model: qwen/qwen3.8-27b
- ✓ Same temperature: 0.0
- ? Same prompt versions: prompt versions not recorded
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'} (1 run(s) did not record it)
- ✗ Run together (one ablation group): separate runs

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 36: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).
- Static + LLM + RAG: 4 of 40 samples failed (llm: 4).
- The effect of RAG on comment quality cannot be judged here: it needs Static + LLM and Static + LLM + RAG on the same samples. Static Only vs Static + LLM + RAG changes two things at once.
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 40 samples need at least 120 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.

Source runs: `20261005T120433Z_codereviewer_msg_test_full_n40`, `20261012T163624Z_codereviewer_msg_test_static_only_n1403`

### Static Only on the full Python test split (n = 1403)

Status: Complete | Static only, full test split | Not paired

Static analysis is cheap enough to run on every sample; LLM configurations are limited by API quota, so they are compared on the subset above. These samples are not paired with that subset, so do not compare this row with the table above.

- **dataset:** CodeReviewer, test split, Python only (all samples)

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.18 | 3.03 | 4.83 | 0.281 | 1403 | 0 | 1 | - |

Source runs: `20261012T163624Z_codereviewer_msg_test_static_only_n1403`

## 4. RAG retrieval

### RAG retrieval vs random retrieval

Status: Complete | Embedder: hashing | Retrieval quality only

Self-supervised from the AST call graph: for each function, the relevant chunks are those containing the functions it calls; the query is the function's own chunk.

- **repository:** src
- **queries:** 381
- **chunks:** 665
- **cut-offs evaluated (k):** [1, 3, 5, 10]
- **embedding model:** hashing
- **review-time retrieval:** top_k = 6 similar chunks + guideline_k = 2 guideline chunks per review unit
- **random seed:** 42

| Method | Recall@1 | Recall@5 | Recall@10 | Hit@10 | MRR | nDCG@10 | n | failed | runs |
|---|---|---|---|---|---|---|---|---|---|
| Random baseline | 0.001 | 0.005 | 0.012 | 0.032 | 0.020 | 0.007 | 381 | - | 1 |
| RAG (hashing embedder) | 0.090 | 0.264 | 0.365 | 0.606 | 0.312 | 0.266 | 381 | - | 1 |

Observations (computed from the numbers above):
- RAG (hashing) has a higher Recall@10 than random (0.365 vs 0.012).

- This measures whether retrieval finds a function's call-graph neighbours. It does not measure final review accuracy, and its effect on reviews needs Static + LLM vs Static + LLM + RAG on identical samples.
- 4 retrieval runs are saved, on 138, 277, 316, 381 queries. The repository grew between them, so they are not comparable. This table shows the latest.
- Recall@3 and the other Hit@k cut-offs are in run 20261012T163120Z_retrieval_src.

Source runs: `20261012T163120Z_retrieval_src`

## 5. Risk ranking

### Risk-based hunk ranking vs baselines

Status: Complete | Baseline not beaten

> **Size-only ranking outperforms Risk model v2 on the current test set, on ROC-AUC and on precision at every cut-off. Do not describe risk ranking as beating the baseline.**

CodeReviewer cls hunks (test split, Python): does ranking by risk put the hunks a human commented on first?

- **hunks:** 4194
- **failed:** 2
- **commented base rate:** 0.4845
- **commented if level high:** 0.7378
- **commented if level low:** 0.4623
- **configuration:** static analysis only (the ranking must be cheap enough for every change)

| Method | ROC-AUC | Precision@Top5% | Precision@Top10% | Precision@Top25% | n | failed | runs |
|---|---|---|---|---|---|---|---|
| Random (expected value) | 0.500 | N/A | 0.484 | N/A | 4194 | - | 1 |
| Size only (changed lines) | 0.651 | 0.823 | 0.792 | 0.677 | 4194 | - | 1 |
| Finding score only (static findings) | 0.407 | 0.282 | 0.224 | 0.321 | 4194 | - | 1 |
| Risk v1 (hand-set points) | 0.431 | 0.230 | 0.305 | 0.353 | 4194 | - | 1 |
| Risk model v2 (calibrated, shipped) | 0.644 | 0.761 | 0.733 | 0.662 | 4194 | - | 1 |

Observations (computed from the numbers above):
- Size only has a higher ROC-AUC than Risk model v2 (0.651 vs 0.644).
- Size only has a higher Precision@Top10% than Risk model v2 (0.792 vs 0.733).

- v2 weights were fitted on the validation split. The test split appears in 4 saved runs, and the weights were not changed after seeing test results.
- That validation fit predates the line-ending fix, so it used inflated sizes for some samples. Re-fitting on a corrected validation run has not been done.

Source runs: `20261012T163944Z_hunkrisk_cls_test_n4196`

## 6a. Efficiency: Gemini

### File-size benchmark: gemini-3.6-flash

Status: Incomplete | Gemini: gemini-3.6-flash

> **Incomplete: 8 of 90 planned runs finished, and 0 of 5 rounds. No complete run for: large. This is not the file-size benchmark result.**

Times are means over complete runs only. Partial, failed and skipped runs are counted and never enter a time. Status comes from results.csv.

- **run:** 20261106T162014Z_runtime_full_r5
- **planned:** 9 files x 5 rounds x cold and warm = 90 runs
- **run status:** 8 complete, 3 partial, 0 failed, 79 skipped
- **files measured:** 6 of 9 (4 with a complete run)
- **rounds:** 1 reached, 0 of 5 finished
- **llm.max_tokens:** 4096

| Method | Runs Complete | Runs Partial | Runs Failed | Runs Skipped | Total | Static | RAG | LLM | Quota wait | Tokens in | Tokens out | Reasoning tokens | Cache hit rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Small, cold | 3 | 0 | 0 | 12 | 20.82 | 2.28 | 0.013 | 17.42 | 0.00 | 2238 | 909 | N/A | 0.00 |
| Small, warm | 3 | 0 | 0 | 12 | 0.12 | 0.02 | 0.012 | 0.00 | 0.00 | N/A | N/A | N/A | 1.00 |
| Medium, cold | 1 | 2 | 0 | 12 | 23.08 | 2.35 | 0.013 | 20.44 | 0.00 | 2689 | 192 | N/A | 0.00 |
| Medium, warm | 1 | 1 | 0 | 13 | 0.09 | 0.02 | 0.013 | 0.00 | 0.00 | N/A | N/A | N/A | 1.00 |
| Large, cold | 0 | 0 | 0 | 15 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| Large, warm | 0 | 0 | 0 | 15 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |

N/A:
- Small, cold / Reasoning tokens: not recorded for this run
- Small, warm / Tokens in, Tokens out, Reasoning tokens: no LLM call: answered from the cache
- Medium, cold / Reasoning tokens: not recorded for this run
- Medium, warm / Tokens in, Tokens out, Reasoning tokens: no LLM call: answered from the cache
- Large, cold / Total, Static, RAG, LLM, Quota wait, Tokens in, Tokens out, Reasoning tokens, Cache hit rate: no complete run
- Large, warm / Total, Static, RAG, LLM, Quota wait, Tokens in, Tokens out, Reasoning tokens, Cache hit rate: no complete run

- These runs used llm.max_tokens = 4096, since raised to 16,384 after replies were cut off on larger units. Rerun before quoting any time.

Source runs: `20261106T162014Z_runtime_full_r5`

## 6b. Efficiency: static analysis only

### File-size benchmark: no LLM

Status: Complete | No LLM

Times are means over complete runs only. Partial, failed and skipped runs are counted and never enter a time. Status comes from results.csv.

- **run:** 20261106T122017Z_runtime_static_only_r5
- **planned:** 9 files x 5 rounds x cold and warm = 90 runs
- **run status:** 90 complete, 0 partial, 0 failed, 0 skipped
- **files measured:** 9 of 9 (9 with a complete run)
- **rounds:** 5 reached, 5 of 5 finished

| Method | Runs Complete | Runs Partial | Runs Failed | Runs Skipped | Total | Static | RAG |
|---|---|---|---|---|---|---|---|
| Small, cold | 15 | 0 | 0 | 0 | 2.42 | 2.35 | N/A |
| Small, warm | 15 | 0 | 0 | 0 | 0.07 | 0.02 | N/A |
| Medium, cold | 15 | 0 | 0 | 0 | 2.56 | 2.45 | N/A |
| Medium, warm | 15 | 0 | 0 | 0 | 0.12 | 0.03 | N/A |
| Large, cold | 15 | 0 | 0 | 0 | 4.69 | 4.35 | N/A |
| Large, warm | 15 | 0 | 0 | 0 | 0.39 | 0.07 | N/A |

N/A:
- Small, cold / RAG: not recorded for this run
- Small, warm / RAG: not recorded for this run
- Medium, cold / RAG: not recorded for this run
- Medium, warm / RAG: not recorded for this run
- Large, cold / RAG: not recorded for this run
- Large, warm / RAG: not recorded for this run

Source runs: `20261106T122017Z_runtime_static_only_r5`

## 6c. Efficiency: historical timing (not Gemini)

### Time per review: planted_repo (median of 3 runs, seconds)

Status: Historical: Groq (openai/gpt-oss-120b)

Fixed input, interleaved repeats, concurrency 1, fresh vector store per run, one untimed warm-up; incomplete runs excluded.

- **input:** planted_repo
- **files:** 8
- **lines reviewed:** 146
- **LLM review units:** 4
- **provider / model:** groq / openai/gpt-oss-120b
- **repeats:** 3
- **hardware:** AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 6.10 | 5.99 | 0.00 | 0.00 | 0.002 | 0.10 | 0.02 | 6.10 | 3 | 0 | 3 | - |
| LLM Only | ✗ | ✓ | ✗ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | - | - | not run | ? |
| Static + LLM | ✓ | ✓ | ✗ | 186.75 | 5.02 | 0.00 | 18.50 | 0.004 | 0.11 | 164.80 | 24.92 | 3 | 0 | 3 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 228.34 | 5.53 | 0.31 | 18.53 | 0.005 | 0.11 | 204.53 | 24.86 | 3 | 0 | 3 | openai/gpt-oss-120b |

N/A:
- LLM Only / all metrics: not included in the latest timing run

To run:
- LLM Only: `python -m marl_agents.cli eval timing --repeats 3 --config configs/gemini.yaml`

Observations (computed from the numbers above):
- RAG overhead -0.3% (median active time 24.92s without -> 24.86s with RAG); RAG's own cost 0.31s.

- Timing statistics (mean, median, min, max) per component are in run 20261012T090910Z_timing_r3; the table shows the median, ranges on hover.

Source runs: `20261012T090910Z_timing_r3`

### Time per review: order_service_file (median of 3 runs, seconds)

Status: Historical: Groq (openai/gpt-oss-120b)

Fixed input, interleaved repeats, concurrency 1, fresh vector store per run, one untimed warm-up; incomplete runs excluded.

- **input:** order_service_file
- **files:** 1
- **lines reviewed:** 114
- **LLM review units:** 1
- **provider / model:** groq / openai/gpt-oss-120b
- **repeats:** 3
- **hardware:** AMD64 Family 25 Model 80 Stepping 0, AuthenticAMD

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 5.49 | 5.43 | 0.00 | 0.00 | 0.001 | 0.05 | 0.01 | 5.49 | 3 | 0 | 3 | - |
| LLM Only | ✗ | ✓ | ✗ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | - | - | not run | ? |
| Static + LLM | ✓ | ✓ | ✗ | 60.65 | 5.37 | 0.00 | 5.92 | 0.002 | 0.06 | 49.29 | 11.37 | 2 | 1 | 2 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 121.35 | 5.22 | 0.16 | 9.89 | 0.002 | 0.06 | 105.25 | 21.87 | 3 | 0 | 3 | openai/gpt-oss-120b |

N/A:
- LLM Only / all metrics: not included in the latest timing run

To run:
- LLM Only: `python -m marl_agents.cli eval timing --repeats 3 --config configs/gemini.yaml`

Observations (computed from the numbers above):
- RAG overhead +92.4% (median active time 11.37s without -> 21.87s with RAG); RAG's own cost 0.16s.
- Median LLM JSON retries differ (0 without vs 1 with RAG): a retry repeats the whole LLM call, so retries, not retrieval, explain most of this overhead.

- Timing statistics (mean, median, min, max) per component are in run 20261012T090910Z_timing_r3; the table shows the median, ranges on hover.

Source runs: `20261012T090910Z_timing_r3`

### Time per review in the planted-benchmark runs (seconds)

Status: Gemini: gemini-3.6-flash

The same repository reviewed under each configuration (the runs in section 1). One measurement per run; repeated runs show the mean.

- **input:** planted fixture repository (8 files, 6 Python)

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 9.75 | 9.68 | 0.00 | 0.00 | 0.002 | N/A | 0.06 | 9.75 | - | - | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 42.82 | 0.00 | 0.00 | 42.78 | 0.005 | N/A | 0.03 | 42.82 | - | - | 1 | gemini-3.6-flash |
| Static + LLM | ✓ | ✓ | ✗ | 60.56 | 5.79 | 0.00 | 54.73 | 0.005 | N/A | 0.03 | 60.56 | - | - | 1 | gemini-3.6-flash |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 99.50 | 5.76 | 0.33 | 90.44 | 0.005 | N/A | 2.96 | 99.50 | - | - | 1 | gemini-3.6-flash |

N/A:
- Static Only / Reports: benchmark runs do not write reports
- LLM Only / Reports: benchmark runs do not write reports
- Static + LLM / Reports: benchmark runs do not write reports
- Static + LLM + RAG / Reports: benchmark runs do not write reports

Fairness checks:
- ✓ Same input: planted fixture repository for every row

Observations (computed from the numbers above):
- RAG overhead +64.3% on active time (n = 1 run(s) per configuration; a single run is noisy, the timing benchmark is the fair measure).
- Of that difference, retrieval itself took 0.33s; LLM inference took +35.71s more with RAG (longer prompts carrying the context).

Source runs: `20261108T055008Z_planted_static_only`, `20261108T055018Z_planted_llm_only`, `20261108T055101Z_planted_static_llm`, `20261108T055201Z_planted_static_llm_rag`

## Supplementary

### Supplementary comment usefulness evaluation (LLM judge)

Status: Preliminary | Historical: Groq (reviewer and judge)

Blind, reference-free 1-5 ratings of the agent's and the human's comment on the same diff. Supplementary only: not a primary result.

- **judge model:** openai/gpt-oss-20b
- **reviewer model:** qwen/qwen3.8-27b
- **source run:** 20261005T120433Z_codereviewer_msg_test_full_n40
- **comments judged:** 64
- **diffs where the agent wrote no comment:** 8

| Method | Relevance (1-5) | Informativeness (1-5) | n | failed | runs |
|---|---|---|---|---|---|
| Agent comment | 4.71 | 4.64 | 28 | - | 1 |
| Human reviewer comment | 3.67 | 3.00 | 36 | - | 1 |

- Limitations: a single LLM judge (possible self-preference and verbosity bias); small sample; the agent's comments are longer than human ones, which judges tend to reward; judge-human agreement must be measured with the human rating kit before citing.

Source runs: `20261005T154602Z_usefulness_codereviewer_msg_test_full_n40`

## Metric definitions

| Metric | Definition | Scale | Better |
|---|---|---|---|
| Precision | TP / (TP + FP) | 0-1 | higher |
| Recall | TP / (TP + FN) | 0-1 | higher |
| F1 | 2 x Precision x Recall / (Precision + Recall) | 0-1 | higher |
| Issue recall | Labelled issues found / all labelled issues (any category). | 0-1 | higher |
| Defect precision | Correct defect findings / all defect findings. Style and documentation findings are not in the answer key, so they are not counted. | 0-1 | higher |
| F1 (mixed basis) | Harmonic mean of defect precision and issue recall. The two have different denominators, so this is not a standard F1. | 0-1 | higher |
| ROC-AUC | Probability that a randomly chosen positive case is scored above a randomly chosen negative one (Mann-Whitney U; ties count 1/2): ranking quality across all thresholds. 0.5 = chance. | 0-1 | higher |
| Accuracy | (TP + TN) / N | 0-1 | higher |
| BLEU-4 | Smoothed sentence BLEU-4 (Lin & Och 2004 +1 smoothing for n >= 2), averaged over samples, x100 (CodeReviewer convention). | 0-100 | higher |
| ROUGE-L | Longest-common-subsequence F1 of word tokens, averaged over samples, x100. | 0-100 | higher |
| chrF | Character 1-6-gram F-score (beta = 2, Popovic 2015), averaged over samples, x100. | 0-100 | higher |
| Coverage | Share of diffs for which the agent produced a comment. | 0-1 | higher |
| Recall@10 | Share of a query's relevant chunks (its callees in the AST call graph) found in the top 10 retrieved; averaged over queries. | 0-1 | higher |
| MRR | Mean over queries of 1 / rank of the first relevant chunk. | 0-1 | higher |
| Precision@Top10% | Of the 10% of hunks ranked riskiest, the share a human reviewer commented on. | 0-1 | higher |
| Time | Wall-clock seconds measured with time.perf_counter(). | seconds | lower |
| Rating | Mean 1-5 rating by the LLM judge (supplementary). | 1-5 | higher |
