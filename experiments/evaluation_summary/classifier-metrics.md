# Fine-tuned change classifier: extended test metrics

Source run `20261106T144800Z_classifier_cls_test_n1771`. Threshold 0.44 (chosen on dev before the test run). Computed from the saved scores of the single test run; nothing was re-scored.

## Repository-disjoint test (primary): n = 1771 (979 positive, base rate 0.553)

| Metric | Classifier | Baseline |
|---|---:|---:|
| ROC-AUC | 0.723 | 0.500 (random) |
| PR-AUC (average precision) | 0.780 | 0.553 (positive base rate) |
| Precision | 0.707 (0.677-0.735) | 0.553 (always positive) |
| Recall | 0.672 (0.642-0.701) | 1.000 (always positive) |
| F1 | 0.689 | 0.712 (always positive) |
| Accuracy | 0.665 | 0.553 (always positive); 0.553 (majority class) |
| Balanced accuracy | 0.664 | 0.500 |
| MCC | 0.326 | 0.000 |
| Precision at top 10% (178 changes) | 0.938 | 0.553 (base rate) |
| Brier score (lower is better) | 0.215 | 0.247 (constant base rate) |

Confusion matrix at the threshold: TP 658, FP 273, TN 519, FN 321. Intervals in brackets are Wilson 95% intervals.

## Official Python test (secondary): n = 3634 (2022 positive, base rate 0.556)

| Metric | Classifier | Baseline |
|---|---:|---:|
| ROC-AUC | 0.724 | 0.500 (random) |
| PR-AUC (average precision) | 0.780 | 0.556 (positive base rate) |
| Precision | 0.708 (0.687-0.727) | 0.556 (always positive) |
| Recall | 0.690 (0.669-0.710) | 1.000 (always positive) |
| F1 | 0.699 | 0.715 (always positive) |
| Accuracy | 0.669 | 0.556 (always positive); 0.556 (majority class) |
| Balanced accuracy | 0.666 | 0.500 |
| MCC | 0.332 | 0.000 |
| Precision at top 10% (364 changes) | 0.920 | 0.556 (base rate) |
| Brier score (lower is better) | 0.214 | 0.247 (constant base rate) |

Confusion matrix at the threshold: TP 1395, FP 576, TN 1036, FN 627. Intervals in brackets are Wilson 95% intervals.
