# Change classifier: independent test

Model change_cls (microsoft/codebert-base), trained on 16000 examples (1.15 epochs of 2). Threshold 0.44 from the dev split. The label is 'a human commented on this change', a proxy for 'needs review', not a defect label.

| Scorer and set | n | Accuracy | Precision | Recall | F1 | FPR | ROC-AUC (95% CI) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Classifier, repository-disjoint (primary) | 1771 | 0.6646 | 0.7068 | 0.6721 | 0.689 | 0.3447 | 0.723 (0.6991-0.7477) |
| Original static analysis, same set | 1771 | 0.4997 | 0.6742 | 0.1839 | 0.2889 | 0.1098 | 0.5415 (---) |
| TF-IDF + logistic regression, same set | 1771 | 0.5906 | 0.6779 | 0.4944 | 0.5718 | 0.2904 | 0.6454 (0.6193-0.6695) |
| Majority class, same set | 1771 | 0.5528 | - | - | - | - | - |
| Change size only, same set | 1771 | - | - | - | - | - | 0.6353 |
| Classifier, official test (shares projects with valid) | 3634 | 0.669 | 0.7078 | 0.6899 | 0.6987 | 0.3573 | 0.7237 (0.707-0.7406) |

Confusion matrix (primary): {'tp': 658, 'fp': 273, 'tn': 519, 'fn': 321}.
Class-wise (primary): {'needs_review': {'precision': 0.7068, 'recall': 0.6721, 'support': 979}, 'no_comment': {'precision': 0.6179, 'recall': 0.6553, 'support': 792}}.

Python only. No claim is made about other languages.
