# Baseline comparison (codereviewer_msg, group abl-20261111T111605Z)

### CodeReviewer: review comment generation

Status: Complete | Historical: Groq (openai/gpt-oss-120b)

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **paired samples:** 40 of 40 requested
- **evaluated per configuration:** A 40/40, B 40/40, C 40/40, D 40/40
- **requested samples:** 40
- **samples in every row:** 40
- **sampling seed:** 42
- **limit:** 40
- **comment:** top finding's title + recommendation
- **scale:** BLEU-4, ROUGE-L, chrF: 0-100; coverage: 0-1

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | 1.78 ± 0.00 | 4.90 ± 0.00 | 7.86 ± 0.00 | 0.425 ± 0.000 | 40 | 0 | 3 | - |
| LLM Only | ✗ | ✓ | ✗ | 1.55 ± 0.09 | 5.22 ± 0.43 | 11.09 ± 0.57 | 0.642 ± 0.014 | 40 | 0 | 3 | openai/gpt-oss-120b |
| Static + LLM | ✓ | ✓ | ✗ | 1.78 ± 0.09 | 5.33 ± 0.59 | 12.40 ± 1.09 | 0.675 ± 0.043 | 40 | 0 | 3 | openai/gpt-oss-120b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 1.92 ± 0.35 | 5.42 ± 0.51 | 13.16 ± 0.89 | 0.717 ± 0.038 | 40 | 0 | 3 | openai/gpt-oss-120b |

Values with ± are the mean ± sample standard deviation over repeated runs.

Fairness checks:
- ✓ Same samples: 40 samples evaluated by every configuration (40 requested; reference run 20261111T114545Z_codereviewer_msg_test_static_llm_rag_n40)
- ✓ Same LLM model: openai/gpt-oss-120b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.1'}
- ✓ Fresh LLM calls: every LLM run called the model
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'}
- ✓ Run together (one ablation group): abl-20261111T111605Z

Observations (computed from the numbers above):
- Static + LLM has a higher chrF than Static Only (12.40 vs 7.86).
- Static + LLM + RAG has a higher chrF than Static + LLM (13.16 vs 12.40).
- LLM Only has a higher chrF than Static Only (11.09 vs 7.86).
- Static + LLM has a higher coverage than Static Only (0.675 vs 0.425).
- Static + LLM + RAG has a higher coverage than Static + LLM (0.717 vs 0.675).
- LLM Only has a higher coverage than Static Only (0.642 vs 0.425).

Statistics (Wilson 95% intervals, exact McNemar, paired bootstrap):
- A: coverage per run 17/40, 17/40, 17/40 (mean 17.0/40, min 17, max 17); latest run 0.425 (17/40; 95% CI 0.285-0.578)
- B: coverage per run 26/40, 25/40, 26/40 (mean 25.7/40, min 25, max 26); latest run 0.650 (26/40; 95% CI 0.495-0.779)
- C: coverage per run 25/40, 28/40, 28/40 (mean 27.0/40, min 25, max 28); latest run 0.700 (28/40; 95% CI 0.546-0.819)
- D: coverage per run 30/40, 29/40, 27/40 (mean 28.7/40, min 27, max 30); latest run 0.675 (27/40; 95% CI 0.520-0.799)
- B minus A (paired bootstrap, 1,000 resamples, seed 42): BLEU-4 -0.23 (95% CI -1.12 to +0.66, bootstrap p = 0.670, n = 40); ROUGE-L +0.31 (95% CI -2.19 to +2.86, bootstrap p = 0.732, n = 40); chrF +3.23 (95% CI -1.07 to +7.36, bootstrap p = 0.140, n = 40); coverage +0.22 (95% CI +0.03 to +0.42, bootstrap p = 0.028, n = 40)
- C minus A (paired bootstrap, 1,000 resamples, seed 42): BLEU-4 +0.00 (95% CI -0.67 to +0.64, bootstrap p = 0.934, n = 40); ROUGE-L +0.43 (95% CI -1.22 to +2.02, bootstrap p = 0.526, n = 40); chrF +4.54 (95% CI +2.45 to +7.16, bootstrap p = 0.000, n = 40); coverage +0.25 (95% CI +0.14 to +0.38, bootstrap p = 0.000, n = 40)
- D minus A (paired bootstrap, 1,000 resamples, seed 42): BLEU-4 +0.13 (95% CI -0.59 to +0.85, bootstrap p = 0.702, n = 40); ROUGE-L +0.51 (95% CI -1.13 to +2.45, bootstrap p = 0.542, n = 40); chrF +5.30 (95% CI +2.82 to +7.94, bootstrap p = 0.000, n = 40); coverage +0.29 (95% CI +0.17 to +0.42, bootstrap p = 0.000, n = 40)
- D minus C (paired bootstrap, 1,000 resamples, seed 42): BLEU-4 +0.13 (95% CI -0.24 to +0.50, bootstrap p = 0.456, n = 40); ROUGE-L +0.08 (95% CI -1.17 to +1.23, bootstrap p = 0.886, n = 40); chrF +0.76 (95% CI -0.80 to +2.44, bootstrap p = 0.400, n = 40); coverage +0.04 (95% CI -0.03 to +0.12, bootstrap p = 0.204, n = 40)
- D minus B (paired bootstrap, 1,000 resamples, seed 42): BLEU-4 +0.36 (95% CI -0.20 to +0.89, bootstrap p = 0.222, n = 40); ROUGE-L +0.20 (95% CI -1.64 to +2.01, bootstrap p = 0.840, n = 40); chrF +2.07 (95% CI -1.07 to +5.00, bootstrap p = 0.198, n = 40); coverage +0.07 (95% CI -0.07 to +0.22, bootstrap p = 0.334, n = 40)
- Coverage: the share of samples for which the configuration produced a comment (its top-ranked in-scope finding was not empty). Empty comments score 0 on BLEU-4, ROUGE-L and chrF. With several runs, each sample's scores are averaged over the runs before the paired bootstrap.

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 40: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 40 samples need at least 120 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.

Source runs: `20261111T111605Z_codereviewer_msg_test_static_only_n40`, `20261111T111615Z_codereviewer_msg_test_llm_only_n40`, `20261111T111914Z_codereviewer_msg_test_static_llm_n40`, `20261111T112247Z_codereviewer_msg_test_static_llm_rag_n40`, `20261111T112652Z_codereviewer_msg_test_static_only_n40`, `20261111T112702Z_codereviewer_msg_test_llm_only_n40`, `20261111T113024Z_codereviewer_msg_test_static_llm_n40`, `20261111T113432Z_codereviewer_msg_test_static_llm_rag_n40`, `20261111T113829Z_codereviewer_msg_test_static_only_n40`, `20261111T113839Z_codereviewer_msg_test_llm_only_n40`, `20261111T114143Z_codereviewer_msg_test_static_llm_n40`, `20261111T114545Z_codereviewer_msg_test_static_llm_rag_n40`

### CodeReviewer: review comment generation: external reference (published, all languages)

Published result of the original CodeReviewer paper on the full multi-language benchmark. Our tables above use the Python subset.

| Method | BLEU-4 | ROUGE-L | chrF | Coverage |
|---|---|---|---|---|
| External reference: original CodeReviewer paper (published, all languages) | N/A | N/A | N/A | N/A |

N/A:
- External reference: original CodeReviewer paper (published, all languages) / all metrics: TBD: fill in from the paper (experiments/external_reference/)

- TBD until filled in from the paper: experiments/external_reference/codereviewer_paper.json.
