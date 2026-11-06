# Can We Train a Deep Learning Model to Review Code?

*Research note for the capstone guide · 4 October 2026 · Team 23UG082*

> **Update, 6 November 2026.** The project guide has since asked for fine-tuning, so section 5.2 was
> carried out for a classifier: see [../fine-tuning.md](../fine-tuning.md). One figure below is wrong.
> The "39,630 Python examples" are all label 0: the positive training records have no language tag,
> so filtering on it removes every positive. The usable Python training set is the one
> `docs/fine-tuning.md` describes. Section 6's script predates the guide's request.

---

## 1. Verdict

**Training our own deep learning model to review code is not viable for this project.** Training from
scratch is infeasible, and fine-tuning an existing model produces weaker reviews than the pretrained-LLM
design we already built.

| Option | Feasible for us? | Why |
|---|---|---|
| Train a model **from scratch** | No | Needs hundreds of GB of data and a GPU cluster; from-scratch models perform worst in the literature |
| **Fine-tune** an existing code model (e.g. CodeReviewer, 223M parameters) | Technically yes, with a cloud GPU | Published fine-tuned models reach only ~5 BLEU-4 and their comments almost never match human reviewers |
| **Pretrained LLM + project context + static analysis** (our design) | Yes, already built | Research shows prompted LLMs with code context outperform fine-tuned models |

**Important:** the argument is *not* "we have too little data". We hold 117,739 comment-generation and
265,836 quality-estimation training examples (section 4). The argument is **compute cost, data quality,
missing codebase context and measured performance**.

---

## 2. Technical reasons

### 2.1 Training from scratch is infeasible

- The state-of-the-art code-review model, **CodeReviewer** (Microsoft, ESEC/FSE 2022), is a 223M-parameter
  Transformer (12 encoder + 12 decoder layers, hidden size 768).
- Its pre-training used **463.2 GB** of data: **7.9 million pull requests** from **1,161 projects** in 9
  languages.
- It was trained on **2 DGX-2 servers with 32 NVIDIA V100 (32 GB) GPUs** for **250,000 steps**
  (batch size 768). Fine-tuning alone used a server with 4 V100 GPUs.
- Even this model did **not** start from scratch: it was initialised from CodeT5, which was already
  pretrained on large code corpora.
- In the same paper, a Transformer **trained from scratch** on the same task data was clearly worse
  (F1 56.93 vs 71.53 on quality estimation) and **"failed to converge in 10 epochs"** on code refinement.
- Our machine has **no NVIDIA GPU** (12-core AMD CPU only).

### 2.2 Even the best trained models produce weak reviews

| Model | Training | Comment BLEU-4 | Human "information" (/5) | Human "relevance" (/5) |
|---|---|---:|---:|---:|
| Transformer | from scratch | 4.76 | 3.08 | 2.50 |
| CodeT5 | fine-tuned | 4.83 | 3.03 | 2.40 |
| CodeReviewer | pre-trained + fine-tuned | 5.32 | 3.60 | 3.20 |
| LLaMA-Reviewer (6.7B, LoRA) | fine-tuned on A100-80GB | 5.70 | – | – |

- The CodeReviewer authors note the BLEU score is **"still lower than 10, indicating it is a hard task"**.
- An independent study (Tufano et al.) checked whether generated comments matched what the human reviewer
  actually said. **CodeReviewer: 0 of 1,611 correct (0%).** The best of three trained models reached
  **2.85%**.
- Quality estimation ("does this change need a comment?") is better but still limited: CodeReviewer reaches
  **73.89% accuracy / 71.53 F1**.

### 2.3 The training data is noisy

- Only **64%** of sampled CodeReviewer training comments are valid; the rest are vague, non-actionable or
  just clarification questions ("Too Noisy To Learn", 2025).
- **32%** of the test-set comments are noisy (Tufano et al., cited in the same paper).
- **Fewer than 10%** of benchmark reference comments are high quality for automation (DeepCRCEval).
- About **25%** of inspected dataset instances are **data-extraction errors** (Tufano et al.).
- A model trained on this data learns to imitate the noise. Cleaning helps but shrinks the training set by
  **25–66%** and raised BLEU-4 only by **7.5–13%**.

