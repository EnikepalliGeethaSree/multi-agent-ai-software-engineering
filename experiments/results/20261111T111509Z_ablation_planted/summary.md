# Baseline comparison (planted, group abl-20261111T111100Z)

### Planted-issue benchmark: detection by configuration

Status: Complete | Small benchmark (n = 17) | Historical: Groq (openai/gpt-oss-120b)

> **Small benchmark: 17 issues written by the project team. It is a regression check, and a score of 1.000 is not evidence of 100% bug detection in real code.**

17 hand-labelled issues in a fixture repository (16 detectable by a rule, 1 needing semantic reasoning) plus a clean negative-control file.

- **answer key:** tests/fixtures/repos/planted_expected.json (17 issues)
- **negative control:** shop/utils.py
- **matching:** same file, start within +-2 lines, compatible category
- **precision counts:** defect findings only (bug, security, error handling, edge case)

| Configuration | Static | LLM | RAG | Labelled issues Issue recall | Labelled issues Found | Labelled issues Missed | Labelled issues Rule-detectable recall | Labelled issues Semantic recall | Defect findings Precision | Defect findings Correct | Defect findings False positives | Defect findings FP in clean file | Other F1 (mixed basis) | Other ROC-AUC | Other Mean line error | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 0.941 ± 0.000 | 16 ± 0 | 1 ± 0 | 1.000 ± 0.000 | 0.000 ± 0.000 | 1.000 ± 0.000 | 13 ± 0 | 0 ± 0 | 0 ± 0 | 0.970 ± 0.000 | N/A | 0.00 ± 0.00 | 17 | 0 | 3 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.667 ± 0.034 | 11 ± 1 | 6 ± 1 | 0.646 ± 0.036 | 1.000 ± 0.000 | 1.000 ± 0.000 | 11 ± 1 | 0 ± 0 | 0 ± 0 | 0.800 ± 0.024 | N/A | 0.77 ± 0.24 | 17 | 0 | 3 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 0.980 ± 0.034 | 17 ± 1 | 0 ± 1 | 1.000 ± 0.000 | 0.667 ± 0.577 | 0.954 ± 0.040 | 14 ± 1 | 1 ± 1 | 0 ± 1 | 0.967 ± 0.033 | N/A | 0.26 ± 0.23 | 17 | 0 | 3 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.000 ± 0.000 | 17 ± 0 | 0 ± 0 | 1.000 ± 0.000 | 1.000 ± 0.000 | 1.000 ± 0.000 | 14 ± 0 | 0 ± 0 | 0 ± 0 | 1.000 ± 0.000 | N/A | 0.18 ± 0.16 | 17 | 0 | 3 | openai/gpt-oss-120b |

Values with ± are the mean ± sample standard deviation over repeated runs.

N/A:
- Static Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- LLM Only / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined
- Static + LLM + RAG / Other ROC-AUC: not applicable: the planted suite labels positives only (no scored negative cases), so a ROC curve is undefined

Fairness checks:
- ✓ Same samples (answer key): one fixture repository and answer key for every configuration
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.1'}
- ✓ Fresh LLM calls: every LLM run called the model
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'line_tolerance': 2, 'match': 'same file, start within +-2 lines, compatible category', 'precision_over': 'defect findings (bug, security, error_handling, edge_case)'}
- ✓ Run together (one ablation group): abl-20261111T111100Z

