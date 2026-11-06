# Python coding standards (review checklist)

Condensed from PEP 8, PEP 257, PEP 20 and common industry review guidelines.

## Naming and readability
- Modules and functions use `snake_case`, classes `CapWords`, constants `UPPER_CASE` (PEP 8).
- Avoid single-letter names except loop indices and well-known math notation; never `l`, `O`, `I`.
- Functions should do one thing; prefer early returns (guard clauses) over deep nesting.
- Functions longer than ~50-80 lines or with more than ~5-6 parameters are hard to test; split them
  or group parameters into a dataclass.
- Cyclomatic complexity above 10 indicates a function that needs refactoring and more tests.

## Documentation
- Public modules, classes and functions need docstrings (PEP 257) describing purpose, parameters,
  return value and raised exceptions.
- Comments explain *why*, not *what*. Remove commented-out code.
- Keep README and API docs in sync with behaviour changes.

## Imports and structure
- One import per line, grouped stdlib / third-party / local; no wildcard `from x import *`.
- Remove unused imports and variables.
- Avoid circular imports and module-level side effects (network calls, heavy work at import time).

## Types and data
- Add type hints to public APIs; run a type checker.
- Never use mutable default arguments (`def f(x=[])`); use `None` and create inside.
- Compare with `None` using `is` / `is not`; use `isinstance` rather than `type(x) == T`.
- Prefer `pathlib` over string path manipulation; open files with an explicit encoding.

## Resource management
- Use context managers (`with`) for files, locks, sockets and database connections so they are
  released even when exceptions occur.
- Close HTTP sessions and database cursors; set timeouts on all network calls.

## Performance
- Avoid quadratic loops over large collections; use sets/dicts for membership tests.
- Do not concatenate strings in loops; use `"".join(...)`.
- Never call blocking functions (`time.sleep`, synchronous I/O) inside `async def` functions.
- Avoid repeated expensive work inside loops (regex compilation, queries: N+1 query problem).
