# Baseline comparison (codereviewer_msg, group abl-20261109T084532Z)

### CodeReviewer: review comment generation

Status: Complete | Local: Ollama (qwen2.5-coder:7b)

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
| Static Only | ✓ | ✗ | ✗ | 1.78 | 4.90 | 7.86 | 0.425 | 40 | 0 | 1 | - |
| LLM Only | ✗ | ✓ | ✗ | 0.77 | 2.64 | 3.56 | 0.200 | 40 | 0 | 1 | qwen2.5-coder:7b |
| Static + LLM | ✓ | ✓ | ✗ | 2.27 | 6.30 | 10.90 | 0.600 | 40 | 0 | 1 | qwen2.5-coder:7b |
| Static + LLM + RAG | ✓ | ✓ | ✓ | 2.59 | 6.53 | 10.98 | 0.625 | 40 | 0 | 1 | qwen2.5-coder:7b |

Fairness checks:
- ✓ Same samples: 40 samples evaluated by every configuration (40 requested; reference run 20261109T114916Z_codereviewer_msg_test_static_llm_rag_n40)
- ✓ Same LLM model: qwen2.5-coder:7b
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.1'}
- ✓ Fresh LLM calls: every LLM run called the model
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'}
- ✓ Run together (one ablation group): abl-20261109T084532Z

Observations (computed from the numbers above):
- Static + LLM has a higher chrF than Static Only (10.90 vs 7.86).
- Static + LLM + RAG has a higher chrF than Static + LLM (10.98 vs 10.90).
- Static Only has a higher chrF than LLM Only (7.86 vs 3.56).
- Static + LLM has a higher coverage than Static Only (0.600 vs 0.425).
- Static + LLM + RAG has a higher coverage than Static + LLM (0.625 vs 0.600).
- Static Only has a higher coverage than LLM Only (0.425 vs 0.200).

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 40: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 40 samples need at least 120 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.

Source runs: `20261109T084532Z_codereviewer_msg_test_static_only_n40`, `20261109T084547Z_codereviewer_msg_test_llm_only_n40`, `20261109T100904Z_codereviewer_msg_test_static_llm_n40`, `20261109T114916Z_codereviewer_msg_test_static_llm_rag_n40`
