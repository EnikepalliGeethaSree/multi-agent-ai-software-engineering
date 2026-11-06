# Code Review Agent: baseline comparison

- Agent-level benchmark evaluation of the Code Review Agent on its own. These numbers are not system-level results of the five-agent platform (SWE-bench Lite resolve rate), which is not built yet.
- Configuration D (Static + LLM + RAG) is the shipped Code Review Agent; A-C are ablations that switch one component off.
- Every value comes from a saved run in experiments/results/ (run ids are listed per row). A configuration without a valid run is N/A with the command that produces it. Runs made with the offline mock LLM test the pipeline and are never shown as results.

### Code Review evaluation summary

Detection quality of each configuration. Planted issues: ROC-AUC is not applicable (positives only). CodeReviewer: raw metrics on the paired sample set; adjusted metrics are in section 2.

- **planted issues:** 17 labelled issues
- **CodeReviewer samples (paired):** 3
- **minimum paired n for a headline:** 30

| Configuration | Static | LLM | RAG | Planted issues Precision | Planted issues Recall | Planted issues F1 | CodeReviewer classification (raw) Precision | CodeReviewer classification (raw) Recall | CodeReviewer classification (raw) F1 | CodeReviewer classification (raw) ROC-AUC | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.000 | 0.941 | 0.970 | N/A | N/A | N/A | N/A | - |
| LLM Only | ✗ | ✓ | ✗ | 1.000 | 0.588 | 0.741 | N/A | N/A | N/A | N/A | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 1.000 | 1.000 | 1.000 | N/A | N/A | N/A | N/A | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.000 | 1.000 | 1.000 | N/A | N/A | N/A | N/A | openai/gpt-oss-120b |

N/A:
- Static Only / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- LLM Only / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- Static + LLM / CodeReviewer classification (raw) (all): paired CodeReviewer sample too small for a headline (n = 3 < 30); see section 2
- Static + LLM + RAG / CodeReviewer classification (raw) (all): incomplete

- Model, sample counts, failures and the exact runs behind every cell are in the benchmark sections below.

Source runs: `20261012T161020Z_planted_static_only`, `20261012T161026Z_planted_llm_only`, `20261012T161133Z_planted_static_llm`, `20261012T161434Z_planted_static_llm_rag`

## 1. Planted issues

### Planted-issue benchmark: detection by configuration

17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 needing semantic reasoning) plus a clean negative-control file.

- **answer key:** tests/fixtures/repos/planted_expected.json (17 issues)
- **negative control:** shop/utils.py
- **matching:** same file, start within +-2 lines, compatible category
- **precision counts:** defect findings only (bug, security, error handling, edge case)

| Configuration | Static | LLM | RAG | Precision | Recall | F1 | ROC-AUC | TP | FP | FN | Recall (static-detectable) | Recall (semantic / LLM-only) | FP in clean file | Mean line error | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.000 | 0.941 | 0.970 | N/A | 13 | 0 | 1 | 1.000 | 0.000 | 0 | 0.00 | 17 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 1.000 | 0.588 | 0.741 | N/A | 10 | 0 | 7 | 0.562 | 1.000 | 0 | 0.90 | 17 | 0 | 1 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 1.000 | 1.000 | 1.000 | N/A | 14 | 0 | 0 | 1.000 | 1.000 | 0 | 0.00 | 17 | 0 | 1 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.000 | 1.000 | 1.000 | N/A | 14 | 0 | 0 | 1.000 | 1.000 | 0 | 0.06 | 17 | 0 | 1 | openai/gpt-oss-120b |

N/A:
- Static Only / ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- LLM Only / ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM / ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM + RAG / ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined

Fairness checks:
- ✓ Same samples (answer key): one fixture repository and answer key for every configuration
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'line_tolerance': 2, 'match': 'same file, start within +-2 lines, compatible category', 'precision_over': 'defect findings (bug, security, error_handling, edge_case)'}
- ✓ Run together (one ablation group): abl-20261012T161020Z

