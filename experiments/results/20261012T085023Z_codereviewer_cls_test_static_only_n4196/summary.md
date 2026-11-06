# CodeReviewer cls (test, Python, n=4196, seed=42, static_only)

n = 4195 evaluated (1 failed: {'patch': 1}), labels = {'positive': 2033, 'negative': 2162}. Findings per sample: 0.731; runtime 218.9 s.

## All rules

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.447 | 0.413 | 0.333 | 0.369 | 0.391 |
| low | 0.437 | 0.384 | 0.266 | 0.314 | 0.336 |
| medium | 0.441 | 0.259 | 0.083 | 0.125 | 0.154 |
| high | 0.430 | 0.153 | 0.039 | 0.062 | 0.123 |
| critical | 0.515 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.437 (95% CI 0.422-0.453), precision 0.384 (95% CI 0.358-0.412), F1 0.314 (95% CI 0.295-0.335)
- ROC-AUC of the finding score: 0.417
- Baselines: majority-class accuracy 0.515; always-positive F1 0.653

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Each sample is one hunk of a larger commit, so these rules fire on imports/names that
live in other hunks. Both analyses are reported; neither replaces the other.

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.546 | 0.573 | 0.247 | 0.345 | 0.209 |
| low | 0.541 | 0.592 | 0.167 | 0.261 | 0.137 |
| medium | 0.529 | 0.648 | 0.062 | 0.114 | 0.047 |
| high | 0.520 | 0.684 | 0.019 | 0.037 | 0.014 |
| critical | 0.515 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.541 (95% CI 0.525-0.555), precision 0.592 (95% CI 0.552-0.636), F1 0.261 (95% CI 0.237-0.285)
- ROC-AUC of the finding score: 0.539
- Baselines: majority-class accuracy 0.515; always-positive F1 0.653
