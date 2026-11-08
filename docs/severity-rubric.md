# Severity rubric

Severity is decided by this rubric (and static-analysis rule tables), not freely by the LLM. The LLM may
propose a level with a justification; `findings.severity` applies the rubric and records the final level.

| Level | Criteria | Examples |
|---|---|---|
| **critical** | Exploitable security flaw or certain data loss/corruption reachable in normal use | SQL injection with user input, hard-coded production secret, `pickle.loads` on request data, auth bypass |
| **high** | Likely incorrect behaviour or security weakness on realistic inputs; crash in a main path | missing authorization check, unhandled `None` on a common path, off-by-one dropping data, weak crypto for passwords |
| **medium** | Bug under edge conditions, or maintainability problem that materially raises defect risk | broad `except Exception` hiding errors, resource not closed, cyclomatic complexity > 15, missing input validation on internal API |
| **low** | Code-quality / standards issue with little direct risk | unused import, poor naming, duplicated small block, missing type hints |
| **info** | Suggestion or observation, no defect | refactoring idea, docstring could be clearer, possible test to add |

## How it is enforced (`src/marl_agents/findings/severity.py`)

1. **Static findings** get their severity from the rule table in
   `src/marl_agents/static_analysis/rules.py` (e.g. `F401 -> low`, `S608 -> high`, `E722 -> medium`,
   Radon CC 11-15 -> low, > 15 -> medium; AWS/private keys -> critical). The LLM never changes these.
   Control-flow checks use `FLOW_RULES` in the same file (`BUG-NONE-DEREF` -> high,
   `BUG-OFF-BY-ONE` -> high, the others -> medium).
2. **LLM-only findings** keep the LLM's *proposed* severity (stored in `proposed_severity`) subject to:
   - security floor: at least `medium`;
   - low-confidence cap: confidence < 0.5 cannot be above `medium`.
3. **Category ceilings** (all sources): standards and documentation <= `low`; quality, maintainability
   and testing <= `medium`; performance <= `high`.
4. **No evidence** -> at most `low`.
5. When duplicates merge, the merged finding takes the higher severity, then steps 2-4 apply again.

Every cap/floor applied is recorded in the finding's `notes` (audit trail).

## Confidence (`src/marl_agents/findings/confidence.py`)

A 0-1 **ranking/filtering signal, not a probability of correctness**:
- static findings start from the rule's prior reliability (rule table);
- LLM self-reported confidence x 0.8, ceiling 0.9 (LLMs are over-confident);
- independent agreement of two sources: `1 - (1-a)(1-b)`;
- relocated by the validator: x 0.85; LLM disputes a static finding: x 0.5; LLM confirms: +30% of the gap.
Findings below `review.min_confidence` (default 0.3) are dropped, except `critical` ones.
