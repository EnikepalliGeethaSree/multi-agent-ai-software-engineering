# Official Groq evaluation (openai/gpt-oss-120b)

All numbers from saved runs (sources in groq_final_results.json). Groq usage: 1230 requests, 4,561,550 input + 1,865,556 output tokens, estimated $1.80 at $0.15/$0.6 per 1M tokens.

## Planted issues (17 issues, 3 runs per configuration)

| Config | Issues found per run | Recall mean (min-max) | Defect precision mean | FP per run |
|---|---|---|---|---|
| A | [16, 16, 16] | 0.941 (0.941-0.941) | 1.000 | [0, 0, 0] |
| B | [11, 11, 12] | 0.667 (0.647-0.706) | 1.000 | [0, 0, 0] |
| C | [17, 17, 16] | 0.980 (0.941-1.000) | 0.954 | [1, 0, 1] |
| D | [17, 17, 17] | 1.000 (1.000-1.000) | 1.000 | [0, 0, 0] |

## CodeReviewer comments (40 test samples, Python, 3 runs)

| Config | BLEU-4 | ROUGE-L | chrF | Coverage (x/40 per run) |
|---|---|---|---|---|
| A | 1.78 (1.78-1.78) | 4.90 | 7.86 | [17, 17, 17] |
| B | 1.55 (1.47-1.65) | 5.22 | 11.09 | [26, 25, 26] |
| C | 1.78 (1.71-1.89) | 5.33 | 12.40 | [25, 28, 28] |
| D | 1.92 (1.55-2.25) | 5.42 | 13.16 | [30, 29, 27] |

## Clean repositories (configuration D)

| Repo | Lines | Findings | Per 1,000 lines | High | Critical |
|---|---:|---:|---:|---:|---:|
| requests | 6,394 | 164 | 25.649 | 11 | 0 |
| flask | 9,566 | 122 | 12.754 | 21 | 0 |
| pydantic | 29,755 | 581 | 19.526 | 42 | 1 |

## BugsInPy (20 dev bugs, 20 test bugs; test run once)

### dev

| Config | Top-1 | Top-3 | Top-5 | Detection P | R | F1 | Told apart |
|---|---|---|---|---|---|---|---|
| A | 0.20 | 0.25 | 0.30 | 0.571 | 0.200 | 0.296 | 1/20 |
| B | 0.55 | 0.60 | 0.60 | 0.483 | 0.700 | 0.571 | 2/20 |
| C | 0.45 | 0.45 | 0.50 | 0.571 | 0.800 | 0.667 | 6/20 |
| D | 0.50 | 0.60 | 0.60 | 0.593 | 0.800 | 0.681 | 6/20 |

### test

| Config | Top-1 | Top-3 | Top-5 | Detection P | R | F1 | Told apart |
|---|---|---|---|---|---|---|---|
| A | 0.15 | 0.25 | 0.35 | 0.667 | 0.100 | 0.174 | 1/20 |
| B | 0.35 | 0.50 | 0.50 | 0.467 | 0.700 | 0.560 | 1/20 |
| C | 0.35 | 0.40 | 0.40 | 0.552 | 0.800 | 0.653 | 4/20 |
| D | 0.25 | 0.40 | 0.40 | 0.516 | 0.800 | 0.627 | 3/20 |

Reproducibility: all recomputed metrics match the stored values.
