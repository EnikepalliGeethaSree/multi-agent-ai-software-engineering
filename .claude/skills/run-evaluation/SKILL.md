---
name: run-evaluation
description: Plan, run, and report an agent-level benchmark evaluation, a RAG retrieval evaluation, or the system-level A/B/C comparison (single LLM vs multi-agent vs multi-agent+RAG). Use when the user wants metrics, experiment results, or comparison tables.
---

# Run an evaluation

Read `.claude/rules/evaluation-integrity.md` first. The golden rule: **every reported number comes from a
saved run; nothing is estimated or invented.**

## 1. Pin down the experiment

State explicitly and confirm with the user before any costly run:
- **Level**: agent-level (which agent + dataset), RAG retrieval, or system-level (A/B/C).
- **Split and sample size** (e.g. CodeReviewer test, n=200, seed 42, Python-only).
- **Model/provider, temperature (default 0), prompt versions, top-k, RAG on/off.**
- **Metrics** (defaults from CLAUDE.md table) and how each is computed.
- **Cost/time estimate** for paid APIs (samples × calls × tokens). Get approval above a trivial amount.

## 2. Configure

Write `experiments/configs/<run_name>.yaml` capturing everything above. For A/B/C, three configs that differ
only in the variable under test:
- A: `mode: single_llm` — one prompt, whole task, no agents, no RAG.
- B: `mode: multi_agent`, `rag.enabled: false`.
- C: `mode: multi_agent`, `rag.enabled: true`.

## 3. Run

- Smoke-test first with `limit: 5` and `MockLLMProvider` or the cheapest model.
- Runs write to `experiments/results/<timestamp>_<run_name>/`: `config.yaml`, `meta.json` (git commit,
  package versions, sample IDs), `predictions.jsonl` (raw model output per sample), `metrics.json`, `errors.jsonl`.
- Execution-based metrics (HumanEval pass@1, coverage, mutation score, SWE-bench resolve rate, BugsInPy
  test pass) run only in an isolated environment (Docker / throwaway venv) with timeouts.

## 4. Report

- Produce a Markdown table from `metrics.json` files only, with n, split, model and seed in the caption.
- Include failure counts (parse errors, timeouts, rejected findings).
- For A/B/C, report per-metric differences; with small n, add a bootstrap confidence interval or say the
  difference may not be significant. Don't claim C is better unless the data shows it.
- Save the table to `experiments/results/<run>/summary.md` and link it from `docs/results.md`.
