# Baseline comparison (codereviewer_msg, group abl-20261109T083055Z)

### CodeReviewer: review comment generation

Status: Incomplete | Gemini: gemini-3.6-flash

> **Incomplete comparison: Static Only, Static + LLM, Static + LLM + RAG have no results. This table does not show that RAG improves comment quality.**

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **paired samples:** 40 of 40 requested
- **evaluated per configuration:** A not run, B 40/40, C not run, D not run
- **requested samples:** 40
- **samples in every row:** 40
- **sampling seed:** 42
- **limit:** 40
- **comment:** top finding's title + recommendation
- **scale:** BLEU-4, ROUGE-L, chrF: 0-100; coverage: 0-1

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | N/A | N/A | N/A | N/A | - | - | not run | - |
| LLM Only | ✗ | ✓ | ✗ | 1.86 | 4.99 | 8.67 | 0.475 | 40 | 0 | 1 | gemini-3.6-flash |
| Static + LLM | ✓ | ✓ | ✗ | N/A | N/A | N/A | N/A | - | - | not run | ? |
| Static + LLM + RAG | ✓ | ✓ | ✓ | N/A | N/A | N/A | N/A | - | - | not run | ? |

N/A:
- Static Only / all metrics: no saved run
- Static + LLM / all metrics: no saved run
- Static + LLM + RAG / all metrics: no saved run

To run:
- Static Only: `python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_only`
- Static + LLM: `python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm --workers 1 --config configs/gemini.yaml`
- Static + LLM + RAG: `python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml`

Fairness checks:
- ✗ Same samples: 40 of 40 requested samples evaluated by LLM Only; no scored samples for Static Only, Static + LLM, Static + LLM + RAG (reference run 20261109T083055Z_codereviewer_msg_test_llm_only_n40)
- ✓ Same LLM model: gemini-3.6-flash
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✗ Fresh LLM calls: replies reused from the cache in LLM Only: quality metrics compare, times do not
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'}
- ✓ Run together (one ablation group): abl-20261109T083055Z

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 40: differences of a few points are within sampling noise (see the bootstrap CIs in each run's summary).
- The effect of RAG on comment quality cannot be judged here: it needs Static + LLM and Static + LLM + RAG on the same samples. Static Only vs Static + LLM + RAG changes two things at once.
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 40 samples need at least 120 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.

Source runs: `20261109T083055Z_codereviewer_msg_test_llm_only_n40`
