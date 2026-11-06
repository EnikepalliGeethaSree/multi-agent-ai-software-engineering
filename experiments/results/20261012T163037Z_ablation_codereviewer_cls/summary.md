# Baseline comparison (codereviewer_cls, group abl-20261012T161828Z)

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
| Static + LLM + RAG | ✓ | ✓ | ✓ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | - | - | not run | ? |

N/A:
- Static Only / ADJUSTED Precision, ADJUSTED F1: undefined on these samples (zero denominator or one class only)
- Static + LLM + RAG / all metrics: no saved run

To run:
- Static + LLM + RAG: `python -m marl_agents.cli eval codereviewer --task cls --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/groq.yaml`

Fairness checks:
- ✓ Same samples: 3 samples evaluated by every configuration (10 requested; reference run 20261012T162634Z_codereviewer_cls_test_static_llm_n10)
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'flag_threshold': 'at least one finding of severity >= low', 'score': 'highest finding priority (severity rank + confidence) / 5', 'adjusted_excludes_rules': ['F401', 'F403', 'F405', 'F811', 'F821']}
- ✓ Run together (one ablation group): abl-20261012T161828Z

Observations (computed from the numbers above):
- Static + LLM has a higher F1 (raw) than Static Only (0.800 vs 0.000).
- LLM Only has a higher F1 (raw) than Static Only (0.800 vs 0.000).
- Static + LLM has a higher ROC-AUC (raw) than Static Only (1.000 vs 0.000).
- LLM Only has a higher ROC-AUC (raw) than Static Only (0.500 vs 0.000).
- Static Only: raw ROC-AUC 0.000 is below chance (0.5).
- LLM Only: raw ROC-AUC 0.500 is at chance (0.5).
- Static + LLM: raw ROC-AUC 1.000 is above chance (0.5).

- RAW counts every finding. ADJUSTED drops the rules that cannot be judged from one hunk (imports/names defined in the commit's other hunks); both are always reported, neither replaces the other.
- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task cls --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/groq.yaml
- n = 3: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).

Source runs: `20261012T161828Z_codereviewer_cls_test_static_only_n10`, `20261012T161832Z_codereviewer_cls_test_llm_only_n10`, `20261012T162634Z_codereviewer_cls_test_static_llm_n10`