Observations (computed from the numbers above):
- Static + LLM has a higher recall than Static Only (1.000 vs 0.941).
- Static + LLM and Static + LLM + RAG have the same recall (1.000).
- Static Only has a higher recall than LLM Only (0.941 vs 0.588).
- Static Only and Static + LLM have the same precision (1.000).
- Static + LLM and Static + LLM + RAG have the same precision (1.000).
- Static Only and LLM Only have the same precision (1.000).
- Static Only: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- LLM Only: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM + RAG: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).

- Precision TP = defect findings that match a planted issue; recall TP = planted issues detected (the project's existing definitions).
- Precision is N/A, not 1.0, when a configuration reports no defect findings at all.
- Run all four together: python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml

Source runs: `20261012T161020Z_planted_static_only`, `20261012T161026Z_planted_llm_only`, `20261012T161133Z_planted_static_llm`, `20261012T161434Z_planted_static_llm_rag`

## 2. CodeReviewer classification

### CodeReviewer: does this change need a review comment? (classification)

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **requested samples:** 10
- **samples in every row:** 3
- **sampling seed:** 42
- **limit:** 10
- **flagged:** at least one finding of severity >= low
- **score (ROC-AUC):** highest finding priority / 5
- **ADJUSTED:** excludes F401, F403, F405, F811, F821

| Configuration | Static | LLM | RAG | RAW Precision | RAW Recall | RAW F1 | RAW ROC-AUC | ADJUSTED Precision | ADJUSTED Recall | ADJUSTED F1 | ADJUSTED ROC-AUC | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.000 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A | 0.500 | 3 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.667 | 1.000 | 0.800 | 0.500 | 0.667 | 1.000 | 0.800 | 0.500 | 3 | 0 | 1 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 0.667 | 1.000 | 0.800 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 3 | 7 | 1 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 0 | 10 | incomplete | openai/gpt-oss-120b |

N/A:
- Static Only / ADJUSTED Precision, ADJUSTED F1: undefined on these samples (zero denominator or one class only)
- Static + LLM + RAG / all metrics: every sample failed in run 20261012T163034Z_codereviewer_cls_test_static_llm_rag_n10 (llm: 10); nothing to score

To run:
- Static + LLM + RAG: `python -m marl_agents.cli eval codereviewer --task cls --limit 10 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml`

Fairness checks:
- ✓ Same samples: 3 samples evaluated by every configuration (10 requested; reference run 20261012T162634Z_codereviewer_cls_test_static_llm_n10)
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'flag_threshold': 'at least one finding of severity >= low', 'score': 'highest finding priority (severity rank + confidence) / 5', 'adjusted_excludes_rules': ['F401', 'F403', 'F405', 'F811', 'F821']}
- ✓ Run together (one ablation group): abl-20261012T161828Z

- RAW counts every finding. ADJUSTED drops the rules that cannot be judged from one hunk (imports/names defined in the commit's other hunks); both are always reported, neither replaces the other.
- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task cls --limit 10 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 3: far too few samples for any conclusion; this table only shows that the pipeline runs end to end.

Source runs: `20261012T161828Z_codereviewer_cls_test_static_only_n10`, `20261012T161832Z_codereviewer_cls_test_llm_only_n10`, `20261012T162634Z_codereviewer_cls_test_static_llm_n10`, `20261012T163034Z_codereviewer_cls_test_static_llm_rag_n10`

### Static Only on the full Python test split (n = 4195)

Static analysis is cheap enough to run on every sample; LLM configurations are limited by API quota, so they are compared on the subset above.

- **dataset:** CodeReviewer, test split, Python only (all samples)

| Configuration | Static | LLM | RAG | RAW Precision | RAW Recall | RAW F1 | RAW ROC-AUC | ADJUSTED Precision | ADJUSTED Recall | ADJUSTED F1 | ADJUSTED ROC-AUC | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.384 | 0.266 | 0.314 | 0.417 | 0.592 | 0.167 | 0.261 | 0.539 | 4195 | 1 | 1 | - |

Source runs: `20261012T163153Z_codereviewer_cls_test_static_only_n4196`

## 3. Review comment generation

### CodeReviewer: review comment generation

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
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
- ✓ Same samples: 36 samples evaluated by every configuration (40 requested; reference run 20261005T120433Z_codereviewer_msg_test_full_n40)
- ✓ Same LLM model: qwen/qwen3.8-27b
- ✓ Same temperature: 0.0
- ? Same prompt versions: prompt versions not recorded
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'} (1 run(s) did not record it)
- ✗ Run together (one ablation group): separate runs

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 36: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).

