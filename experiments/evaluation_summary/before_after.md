# Original vs improved system

| Benchmark | Metric | Original | Improved | n | Note |
|---|---|---:|---:|---:|---|
| Planted issues | Precision | 1.000 | 1.000 | - |  |
| Planted issues | Recall | 1.000 | 1.000 | - |  |
| Planted issues | False positives in the clean file | 0.000 | 0.000 | - |  |
| CodeReviewer comments | Comment coverage | 0.778 | N/A | 36 | improved run missing: python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml |
| CodeReviewer comments | BLEU-4 | 2.136 | N/A | 36 | improved run missing: python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml |
| CodeReviewer comments | ROUGE-L | 6.909 | N/A | 36 | improved run missing: python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml |
| CodeReviewer comments | chrF | 13.595 | N/A | 36 | improved run missing: python -m marl_agents.cli eval codereviewer --task msg --limit 40 --seed 42 --configuration static_llm_rag --workers 1 --config configs/gemini.yaml |
| Needs-review classification | Accuracy | N/A | N/A | - |  |
| Needs-review classification | Precision | N/A | N/A | - |  |
| Needs-review classification | Recall | N/A | N/A | - |  |
| Needs-review classification | F1-score | N/A | N/A | - |  |
| Needs-review classification | False positive rate | N/A | N/A | - |  |
| Needs-review classification | ROC-AUC | N/A | N/A | - |  |
| LLM work per sample (Gemini, without vs with classifier) | Average LLM calls | N/A | N/A | - | improved run missing: python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml |
| LLM work per sample (Gemini, without vs with classifier) | Average input tokens | N/A | N/A | - | improved run missing: python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml |
| LLM work per sample (Gemini, without vs with classifier) | Average output tokens | N/A | N/A | - | improved run missing: python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml |
| LLM work per sample (Gemini, without vs with classifier) | Average execution time (s) | N/A | N/A | - | improved run missing: python -m marl_agents.cli eval classifier-ablation --model-dir data/models/change_cls --limit 15 --max-llm-calls 45 --config configs/gemini.yaml |

- Classification rows compare the original static analysis with the fine-tuned classifier on the same repository-disjoint test samples. They do not depend on the LLM provider.
- Original = the agent on Groq; improved = the agent on Gemini. Both are the full configuration (static + LLM + RAG).
- Execution time, LLM calls and token use by file size are in the file-size benchmark.
- The classifier has its own evaluation run, because it scores changes, not findings.
