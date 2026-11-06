---
name: capstone-writeup
description: Draft or revise capstone deliverables — review presentations, report chapters, literature survey rows, problem definition, objectives, architecture explanations, viva answers — consistent with the approved project. Use when the user asks for slides content, report text, or explanations for reviewers/panel.
---

# Capstone write-up

Audience: the review panel and project guide (Amrita B.Tech, 23CSE399). Academic, precise, defensible.

## Source of truth

- Approved deck: `PPT/Finalyear_2027_23UG082.pptx` (problem definition, 10-paper literature survey,
  limitations/research gap, architecture figs 1–3, tools, datasets, conclusion). Extract text with
  `python-pptx`; don't contradict it without flagging the change.
- `CLAUDE.md`, `docs/architecture.md`, `docs/decisions.md`, `docs/datasets.md`.
- Results: only `experiments/results/**` and `docs/results.md`.

## Review presentation structure

Introduction → Motivation → Literature Survey → Identified Gaps → Problem Definition → Objectives →
Proposed Architecture → Modules in Proposed Work → Impact (later reviews add Implementation, Results,
Conclusion & Future Work).

## Framing rules

- The gap is **integration**: existing work targets single SE tasks; this project combines five specialized
  agents + repository-aware RAG + common orchestration + agent- and system-level evaluation.
  Never claim "no one has done AI code review".
- We **do not train an LLM**; contribution is the system around a pretrained LLM.
- Research questions: does agent specialization help? does repository RAG help? how does the full system
  compare with a single-LLM baseline under the same setup?
- **No invented results.** Numbers only from saved runs; otherwise write "to be measured" or mark as
  illustrative. Flag any placeholder UI numbers (e.g. "Code Quality 91%") as mock-ups.
- Citations: only papers that exist and that the user has or can verify; keep the deck's reference style.
  If unsure a paper exists, say so rather than inventing a citation.
- For .pptx/.docx output use the pptx/docx skills; keep the team's existing template.