Source runs: `20261005T120433Z_codereviewer_msg_test_full_n40`, `20261012T163624Z_codereviewer_msg_test_static_only_n1403`

### Static Only on the full Python test split (n = 1403)

Static analysis is cheap enough to run on every sample; LLM configurations are limited by API quota, so they are compared on the subset above.

- **dataset:** CodeReviewer, test split, Python only (all samples)

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.18 | 3.03 | 4.83 | 0.281 | 1403 | 0 | 1 | - |

Source runs: `20261012T163624Z_codereviewer_msg_test_static_only_n1403`

## 4. RAG retrieval

### RAG retrieval vs random retrieval

Self-supervised from the AST call graph: for each function, the relevant chunks are those containing the functions it calls; the query is the function's own chunk.

- **repository:** src
- **queries:** 381
- **chunks:** 665
- **cut-offs evaluated (k):** [1, 3, 5, 10]
- **embedding model:** hashing
- **review-time retrieval:** top_k = 6 similar chunks + guideline_k = 2 guideline chunks per review unit
- **random seed:** 42

| Method | Recall@10 | MRR | n | failed | runs |
|---|---|---|---|---|---|
| Random baseline | 0.012 | 0.020 | 381 | - | 1 |
| RAG (hashing embedder) | 0.365 | 0.312 | 381 | - | 1 |

Observations (computed from the numbers above):
- RAG (hashing) has a higher Recall@10 than random (0.365 vs 0.012).

- Retrieval is measured on its own; its effect on review quality is configuration C vs D in the detection tables.
- Other cut-offs (Recall@1/3/5, Hit@k, nDCG@10) are in run 20261012T163120Z_retrieval_src.

Source runs: `20261012T163120Z_retrieval_src`

## 5. Risk ranking

### Risk-based hunk ranking vs baselines

CodeReviewer cls hunks (test split, Python): does ranking by risk put the hunks a human commented on first?

- **hunks:** 4194
- **failed:** 2
- **commented base rate:** 0.4845
- **commented if level high:** 0.7378
- **commented if level low:** 0.4623
- **configuration:** static analysis only (the ranking must be cheap enough for every change)

| Method | ROC-AUC | Precision@Top10% | n | failed | runs |
|---|---|---|---|---|---|
| Random (expected value) | 0.500 | 0.484 | 4194 | - | 1 |
| Size only (changed lines) | 0.651 | 0.792 | 4194 | - | 1 |
| Finding score only (static findings) | 0.407 | 0.224 | 4194 | - | 1 |
| Risk v1 (hand-set points) | 0.431 | 0.305 | 4194 | - | 1 |
| Risk model v2 (calibrated, shipped) | 0.644 | 0.733 | 4194 | - | 1 |

Observations (computed from the numbers above):
- Size only has a higher ROC-AUC than Risk model v2 (0.651 vs 0.644).
- Size only has a higher Precision@Top10% than Risk model v2 (0.792 vs 0.733).

- v2 weights were fitted on the validation split; the test split was used once.

Source runs: `20261012T163944Z_hunkrisk_cls_test_n4196`

## 6. Efficiency

### Time per review: planted_repo (median of 3 runs, seconds)

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

