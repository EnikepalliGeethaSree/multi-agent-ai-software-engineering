# Classifier ablation on development samples

Provider `gemini`, model `gemini-3.6-flash`, threshold from the model. Dev samples, seed 42. Dev tuned the classifier, so this is not an independent test.

| Measure | Disabled | Prioritize | Gate |
|---|---:|---:|---:|
| Samples compared | 2 | 2 | 2 |
| Review units | 2 | 2 | 2 |
| Units skipped | 0 | 0 | 1 |
| Units protected from gating | 0 | 0 | 0 |
| LLM calls | 2 | 2 | 1 |
| Input tokens | 12397 | 12397 | 5704 |
| Output tokens | 1604 | 1604 | 817 |
| Total time (s) | 44.08 | 35.94 | 15.48 |
| Findings | 2 | 2 | 1 |
| Baseline findings retained | - | 2 | 1 |
| Useful retained (proxy) | - | 0 | 0 |
| Useful in baseline (proxy) | - | 0 | 0 |
| Important missed (proxy) | - | 0 | 0 |
| Important in baseline (proxy) | - | 0 | 0 |
| Static high/critical lost in skipped units | - | 0 | 0 |

Run status by mode: {'disabled': {'complete': 2, 'quota': 1, 'skipped': 12}, 'prioritize': {'complete': 2, 'skipped': 13}, 'gate': {'complete': 3, 'skipped': 12}}.

- Baseline: the same sample with the classifier disabled.
- Retained: a baseline finding with a match (same rule if both have one, else same category, within 3 lines).
- Useful (proxy): severity medium or above, on a change a human commented on.
- Important (proxy): severity high or critical.
- Prioritize reviews the same units as disabled, so its gap from 100% shows LLM run-to-run variation, not lost work.
- These samples are single changes, so prioritize usually has nothing to reorder.
