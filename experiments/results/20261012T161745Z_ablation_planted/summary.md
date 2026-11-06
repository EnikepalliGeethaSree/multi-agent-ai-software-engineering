# Baseline comparison (planted, group abl-20261012T161020Z)

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
- Run all four together: python -m marl_agents.cli eval ablation --benchmark planted --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/groq.yaml

Source runs: `20261012T161020Z_planted_static_only`, `20261012T161026Z_planted_llm_only`, `20261012T161133Z_planted_static_llm`, `20261012T161434Z_planted_static_llm_rag`

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

Source runs: `20261012T161020Z_planted_static_only`, `20261012T161026Z_planted_llm_only`, `20261012T161133Z_planted_static_llm`, `20261012T161434Z_planted_static_llm_rag`