The same repository reviewed under each configuration (the runs in section 1). One measurement per run; repeated runs show the mean.

- **input:** planted fixture repository (8 files, 6 Python)

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 5.62 | 5.60 | 0.00 | 0.00 | 0.001 | N/A | 0.02 | 5.62 | - | - | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 67.61 | 0.00 | 0.00 | 15.98 | 0.003 | N/A | 51.63 | 16.00 | - | - | 1 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 180.88 | 5.88 | 0.00 | 16.80 | 0.003 | N/A | 158.20 | 22.69 | - | - | 1 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 190.31 | 5.27 | 0.18 | 19.52 | 0.004 | N/A | 165.34 | 26.53 | - | - | 1 | openai/gpt-oss-120b |

N/A:
- Static Only / Reports: benchmark runs do not write reports
- LLM Only / Reports: benchmark runs do not write reports
- Static + LLM / Reports: benchmark runs do not write reports
- Static + LLM + RAG / Reports: benchmark runs do not write reports

Fairness checks:
- ✓ Same input: planted fixture repository for every row

Observations (computed from the numbers above):
- RAG overhead +16.9% on active time (n = 1 run(s) per configuration; a single run is noisy, the timing benchmark is the fair measure).
- Of that difference, retrieval itself took 0.18s; LLM inference took +2.72s more with RAG (longer prompts carrying the context).

Source runs: `20261012T161020Z_planted_static_only`, `20261012T161026Z_planted_llm_only`, `20261012T161133Z_planted_static_llm`, `20261012T161434Z_planted_static_llm_rag`

## Supplementary

### Supplementary comment usefulness evaluation (LLM judge)

Blind, reference-free 1-5 ratings of the agent's and the human's comment on the same diff. Supplementary only: not a primary result.

- **judge model:** openai/gpt-oss-20b
- **reviewer model:** qwen/qwen3.8-27b
- **source run:** 20261005T120433Z_codereviewer_msg_test_full_n40
- **comments judged:** 64

| Method | Relevance (1-5) | Informativeness (1-5) | n | failed | runs |
|---|---|---|---|---|---|
| Agent comment | 4.71 | 4.64 | 64 | - | 1 |
| Human reviewer comment | 3.67 | 3.00 | 64 | - | 1 |

- Limitations: a single LLM judge (possible self-preference and verbosity bias); small sample; the agent's comments are longer than human ones, which judges tend to reward; judge-human agreement must be measured with the human rating kit before citing.

Source runs: `20261005T154602Z_usefulness_codereviewer_msg_test_full_n40`

## Metric definitions

| Metric | Definition | Scale | Better |
|---|---|---|---|
| Precision | TP / (TP + FP) | 0-1 | higher |
| Recall | TP / (TP + FN) | 0-1 | higher |
| F1 | 2 x Precision x Recall / (Precision + Recall) | 0-1 | higher |
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

---

## Appendix: Code Review Agent: evaluation summary

Generated from saved runs only (`python -m marl_agents.cli eval summary`).

## Results

