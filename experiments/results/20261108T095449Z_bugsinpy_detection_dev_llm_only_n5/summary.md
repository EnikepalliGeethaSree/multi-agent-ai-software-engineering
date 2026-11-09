# Bug detection: llm_only

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 5 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.000 | 0.000 | 0.000 | 0.500 |
| Defect at the fixed lines | 0.000 | 0.000 | 0.000 | 0.500 |

- F1 95% CI: (0.000-0.000); AUC: 0.500
- Told apart from the fix: 0.000 (only buggy 0, both 0, neither 5, only fixed 0)
- LLM calls: 10; LLM findings rejected: 0
