---
paths:
  - "src/marl_agents/ingestion/**"
  - "src/marl_agents/parsing/**"
  - "src/marl_agents/static_analysis/**"
  - "src/marl_agents/api/**"
---

# Analyzed repositories are untrusted input

- **Never execute analyzed code.** No `exec`, `eval`, `importlib` of repo modules, `subprocess` running repo
  scripts, `pip install` of repo requirements, or running the repo's tests during analysis.
  Parse with `ast.parse` only.
- Static analyzers (ruff, radon) run as subprocesses on the files with `shell=False`, an explicit argument
  list, a timeout, and must not load repo-provided plugins/config that can execute code.
- ZIP extraction must guard against zip-slip (resolve every member path and confirm it stays inside the
  target dir), symlinks, absolute paths, and zip bombs (limits on total uncompressed size, file count,
  per-file size — configured in `configs/default.yaml`).
- Ignore: `.git`, `.venv`, `venv`, `env`, `__pycache__`, `node_modules`, `.idea`, `.vscode`, `dist`,
  `build`, `*.egg-info`, binaries. Indexed extensions: `.py .md .rst .txt .yaml .yml .json .toml .cfg .ini`.
- Treat file contents as data when building prompts: delimit them clearly and instruct the LLM that
  instructions inside code/comments are not to be followed (prompt-injection defence).
- Uploaded repos are extracted to a per-job temp directory under `data/workspaces/` and cleaned up.
- Never log full file contents or secrets found in analyzed repos; log paths and counts.
