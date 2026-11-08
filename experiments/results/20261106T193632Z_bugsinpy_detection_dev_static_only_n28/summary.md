# Bug detection: static_only

- BugsInPy dev split, n=28 bugs (of 28 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 28 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.571 | 0.143 | 0.229 | 0.518 |
| Defect at the fixed lines | 1.000 | 0.071 | 0.133 | 0.536 |

- F1 95% CI: (0.056-0.400); AUC: 0.520
- Told apart from the fix: 0.036 (only buggy 1, both 3, neither 24, only fixed 0)
- LLM calls: 0; claims rejected: 268
