# Baseline comparison (planted, group abl-20261108T055008Z)

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
