# Classifier ablation on development samples

Provider `ollama`, model `qwen2.5-coder:7b`, threshold from the model. Dev samples, seed 42. Dev tuned the classifier, so this is not an independent test.

| Measure | Disabled | Prioritize | Gate |
|---|---:|---:|---:|
| Samples compared | 14 | 14 | 14 |
| Review units | 14 | 14 | 14 |
| Units skipped | 0 | 0 | 2 |
| Units protected from gating | 0 | 0 | 4 |
| LLM calls | 14 | 14 | 12 |
| Input tokens | 74894 | 74894 | 64872 |
| Output tokens | 2474 | 2514 | 2337 |
| Total time (s) | 1955.26 | 2004.27 | 1800.58 |
| Findings | 13 | 13 | 14 |
| Baseline findings retained | - | 13 | 13 |
| Useful retained (proxy) | - | 3 | 3 |
| Useful in baseline (proxy) | - | 3 | 3 |
| Important missed (proxy) | - | 0 | 0 |
| Important in baseline (proxy) | - | 6 | 6 |
| Static high/critical lost in skipped units | - | 0 | 0 |

Run status by mode: {'disabled': {'complete': 15}, 'prioritize': {'complete': 14, 'partial': 1}, 'gate': {'complete': 14, 'partial': 1}}.

- Baseline: the same sample with the classifier disabled.
- Retained: a baseline finding with a match (same rule if both have one, else same category, within 3 lines).
- Useful (proxy): severity medium or above, on a change a human commented on.
- Important (proxy): severity high or critical.
- Prioritize reviews the same units as disabled, so its gap from 100% shows LLM run-to-run variation, not lost work.
- These samples are single changes, so prioritize usually has nothing to reorder.
