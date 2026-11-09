# Bug detection: static_only

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 5 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 1.000 | 0.200 | 0.333 | 0.600 |
| Defect at the fixed lines | 1.000 | 0.200 | 0.333 | 0.600 |

- F1 95% CI: (0.000-0.750); AUC: 0.600
- Told apart from the fix: 0.200 (only buggy 1, both 0, neither 4, only fixed 0)
- LLM calls: 0; LLM findings rejected: 0