| Evaluation | Benchmark | Configuration | n | Metric | Result |
|---|---|---|---:|---|---:|
| Planted issues | Planted issues | LLM only (openai/gpt-oss-120b) | 17 | precision | 1.000 |
| Planted issues | Planted issues | LLM only (openai/gpt-oss-120b) | 17 | recall | 0.588 |
| Planted issues | Planted issues | LLM only (openai/gpt-oss-120b) | 17 | f1 | 0.741 |
| Planted issues | Planted issues | static + LLM (openai/gpt-oss-120b), no RAG | 17 | precision | 1.000 |
| Planted issues | Planted issues | static + LLM (openai/gpt-oss-120b), no RAG | 17 | recall | 1.000 |
| Planted issues | Planted issues | static + LLM (openai/gpt-oss-120b), no RAG | 17 | f1 | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-120b) | 17 | precision | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-120b) | 17 | recall | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-120b) | 17 | f1 | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-20b) | 17 | precision | 0.933 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-20b) | 17 | recall | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (openai/gpt-oss-20b) | 17 | f1 | 0.966 |
| Planted issues | Planted issues | static + LLM + RAG (qwen/qwen3.8-27b) | 17 | precision | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (qwen/qwen3.8-27b) | 17 | recall | 1.000 |
| Planted issues | Planted issues | static + LLM + RAG (qwen/qwen3.8-27b) | 17 | f1 | 1.000 |
| Planted issues | Planted issues | static only | 17 | precision | 1.000 |
| Planted issues | Planted issues | static only | 17 | recall | 0.941 |
| Planted issues | Planted issues | static only | 17 | f1 | 0.970 |
| CodeReviewer | CodeReviewer cls (test, Python) | LLM only (openai/gpt-oss-120b) | 10 | precision | 0.625 |
| CodeReviewer | CodeReviewer cls (test, Python) | LLM only (openai/gpt-oss-120b) | 10 | auc | 0.560 |
| CodeReviewer | CodeReviewer cls (test, Python) | LLM only (openai/gpt-oss-120b) | 10 | precision_cross_hunk_rules_excluded | 0.625 |
| CodeReviewer | CodeReviewer cls (test, Python) | LLM only (openai/gpt-oss-120b) | 10 | auc_cross_hunk_rules_excluded | 0.560 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM (openai/gpt-oss-120b), no RAG | 3 | precision | 0.667 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM (openai/gpt-oss-120b), no RAG | 3 | auc | 1.000 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM (openai/gpt-oss-120b), no RAG | 3 | precision_cross_hunk_rules_excluded | 1.000 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM (openai/gpt-oss-120b), no RAG | 3 | auc_cross_hunk_rules_excluded | 1.000 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM + RAG (openai/gpt-oss-120b) | 0 | precision | 0.000 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM + RAG (openai/gpt-oss-120b) | 0 | auc | - |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM + RAG (openai/gpt-oss-120b) | 0 | precision_cross_hunk_rules_excluded | 0.000 |
| CodeReviewer | CodeReviewer cls (test, Python) | static + LLM + RAG (openai/gpt-oss-120b) | 0 | auc_cross_hunk_rules_excluded | - |
| CodeReviewer | CodeReviewer cls (test, Python) | static only | 4195 | precision | 0.384 |
| CodeReviewer | CodeReviewer cls (test, Python) | static only | 4195 | auc | 0.417 |
| CodeReviewer | CodeReviewer cls (test, Python) | static only | 4195 | precision_cross_hunk_rules_excluded | 0.592 |
| CodeReviewer | CodeReviewer cls (test, Python) | static only | 4195 | auc_cross_hunk_rules_excluded | 0.539 |
| CodeReviewer | CodeReviewer msg (test, Python) | static + LLM + RAG (qwen/qwen3.8-27b) | 36 | coverage | 0.778 |
| CodeReviewer | CodeReviewer msg (test, Python) | static + LLM + RAG (qwen/qwen3.8-27b) | 36 | chrf | 13.595 |
| CodeReviewer | CodeReviewer msg (test, Python) | static only | 1403 | coverage | 0.281 |
| CodeReviewer | CodeReviewer msg (test, Python) | static only | 1403 | chrf | 4.832 |
| RAG | Call-graph retrieval (src) | hashing embedder | 381 | recall@10 (hashing) | 0.365 |
| RAG | Call-graph retrieval (src) | hashing embedder | 381 | recall@10 (random baseline) | 0.012 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | precision@top10% risk v2 (calibrated) | 0.733 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | auc risk v2 (calibrated) | 0.644 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | precision@top10% risk v1 (hand-set) | 0.305 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | auc risk v1 (hand-set) | 0.431 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | precision@top10% size only | 0.792 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | auc size only | 0.651 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | precision@top10% random (expected) | 0.484 |
| Risk ranking | CodeReviewer cls hunks (test) | risk v2 vs baselines | 4194 | auc random (expected) | 0.500 |
| Efficiency | order_service_file | llm_no_rag | 2 runs | Total review time (median) | 60.648 s |
| Efficiency | order_service_file | llm_no_rag | 2 runs | Active time, excl. LLM quota waiting (median) | 11.367 s |
| Efficiency | order_service_file | llm_rag | 3 runs | Total review time (median) | 121.354 s |
| Efficiency | order_service_file | llm_rag | 3 runs | Active time, excl. LLM quota waiting (median) | 21.870 s |
| Efficiency | order_service_file | static_only | 3 runs | Total review time (median) | 5.490 s |
| Efficiency | order_service_file | static_only | 3 runs | Active time, excl. LLM quota waiting (median) | 5.490 s |
| Efficiency | planted_repo | llm_no_rag | 3 runs | Total review time (median) | 186.746 s |
| Efficiency | planted_repo | llm_no_rag | 3 runs | Active time, excl. LLM quota waiting (median) | 24.919 s |
| Efficiency | planted_repo | llm_rag | 3 runs | Total review time (median) | 228.339 s |
| Efficiency | planted_repo | llm_rag | 3 runs | Active time, excl. LLM quota waiting (median) | 24.855 s |
| Efficiency | planted_repo | static_only | 3 runs | Total review time (median) | 6.101 s |
| Efficiency | planted_repo | static_only | 3 runs | Active time, excl. LLM quota waiting (median) | 6.101 s |