### 2.4 Trained models cannot see the rest of the codebase

- Tufano et al. found these models **"struggle"** with changes spanning several components, because their
  view is **"usually limited to a single function or diff hunk"**.
- Real code review needs cross-file context: callers, callees, data formats, tests. Our agent supplies this
  through the call graph and retrieval; a trained single-hunk model cannot.

### 2.5 Prompting LLMs with context beats fine-tuning

- A 2024 study compared both approaches on the CodeReviewer dataset. **GPT-3.5 prompted with function call
  graphs beat the pretrained CodeReviewer baseline by about 90% BLEU-4.**
- QLoRA fine-tuned Code Llama and Llama 3.1 improved by only **25–83%**.
- Our Code Review Agent follows the winning recipe: a pretrained LLM (Groq, `openai/gpt-oss-120b`) plus
  call-graph context, retrieval and static analysis.

### 2.6 BLEU, the standard metric, is itself unreliable

- DeepCRCEval reports that text-similarity metrics such as BLEU have **weak correlation** with what matters
  (better code, detected defects). So even a model that "wins" on BLEU may not review better.

### 2.7 We have no project-specific labels

- Our own reviews have no human "correct answers". There is nothing project-specific to train on without
  months of manual labelling.

---

## 3. Evidence summary from the literature

