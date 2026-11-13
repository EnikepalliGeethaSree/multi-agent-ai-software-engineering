# Bug detection: static_llm

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.571 | 0.800 | 0.667 | 0.600 |
| Defect at the fixed lines | 0.478 | 0.550 | 0.512 | 0.475 |

- F1 95% CI: (0.486-0.800); AUC: 0.626
- Told apart from the fix: 0.300 (only buggy 6, both 10, neither 2, only fixed 2)
- LLM calls: 40; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.571 (16/28; 95% CI 0.391-0.735); recall 0.800 (16/20; 95% CI 0.584-0.919); told apart from the fix 0.300 (6/20; 95% CI 0.145-0.519)
