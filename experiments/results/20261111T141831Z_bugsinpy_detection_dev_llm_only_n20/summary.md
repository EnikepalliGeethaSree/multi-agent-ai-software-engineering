# Bug detection: llm_only

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.483 | 0.700 | 0.571 | 0.475 |
| Defect at the fixed lines | 0.423 | 0.550 | 0.478 | 0.400 |

- F1 95% CI: (0.391-0.720); AUC: 0.500
- Told apart from the fix: 0.100 (only buggy 2, both 12, neither 3, only fixed 3)
- LLM calls: 40; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.483 (14/29; 95% CI 0.314-0.656); recall 0.700 (14/20; 95% CI 0.481-0.855); told apart from the fix 0.100 (2/20; 95% CI 0.028-0.301)