Observations (computed from the numbers above):
- Static + LLM has a higher recall than Static Only (0.980 vs 0.941).
- Static + LLM + RAG has a higher recall than Static + LLM (1.000 vs 0.980).
- Static Only has a higher recall than LLM Only (0.941 vs 0.667).
- Static Only has a higher precision than Static + LLM (1.000 vs 0.954).
- Static + LLM + RAG has a higher precision than Static + LLM (1.000 vs 0.954).
- Static Only and LLM Only have the same precision (1.000).
- Static Only: semantic (LLM-only) issue recall 0.000 (the suite has a single such issue, so this is 0 or 1 per run).
- LLM Only: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM: semantic (LLM-only) issue recall 0.667 (the suite has a single such issue, so this is 0 or 1 per run).
- Static + LLM + RAG: semantic (LLM-only) issue recall 1.000 (the suite has a single such issue, so this is 0 or 1 per run).
- LLM Only on openai/gpt-oss-120b varies between complete runs (20261111: 11/17, 20261111: 11/17, 20261111: 12/17). The table shows the latest, so 1.000 is not a stable result.
- Static + LLM on openai/gpt-oss-120b varies between complete runs (20261111: 17/17, 20261111: 17/17, 20261111: 16/17). The table shows the latest, so 1.000 is not a stable result.
- Static + LLM + RAG on openai/gpt-oss-120b gave the same recall in 3 runs.

Statistics (Wilson 95% intervals, exact McNemar, paired bootstrap):
- A run 1 of 3: issues found 0.941 (16/17; 95% CI 0.730-0.990); defect findings correct 1.000 (13/13; 95% CI 0.772-1.000); false-positive defect findings 0
- A run 2 of 3: issues found 0.941 (16/17; 95% CI 0.730-0.990); defect findings correct 1.000 (13/13; 95% CI 0.772-1.000); false-positive defect findings 0
- A run 3 of 3: issues found 0.941 (16/17; 95% CI 0.730-0.990); defect findings correct 1.000 (13/13; 95% CI 0.772-1.000); false-positive defect findings 0
- B run 1 of 3: issues found 0.647 (11/17; 95% CI 0.413-0.827); defect findings correct 1.000 (11/11; 95% CI 0.741-1.000); false-positive defect findings 0
- B run 2 of 3: issues found 0.647 (11/17; 95% CI 0.413-0.827); defect findings correct 1.000 (11/11; 95% CI 0.741-1.000); false-positive defect findings 0
- B run 3 of 3: issues found 0.706 (12/17; 95% CI 0.469-0.867); defect findings correct 1.000 (12/12; 95% CI 0.758-1.000); false-positive defect findings 0
- C run 1 of 3: issues found 1.000 (17/17; 95% CI 0.816-1.000); defect findings correct 0.933 (14/15; 95% CI 0.702-0.988); false-positive defect findings 1
- C run 2 of 3: issues found 1.000 (17/17; 95% CI 0.816-1.000); defect findings correct 1.000 (14/14; 95% CI 0.785-1.000); false-positive defect findings 0
- C run 3 of 3: issues found 0.941 (16/17; 95% CI 0.730-0.990); defect findings correct 0.929 (13/14; 95% CI 0.685-0.987); false-positive defect findings 1
- D run 1 of 3: issues found 1.000 (17/17; 95% CI 0.816-1.000); defect findings correct 1.000 (14/14; 95% CI 0.785-1.000); false-positive defect findings 0
- D run 2 of 3: issues found 1.000 (17/17; 95% CI 0.816-1.000); defect findings correct 1.000 (14/14; 95% CI 0.785-1.000); false-positive defect findings 0
- D run 3 of 3: issues found 1.000 (17/17; 95% CI 0.816-1.000); defect findings correct 1.000 (14/14; 95% CI 0.785-1.000); false-positive defect findings 0
- A vs B: only A 5, only B 1, both 11, neither 0; exact McNemar p = 0.219 (n = 17) (issues found, latest run each)
- A vs C: only A 0, only C 0, both 16, neither 1; exact McNemar p = 1.000 (n = 17) (issues found, latest run each)
- A vs D: only A 0, only D 1, both 16, neither 0; exact McNemar p = 1.000 (n = 17) (issues found, latest run each)
- B vs C: only B 1, only C 5, both 11, neither 0; exact McNemar p = 0.219 (n = 17) (issues found, latest run each)
- B vs D: only B 0, only D 5, both 12, neither 0; exact McNemar p = 0.062 (n = 17) (issues found, latest run each)
- C vs D: only C 0, only D 1, both 16, neither 0; exact McNemar p = 1.000 (n = 17) (issues found, latest run each)
- Precision is counted per finding (defect-class findings that match an issue / all defect-class findings); recall is counted per issue (issues matched / 17).

