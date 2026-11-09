# Baseline comparison (planted, group abl-20261108T074047Z)

### Planted-issue benchmark: detection by configuration

Status: Complete | Small benchmark (n = 17) | Historical: Ollama (qwen2.5-coder:7b)

> **Small benchmark: 17 issues written by the project team. It is a regression check, and a score of 1.000 is not evidence of 100% bug detection in real code.**

17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 needing semantic reasoning) plus a clean negative-control file.

- **answer key:** tests/fixtures/repos/planted_expected.json (17 issues)
- **negative control:** shop/utils.py
- **matching:** same file, start within +-2 lines, compatible category
- **precision counts:** defect findings only (bug, security, error handling, edge case)

| Configuration | Static | LLM | RAG | Labelled issues Issue recall | Labelled issues Found | Labelled issues Missed | Labelled issues Rule-detectable recall | Labelled issues Semantic recall | Defect findings Precision | Defect findings Correct | Defect findings False positives | Defect findings FP in clean file | Other F1 (mixed basis) | Other ROC-AUC | Other Mean line error | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.941 | 16 | 1 | 1.000 | 0.000 | 1.000 | 13 | 0 | 0 | 0.970 | N/A | 0.00 | 17 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.294 | 5 | 12 | 0.312 | 0.000 | 1.000 | 5 | 0 | 0 | 0.455 | N/A | 0.00 | 17 | 0 | 1 | qwen2.5-coder:7b |
| Static + LLM | ✓ | ✓ | ✗ | 0.941 | 16 | 1 | 1.000 | 0.000 | 0.929 | 13 | 1 | 0 | 0.935 | N/A | 0.00 | 17 | 0 | 1 | qwen2.5-coder:7b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 0.941 | 16 | 1 | 1.000 | 0.000 | 0.929 | 13 | 1 | 0 | 0.935 | N/A | 0.00 | 17 | 0 | 1 | qwen2.5-coder:7b |

N/A:
- Static Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- LLM Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM + RAG / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined

Fairness checks:
- ✓ Same samples (answer key): one fixture repository and answer key for every configuration
- ✓ Same LLM model: qwen2.5-coder:7b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.1'}
- ✓ Fresh LLM calls: every LLM run called the model
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'line_tolerance': 2, 'match': 'same file, start within +-2 lines, compatible category', 'precision_over': 'defect findings (bug, security, error_handling, edge_case)'}
- ✓ Run together (one ablation group): abl-20261108T074047Z

Observations (computed from the numbers above):
- Static Only and Static + LLM have the same recall (0.941).
- Static + LLM and Static + LLM + RAG have the same recall (0.941).
- Static Only has a higher recall than LLM Only (0.941 vs 0.294).
- Static Only has a higher precision than Static + LLM (1.000 vs 0.929).
- Static + LLM and Static + LLM + RAG have the same precision (0.929).
- Static Only and LLM Only have the same precision (1.000).
- Static Only: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- LLM Only: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM + RAG: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).

- Why 14 correct findings can sit beside 17 issues found: the answer key has 14 defect-class issues and 3 others (quality, maintainability, standards). Found counts issues of every category. Correct counts findings of the defect classes only. They are separate counts, so Correct + Missed need not equal the number of issues.
- Rule-detectable recall covers 16 issues. Semantic recall covers 1, so it can only be 0 or 1 in a run.
- F1 here mixes defect precision and issue recall, which have different denominators. Treat it as a summary of this benchmark, not a standard F1.
- Precision is N/A, not 1.0, when a configuration reports no defect findings at all.
- Run all four together: python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml

Source runs: `20261108T074047Z_planted_static_only`, `20261108T074052Z_planted_llm_only`, `20261108T074755Z_planted_static_llm`, `20261108T075847Z_planted_static_llm_rag`

### Time per review in the planted-benchmark runs (seconds)

Status: Historical: Ollama (qwen2.5-coder:7b)

The same repository reviewed under each configuration (the runs in section 1). One measurement per run; repeated runs show the mean.

- **input:** planted fixture repository (8 files, 6 Python)

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 5.39 | 5.37 | 0.00 | 0.00 | 0.002 | N/A | 0.02 | 5.39 | - | - | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 422.13 | 0.00 | 0.00 | 422.10 | 0.002 | N/A | 0.03 | 422.13 | - | - | 1 | qwen2.5-coder:7b |
| Static + LLM | ✓ | ✓ | ✗ | 651.65 | 5.89 | 0.00 | 645.73 | 0.005 | N/A | 0.02 | 651.65 | - | - | 1 | qwen2.5-coder:7b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 822.73 | 5.62 | 0.41 | 814.55 | 0.005 | N/A | 2.14 | 822.73 | - | - | 1 | qwen2.5-coder:7b |

N/A:
- Static Only / Reports: benchmark runs do not write reports
- LLM Only / Reports: benchmark runs do not write reports
- Static + LLM / Reports: benchmark runs do not write reports
- Static + LLM + RAG / Reports: benchmark runs do not write reports

Fairness checks:
- ✓ Same input: planted fixture repository for every row

Observations (computed from the numbers above):
- RAG overhead +26.3% on active time (n = 1 run(s) per configuration; a single run is noisy, the timing benchmark is the fair measure).
- Of that difference, retrieval itself took 0.41s; LLM inference took +168.83s more with RAG (longer prompts carrying the context).

Source runs: `20261108T074047Z_planted_static_only`, `20261108T074052Z_planted_llm_only`, `20261108T074755Z_planted_static_llm`, `20261108T075847Z_planted_static_llm_rag`