## Time breakdown

**order_service_file** (median seconds)

| Component | static_only | llm_no_rag | llm_rag |
|---|---:|---:|---:|
| Static analysis | 5.426 | 5.368 | 5.224 |
| RAG retrieval (index + queries) | 0.000 | 0.000 | 0.164 |
| LLM inference | 0.000 | 5.923 | 9.890 |
| Validation | 0.001 | 0.002 | 0.002 |
| Report generation | 0.053 | 0.061 | 0.058 |
| Other / orchestration | 0.011 | 49.294 | 105.252 |
| of which: LLM quota waiting | - | 49.282 | 99.484 |
| **Total** | 5.490 | 60.648 | 121.354 |
| Active time (total - quota waiting) | 5.490 | 11.367 | 21.870 |
| Complete runs | 3 | 2 | 3 |

**planted_repo** (median seconds)

| Component | static_only | llm_no_rag | llm_rag |
|---|---:|---:|---:|
| Static analysis | 5.988 | 5.022 | 5.528 |
| RAG retrieval (index + queries) | 0.000 | 0.000 | 0.311 |
| LLM inference | 0.000 | 18.497 | 18.531 |
| Validation | 0.002 | 0.004 | 0.005 |
| Report generation | 0.095 | 0.108 | 0.107 |
| Other / orchestration | 0.016 | 164.798 | 204.531 |
| of which: LLM quota waiting | - | 161.827 | 204.436 |
| **Total** | 6.101 | 186.746 | 228.339 |
| Active time (total - quota waiting) | 6.101 | 24.919 | 24.855 |
| Complete runs | 3 | 3 | 3 |

## Notes