- Why 14 correct findings can sit beside 17 issues found: the answer key has 14 defect-class issues and 3 others (quality, maintainability, standards). Found counts issues of every category. Correct counts findings of the defect classes only. They are separate counts, so Correct + Missed need not equal the number of issues.
- Rule-detectable recall covers 16 issues. Semantic recall covers 1, so it can only be 0 or 1 in a run.
- F1 here mixes defect precision and issue recall, which have different denominators. Treat it as a summary of this benchmark, not a standard F1.
- Precision is N/A, not 1.0, when a configuration reports no defect findings at all.
- Run all four together: python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml

Source runs: `20261111T111100Z_planted_static_only`, `20261111T111106Z_planted_llm_only`, `20261111T111123Z_planted_static_llm`, `20261111T111144Z_planted_static_llm_rag`, `20261111T111212Z_planted_static_only`, `20261111T111217Z_planted_llm_only`, `20261111T111237Z_planted_static_llm`, `20261111T111306Z_planted_static_llm_rag`, `20261111T111332Z_planted_static_only`, `20261111T111338Z_planted_llm_only`, `20261111T111358Z_planted_static_llm`, `20261111T111430Z_planted_static_llm_rag`

### Time per review in the planted-benchmark runs (seconds)

Status: Historical: Groq (openai/gpt-oss-120b)

The same repository reviewed under each configuration (the runs in section 1). One measurement per run; repeated runs show the mean.

- **input:** planted fixture repository (8 files, 6 Python)

| Configuration | Static | LLM | RAG | Total | Static | RAG | LLM | Validation | Reports | Other | Active (total - quota wait) | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 5.51 ± 0.21 | 5.49 ± 0.20 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.003 ± 0.001 | N/A | 0.02 ± 0.00 | 5.51 ± 0.21 | - | - | 3 | - |
| LLM Only | ✗ | ✓ | ✗ | 18.37 ± 1.80 | 0.00 ± 0.00 | 0.00 ± 0.00 | 18.32 ± 1.81 | 0.007 ± 0.006 | N/A | 0.03 ± 0.00 | 18.37 ± 1.80 | - | - | 3 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 27.53 ± 5.44 | 5.29 ± 0.48 | 0.00 ± 0.00 | 22.20 ± 5.43 | 0.005 ± 0.000 | N/A | 0.03 ± 0.00 | 27.53 ± 5.44 | - | - | 3 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 30.62 ± 6.27 | 5.26 ± 0.36 | 0.13 ± 0.11 | 24.44 ± 7.22 | 0.010 ± 0.005 | N/A | 0.78 ± 1.23 | 30.62 ± 6.27 | - | - | 3 | openai/gpt-oss-120b |

Values with ± are the mean ± sample standard deviation over repeated runs.

N/A:
- Static Only / Reports: benchmark runs do not write reports
- LLM Only / Reports: benchmark runs do not write reports
- Static + LLM / Reports: benchmark runs do not write reports
- Static + LLM + RAG / Reports: benchmark runs do not write reports

Fairness checks:
- ✓ Same input: planted fixture repository for every row

Observations (computed from the numbers above):
- RAG overhead +11.2% on active time (n = 3 run(s) per configuration; a single run is noisy, the timing benchmark is the fair measure).
- Of that difference, retrieval itself took 0.13s; LLM inference took +2.24s more with RAG (longer prompts carrying the context).

Source runs: `20261111T111100Z_planted_static_only`, `20261111T111106Z_planted_llm_only`, `20261111T111123Z_planted_static_llm`, `20261111T111144Z_planted_static_llm_rag`, `20261111T111212Z_planted_static_only`, `20261111T111217Z_planted_llm_only`, `20261111T111237Z_planted_static_llm`, `20261111T111306Z_planted_static_llm_rag`, `20261111T111332Z_planted_static_only`, `20261111T111338Z_planted_llm_only`, `20261111T111358Z_planted_static_llm`, `20261111T111430Z_planted_static_llm_rag`
