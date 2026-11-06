---
name: review-repo
description: Run the Code Review Agent on a code snippet, a local directory, or a repository ZIP and inspect the structured findings and reports. Use for demos, manual testing of the pipeline, or debugging a stage (ingestion, parsing, retrieval, static analysis, LLM, validation).
---

# Run the Code Review Agent on a target

The analyzed target is **untrusted**: never run, import, or install anything from it.

## Steps

1. Identify the target: snippet (write to a temp `.py` in the scratchpad), directory, or `.zip`.
   Small sample repos for testing live in `tests/fixtures/repos/`.
2. Check which stages are implemented (`src/marl_agents/agents/code_review/`, `ingestion/`, `rag/`,
   `static_analysis/`). If a stage is still a stub, say so and run what exists — don't fake output.
3. Choose the provider: `MockLLMProvider` for pipeline checks (default), or a real provider from `.env`
   only if the user asks (mention the cost).
4. Run via the CLI entry point once it exists:
   ```bash
   python -m marl_agents.cli review <path-or-zip> --provider mock --rag on --out data/reports/<name>
   ```
   Until the CLI exists, use a short script in the scratchpad that builds the agent and calls `run()`.
5. Inspect the output: number of findings per category/severity, validation rejections, dedup merges,
   retrieved context per finding. Show a few representative findings with file:line.
6. When debugging, isolate one stage at a time (e.g. print the chunks for one file, or the top-k retrieval
   for one query) instead of rerunning the whole pipeline.
7. Report numbers exactly as produced. Never round up or add findings by hand.
