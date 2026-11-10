# Static baseline on the full CodeReviewer test set: extended metrics

Source run `20261012T163153Z_codereviewer_cls_test_static_only_n4196`. Flagged = at least one finding of severity >= low. Python only. "Without single-hunk rules" excludes F401, F403, F405, F811, F821.

| Rule set | n | Accuracy | Balanced accuracy | MCC | Precision | Recall | F1 | Majority-class accuracy | Always-positive F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All rules | 4195 | 0.437 | 0.432 | -0.144 | 0.384 (0.358-0.409) | 0.266 (0.247-0.285) | 0.314 | 0.515 | 0.653 |
| Without single-hunk rules | 4195 | 0.541 | 0.530 | 0.086 | 0.592 (0.552-0.632) | 0.167 (0.152-0.184) | 0.261 | 0.515 | 0.653 |