- Planted issues / LLM only (openai/gpt-oss-120b): precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static + LLM (openai/gpt-oss-120b), no RAG: precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static + LLM + RAG (openai/gpt-oss-120b): precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static + LLM + RAG (openai/gpt-oss-120b): earlier run 20260929T194203Z_planted_full: precision 1.0, recall 1.0, f1 1.0
- Planted issues / static + LLM + RAG (openai/gpt-oss-120b): earlier run 20261012T090444Z_planted_full: precision 1.0, recall 0.941, f1 0.97
- Planted issues / static + LLM + RAG (openai/gpt-oss-20b): precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static + LLM + RAG (qwen/qwen3.8-27b): precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static only: precision over defect findings (bug, security, error handling, edge case)
- Planted issues / static only: earlier run 20260929T193007Z_planted_static_only: precision 1.0, recall 0.941, f1 0.97
- Planted issues / static only: earlier run 20261005T115337Z_planted_static_only: precision 1.0, recall 0.941, f1 0.97
- Planted issues / static only: earlier run 20261012T084950Z_planted_static_only: precision 1.0, recall 0.941, f1 0.97
- CodeReviewer / LLM only (openai/gpt-oss-120b): random subset: n=10 (seed 42), 0 failed
- CodeReviewer / static + LLM (openai/gpt-oss-120b), no RAG: random subset: n=10 (seed 42), 7 failed
- CodeReviewer / static + LLM + RAG (openai/gpt-oss-120b): random subset: n=10 (seed 42), 10 failed
- CodeReviewer / static only: earlier run 20260929T192259Z_codereviewer_cls_test_static_only_n4196: precision 0.384, auc 0.417, precision_cross_hunk_rules_excluded 0.592, auc_cross_hunk_rules_excluded 0.539
- CodeReviewer / static only: earlier run 20261005T115401Z_codereviewer_cls_test_static_only_n4196: precision 0.384, auc 0.417, precision_cross_hunk_rules_excluded 0.592, auc_cross_hunk_rules_excluded 0.539
- CodeReviewer / static only: earlier run 20261012T085023Z_codereviewer_cls_test_static_only_n4196: precision 0.384, auc 0.417, precision_cross_hunk_rules_excluded 0.592, auc_cross_hunk_rules_excluded 0.539
- CodeReviewer / static only: earlier run 20261012T161828Z_codereviewer_cls_test_static_only_n10: precision 0.25, auc 0.28, precision_cross_hunk_rules_excluded 0.5, auc_cross_hunk_rules_excluded 0.52
- CodeReviewer / static + LLM + RAG (qwen/qwen3.8-27b): random subset: n=40 (seed 42), 4 failed
- CodeReviewer / static + LLM + RAG (qwen/qwen3.8-27b): BLEU-4 (approved-deck metric, still computed): 2.136
- CodeReviewer / static only: BLEU-4 (approved-deck metric, still computed): 1.177
- CodeReviewer / static only: earlier run 20260929T192630Z_codereviewer_msg_test_static_only_n1403: coverage 0.281, chrf 4.832
- CodeReviewer / static only: earlier run 20261005T115807Z_codereviewer_msg_test_static_only_n1403: coverage 0.281, chrf 4.832
- CodeReviewer / static only: earlier run 20261012T085436Z_codereviewer_msg_test_static_only_n1403: coverage 0.281, chrf 4.832
- Efficiency / llm_rag: order_service_file: RAG latency overhead +92.4% (11.37s -> 21.87s, median active time); RAG itself 0.16s (0.7%); median JSON retries 0.0 without vs 1.0 with RAG
- Efficiency / llm_rag: planted_repo: RAG latency overhead -0.3% (24.92s -> 24.86s, median active time); RAG itself 0.31s (1.3%); median JSON retries 0.0 without vs 0.0 with RAG

## Source runs

- `20260929T194356Z_planted_full`
- `20260929T194832Z_planted_full`
- `20261005T120433Z_codereviewer_msg_test_full_n40`
- `20261012T090910Z_timing_r3`
- `20261012T161020Z_planted_static_only`
- `20261012T161026Z_planted_llm_only`
- `20261012T161133Z_planted_static_llm`
- `20261012T161434Z_planted_static_llm_rag`
- `20261012T161832Z_codereviewer_cls_test_llm_only_n10`
- `20261012T162634Z_codereviewer_cls_test_static_llm_n10`
- `20261012T163034Z_codereviewer_cls_test_static_llm_rag_n10`
- `20261012T163120Z_retrieval_src`
- `20261012T163153Z_codereviewer_cls_test_static_only_n4196`
- `20261012T163624Z_codereviewer_msg_test_static_only_n1403`
- `20261012T163944Z_hunkrisk_cls_test_n4196`
