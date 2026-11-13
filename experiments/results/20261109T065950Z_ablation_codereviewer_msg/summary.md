# Baseline comparison (codereviewer_msg, group abl-20261109T065441Z)

### CodeReviewer: review comment generation

Status: Preliminary | Gemini: gemini-3.6-flash

> **Preliminary: only 20 of 40 requested samples are paired. No conclusion about any configuration can be drawn from this table, and ROC-AUC is not reported.**

Paired comparison: every row is scored on the same samples.

- **dataset:** CodeReviewer, test split, Python only
- **paired samples:** 20 of 40 requested
- **evaluated per configuration:** A not run, B 20/40, C not run, D not run
- **requested samples:** 40
- **samples in every row:** 20
- **sampling seed:** 42
- **limit:** 40
- **comment:** top finding's title + recommendation
- **scale:** BLEU-4, ROUGE-L, chrF: 0-100; coverage: 0-1

| Configuration | Static | LLM | RAG | BLEU-4 | ROUGE-L | chrF | Coverage | n | failed | runs | model |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Static Only | ✓ | ✗ | ✗ | N/A | N/A | N/A | N/A | - | - | not run | - |
| LLM Only | ✗ | ✓ | ✗ | 1.48 | 3.87 | 9.61 | 0.550 | 20 | 20 | 1 | gemini-3.6-flash |
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
- ✗ Same samples: 20 of 40 requested samples evaluated by LLM Only; no scored samples for Static Only, Static + LLM, Static + LLM + RAG (reference run 20261109T065441Z_codereviewer_msg_test_llm_only_n40)
- ✓ Same LLM model: gemini-3.6-flash
- ✓ Same temperature: 0.0
- ✓ Same prompt versions: {'system': '1.0', 'review': '1.0'}
- ✗ Fresh LLM calls: replies reused from the cache in LLM Only: quality metrics compare, times do not
- ✓ Same confidence threshold: 0.3
- ✓ Same evaluation rules: {'comment': 'top-ranked finding: title + recommendation (variant title_fix)', 'text_metric_scale': 'BLEU-4, ROUGE-L, chrF in 0-100; coverage in 0-1'}
- ✓ Run together (one ablation group): abl-20261109T065441Z

- Run all four on one sample set: python -m marl_agents.cli eval ablation --benchmark codereviewer --task msg --limit 40 --seed 42 --configurations static_only,llm_only,static_llm,static_llm_rag --config configs/gemini.yaml
- n = 20: far too few samples for any conclusion; this table only shows that the pipeline runs end to end. ROC-AUC is not reported. Each run's saved scores are unchanged in its predictions.jsonl.
- LLM Only: 20 of 40 samples failed (llm: 20).
- The effect of RAG on comment quality cannot be judged here: it needs Static + LLM and Static + LLM + RAG on the same samples. Static Only vs Static + LLM + RAG changes two things at once.
- Gemini: set GEMINI_MODEL=gemini-3.6-flash first. Three LLM configurations on 40 samples need at least 120 requests, and the free tier allows 20 per day per model. Add --reuse-llm-cache and repeat the command each day: cached replies carry it forward, and the run that finishes is complete.

Source runs: `20261109T065441Z_codereviewer_msg_test_llm_only_n40`
