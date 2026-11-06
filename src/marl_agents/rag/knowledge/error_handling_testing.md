# Error handling, edge cases and testing guidance

## Error handling
- Catch the most specific exception possible. `except:` and `except Exception:` hide bugs and,
  for bare `except`, also catch `KeyboardInterrupt`/`SystemExit`.
- Never silently `pass` on an exception: log it (`logger.exception`) and re-raise, or handle it
  meaningfully and document why it is safe to ignore.
- Re-raise with `raise NewError(...) from err` to keep the original traceback.
- Do not `return`/`break` inside `finally`; it discards in-flight exceptions.
- Validate inputs at API boundaries and raise clear, specific errors (`ValueError`, `TypeError`).
- Do not use `assert` for runtime validation of user input; asserts are removed with `python -O`.

## Common edge cases to check
- Empty inputs: empty list/string/dict, zero, `None`.
- Boundaries: first/last element, off-by-one in ranges and slices, integer overflow in other
  languages, very large inputs.
- Division by zero; missing dictionary keys; unexpected types; Unicode and whitespace.
- Concurrency: shared mutable state, race conditions, non-atomic check-then-act.
- External failures: network timeouts, missing files, permission errors, partial writes.

## Testing
- Every public function should have unit tests for: typical input, boundary values, invalid input
  (asserting the exact exception), and regression tests for fixed bugs.
- Tests should be deterministic, isolated, and not depend on network or execution order.
- Assert specific exception types (`pytest.raises(ValueError)`), not `Exception`.
- Use parametrised tests for input tables; mock external services at the boundary.
- Security fixes deserve a test with a malicious input (e.g. `' OR '1'='1` for SQL injection).