| Source | Key finding |
|---|---|
| [CodeReviewer, ESEC/FSE 2022](https://arxiv.org/pdf/2203.09095) | 463.2 GB data, 32 V100 GPUs; BLEU-4 5.32; from-scratch model worse and failed to converge |
| [Tufano et al., Strengths and Weaknesses of the State of the Art](https://arxiv.org/pdf/2401.05136) | 0% of CodeReviewer comments correct; models limited to one hunk; ~25% data-extraction errors |
| [Too Noisy To Learn (2025)](https://www.arxiv.org/pdf/2502.02757) | Only 64% of training comments valid; cleaning gives +7.5–13% BLEU-4 |
| [DeepCRCEval](https://arxiv.org/abs/2412.18291) | <10% of reference comments high quality; BLEU weakly correlated with real goals |
| [LLaMA-Reviewer](https://arxiv.org/html/2308.11148v2) | 6.7B model fine-tuned on A100-80GB reaches only 5.70 BLEU-4 |
| [Prompting and Fine-tuning LLMs for Review Comments (2024)](https://arxiv.org/abs/2411.10129) | Prompted GPT-3.5 + call graphs ~90% better than CodeReviewer; fine-tuning 25–83% |
| [Fine-Tuning for Code Review, Industrial C# (2025)](https://arxiv.org/abs/2507.19271) | Fine-tuning helps routine tasks; humans remain better for complex, context-sensitive changes |

---

## 4. Our own data and hardware (measured on our machine)

| CodeReviewer dataset (in `capstone-datasets/`) | Total examples | Python only |
|---|---:|---:|
| Comment generation: train | 117,739 | – (no language field in this split) |
| Comment generation: valid / test | 10,319 / 10,169 | – / 1,403 (test) |
| Quality estimation: train (4 chunks) | 265,836 | 39,630 |
| Quality estimation: valid | 31,252 | 4,220 |
| Quality estimation: test | 31,252 | 4,196 |

| Hardware | Value |
|---|---|
| GPU | None (no NVIDIA GPU detected) |
| CPU | 12 cores, AMD |

So **data volume is not the obstacle**; quality, compute and context are.

---

## 5. What is feasible instead

### 5.1 Our chosen design (already built and tested)

Pretrained LLM + call-graph context + retrieval + static analysis + validation of every finding.
Measured on our planted-issue benchmark: **17/17 issues found, 14/14 defect precision**, versus 16/17 with
static analysis alone (see `docs/results.md`).

### 5.2 Optional experiment to make the case bulletproof

If the guide wants empirical proof rather than literature:

1. Fine-tune the **released CodeReviewer checkpoint** on our **39,630 Python quality-estimation examples**.
2. Run it on **free Google Colab** (T4 GPU, a few hours).
3. Evaluate on the **same 4,196 Python test samples** our agent was evaluated on.
4. Compare accuracy, precision, recall, F1 and ROC-AUC side by side.

This turns "the literature says" into "we tested it ourselves". It can also become a component: a fast
trained classifier that pre-filters which code changes need a full LLM review.

### 5.3 What we would need for a trained model to be worthwhile

- A GPU budget (multiple A100/V100-class GPUs for weeks for anything beyond fine-tuning).
- A cleaned, high-quality, labelled dataset (manual or LLM-assisted cleaning).
- A way to give the model repository context, which current trained models lack.

---

## 6. How to defend this in front of the guide (simple words)

### The one-paragraph answer

> "Ma'am, we researched it properly. Training a code-review model from scratch needs hundreds of GB of
> data and a GPU cluster. Microsoft's CodeReviewer used 463 GB and 32 GPUs, and the from-scratch version
> still performed worse. Even the best fine-tuned models only reach about 5 BLEU, and an independent study
> found 0% of their comments matched human reviewers. Part of the reason is noisy data (only 64% clean), and
> part is that these models see only one small piece of code, not the whole project. Research shows that a
> large pretrained LLM given the right code context beats fine-tuned models, so that's the design we built."

### Short answers to likely questions

**"Why can't you just train a model?"**
It needs a GPU cluster and hundreds of GB of data. Even the experts' from-scratch model did worse.

**"But you have a dataset, right?"**
Yes, over 100,000 examples. The problem isn't the amount, it's the quality: about a third of the comments
are useless, and models trained on it score poorly.

**"Then why not fine-tune an existing model?"**
We can, but published results show it reaches only about 5 BLEU and its comments almost never match a
human reviewer. A prompted LLM with code context did about 90% better in a 2024 study.

**"Is your project then just using ChatGPT?"**
No. The LLM is one stage of a 12-stage pipeline: static analysis, call-graph context, retrieval, and
validation that rejects any finding whose quoted code doesn't exist.

**"What is your contribution if you don't train a model?"**
The system around the model: repository-aware context, verified findings, a severity rubric, multi-agent
design, and a measured evaluation. That's also what the approved project plan says.

**"Can you prove fine-tuning is worse instead of just quoting papers?"**
Yes. We can fine-tune the released CodeReviewer model on our 39,630 Python examples on free Colab and compare
it with our agent on the same 4,196 test samples.

**"Will you never train anything?"**
We can add a small fine-tuned classifier as a fast pre-filter. Training a full reviewer is out of scope for a
capstone budget.

### Three numbers to remember

- **463 GB and 32 GPUs**: what CodeReviewer needed.
- **0%**: CodeReviewer comments matching the human reviewer in an independent study.
- **64%**: share of the training data that is actually clean.

---

## 7. Sources

All pages below were opened and read for this note.

1. Li et al., [Automating Code Review Activities by Large-Scale Pre-training](https://arxiv.org/pdf/2203.09095), ESEC/FSE 2022.
2. Tufano et al., [Code Review Automation: Strengths and Weaknesses of the State of the Art](https://arxiv.org/pdf/2401.05136).
3. [Too Noisy To Learn: Enhancing Data Quality for Code Review Comment Generation](https://www.arxiv.org/pdf/2502.02757), 2025.
4. [DeepCRCEval: Revisiting the Evaluation of Code Review Comment Generation](https://arxiv.org/abs/2412.18291).
5. [LLaMA-Reviewer: Advancing Code Review Automation with LLMs through Parameter-Efficient Fine-Tuning](https://arxiv.org/html/2308.11148v2).
6. [Prompting and Fine-tuning Large Language Models for Automated Code Review Comment Generation](https://arxiv.org/abs/2411.10129), 2024.
7. [Fine-Tuning Multilingual Language Models for Code Review: An Empirical Study on Industrial C# Projects](https://arxiv.org/abs/2507.19271), 2025.
8. Local measurements: dataset counts and hardware check run on the project machine, 4 October 2026.
