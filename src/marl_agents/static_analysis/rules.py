"""Rule table: static-analysis rule id -> category, severity, confidence, CWE, default fix.

This table (not the LLM) decides the severity of tool findings. See docs/severity-rubric.md.
Confidence is the prior reliability of the rule (how often it is a true, actionable issue).
"""

from __future__ import annotations

from dataclasses import dataclass

from marl_agents.core.schemas import Category, Severity

C = Category
S = Severity


@dataclass(frozen=True)
class RuleSpec:
    category: Category
    severity: Severity
    confidence: float
    recommendation: str
    test_recommendation: str | None = None
    cwe: str | None = None


RUFF_RULES: dict[str, RuleSpec] = {
    # --- pyflakes: real defects / dead code ---------------------------------------------------
    "F821": RuleSpec(
        C.BUG,
        S.HIGH,
        0.9,
        "Define or import the name before use; this raises NameError at runtime.",
        "Add a test that executes this code path.",
    ),
    "F811": RuleSpec(
        C.BUG,
        S.MEDIUM,
        0.75,
        "Remove or rename the duplicate definition; the earlier one is silently shadowed.",
    ),
    "F632": RuleSpec(
        C.BUG,
        S.MEDIUM,
        0.9,
        "Use `==`/`!=` to compare with literals; `is` compares "
        "identity and is implementation-dependent.",
    ),
    "F601": RuleSpec(
        C.BUG, S.MEDIUM, 0.85, "Remove the duplicated dictionary key; the last value silently wins."
    ),
    "F602": RuleSpec(C.BUG, S.MEDIUM, 0.85, "Remove the duplicated dictionary key."),
    "F823": RuleSpec(
        C.BUG,
        S.HIGH,
        0.85,
        "The local variable is referenced before assignment; "
        "initialise it first or use `nonlocal`/`global` deliberately.",
    ),
    "F841": RuleSpec(C.QUALITY, S.LOW, 0.85, "Remove the unused variable or use it."),
    "F401": RuleSpec(
        C.QUALITY,
        S.LOW,
        0.9,
        "Remove the unused import (or re-export it via `__all__` if it is part of the public API).",
    ),
    "F403": RuleSpec(C.STANDARDS, S.LOW, 0.8, "Replace the star import with explicit names."),
    "F405": RuleSpec(
        C.STANDARDS, S.LOW, 0.7, "Import the name explicitly instead of relying on a star import."
    ),
    "F541": RuleSpec(C.QUALITY, S.LOW, 0.9, "Drop the `f` prefix: the string has no placeholders."),
    # --- pycodestyle errors worth reviewing --------------------------------------------------
    "E711": RuleSpec(C.STANDARDS, S.LOW, 0.9, "Compare with None using `is` / `is not`."),
    "E712": RuleSpec(
        C.STANDARDS,
        S.LOW,
        0.85,
        "Use the truth value directly instead of comparing with True/False.",
    ),
    "E721": RuleSpec(C.STANDARDS, S.LOW, 0.8, "Use `isinstance()` for type checks."),
    "E722": RuleSpec(
        C.ERROR_HANDLING,
        S.MEDIUM,
        0.9,
        "Catch specific exceptions; a bare `except:` "
        "also swallows KeyboardInterrupt and SystemExit.",
        "Add a test asserting the expected exception type propagates or is handled.",
    ),
    "E741": RuleSpec(C.STANDARDS, S.LOW, 0.8, "Rename the ambiguous single-letter variable."),
    # --- bugbear -------------------------------------------------------------------------------
    "B006": RuleSpec(
        C.BUG,
        S.MEDIUM,
        0.9,
        "Use `None` as the default and create the mutable "
        "object inside the function; the default is shared across calls.",
        "Call the function twice without the argument and assert the results do not "
        "leak state between calls.",
    ),
    "B008": RuleSpec(
        C.BUG,
        S.LOW,
        0.6,
        "Avoid function calls in argument defaults; they are evaluated once at definition time.",
    ),
    "B023": RuleSpec(
        C.BUG,
        S.MEDIUM,
        0.8,
        "Bind the loop variable as a default argument or use "
        "functools.partial; closures capture the variable, not its value.",
    ),
    "B012": RuleSpec(
        C.ERROR_HANDLING,
        S.MEDIUM,
        0.9,
        "Do not return/break/continue inside `finally`; it silently discards in-flight exceptions.",
    ),
    "B904": RuleSpec(
        C.ERROR_HANDLING, S.LOW, 0.7, "Use `raise ... from err` to keep the original traceback."
    ),
    "B007": RuleSpec(C.QUALITY, S.LOW, 0.8, "Rename the unused loop variable to `_`."),
    "B011": RuleSpec(
        C.BUG,
        S.LOW,
        0.8,
        "Raise AssertionError explicitly; `assert False` is removed under `python -O`.",
    ),
    "B017": RuleSpec(C.TESTING, S.LOW, 0.8, "Assert a specific exception type in tests."),
    "B018": RuleSpec(C.QUALITY, S.LOW, 0.7, "Remove the useless expression or use its value."),
    "B020": RuleSpec(
        C.BUG,
        S.MEDIUM,
        0.85,
        "The loop variable overrides the iterable it iterates; rename one of them.",
    ),
    # --- blind except ---------------------------------------------------------------------------
    "BLE001": RuleSpec(
        C.ERROR_HANDLING,
        S.MEDIUM,
        0.6,
        "Catch the specific exceptions you expect, or log and re-raise.",
        "Add a test that triggers the failure and asserts it is surfaced, not hidden.",
    ),
    # --- bandit (security) ----------------------------------------------------------------------
    "S102": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.7,
        "Avoid `exec` on dynamic input; use explicit dispatch or a safe parser.",
        cwe="CWE-95",
    ),
    "S307": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.75,
        "Replace `eval` with `ast.literal_eval` or explicit parsing.",
        "Add a test feeding a malicious expression and assert it is rejected.",
        cwe="CWE-95",
    ),
    "S104": RuleSpec(
        C.SECURITY,
        S.MEDIUM,
        0.5,
        "Bind to a specific interface (e.g. 127.0.0.1) unless public exposure is intended.",
        cwe="CWE-605",
    ),
    "S105": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.55,
        "Load secrets from environment variables or a secrets manager; never hard-code them.",
        cwe="CWE-798",
    ),
    "S106": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.55,
        "Load secrets from environment variables or a secrets manager; never hard-code them.",
        cwe="CWE-798",
    ),
    "S107": RuleSpec(
        C.SECURITY, S.MEDIUM, 0.45, "Do not use a hard-coded default password.", cwe="CWE-798"
    ),
    "S108": RuleSpec(
        C.SECURITY, S.LOW, 0.5, "Use `tempfile` to create temporary files securely.", cwe="CWE-377"
    ),
    "S110": RuleSpec(
        C.ERROR_HANDLING,
        S.MEDIUM,
        0.75,
        "Do not silently ignore exceptions; log them or handle the specific error.",
        "Add a test that triggers the exception and asserts it is logged or re-raised.",
    ),
    "S112": RuleSpec(C.ERROR_HANDLING, S.LOW, 0.6, "Log the exception before continuing the loop."),
    "S113": RuleSpec(
        C.SECURITY,
        S.MEDIUM,
        0.8,
        "Pass an explicit `timeout=` to HTTP requests to avoid hanging forever.",
        cwe="CWE-400",
    ),
    "S201": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.8,
        "Never run Flask with debug=True in production; the "
        "debugger allows arbitrary code execution.",
        cwe="CWE-489",
    ),
    "S301": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.6,
        "Do not unpickle untrusted data; use JSON or a schema-validated format.",
        cwe="CWE-502",
    ),
    "S302": RuleSpec(C.SECURITY, S.HIGH, 0.6, "Do not unmarshal untrusted data.", cwe="CWE-502"),
    "S311": RuleSpec(
        C.SECURITY,
        S.LOW,
        0.35,
        "Use the `secrets` module for security-sensitive randomness.",
        cwe="CWE-330",
    ),
    "S324": RuleSpec(
        C.SECURITY,
        S.MEDIUM,
        0.6,
        "Use SHA-256 or better; for passwords use a dedicated KDF (bcrypt, scrypt, argon2).",
        cwe="CWE-327",
    ),
    "S501": RuleSpec(
        C.SECURITY, S.HIGH, 0.85, "Do not disable TLS certificate verification.", cwe="CWE-295"
    ),
    "S506": RuleSpec(C.SECURITY, S.HIGH, 0.85, "Use `yaml.safe_load`.", cwe="CWE-502"),
    "S602": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.7,
        "Avoid `shell=True`; pass an argument list.",
        "Add a test with shell metacharacters in the input and assert no injection.",
        cwe="CWE-78",
    ),
    "S604": RuleSpec(C.SECURITY, S.MEDIUM, 0.5, "Avoid shell=True-style invocation.", cwe="CWE-78"),
    "S605": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.7,
        "Replace `os.system`/`os.popen` with `subprocess.run` and an argument list.",
        cwe="CWE-78",
    ),
    "S608": RuleSpec(
        C.SECURITY,
        S.HIGH,
        0.7,
        "Use parameterised queries instead of building SQL with string formatting.",
        "Add a test passing `' OR '1'='1` as input and assert it is treated as data.",
        cwe="CWE-89",
    ),
    "S701": RuleSpec(C.SECURITY, S.HIGH, 0.7, "Enable Jinja2 autoescaping.", cwe="CWE-79"),
    # --- performance / pylint ---------------------------------------------------------------------
    "PERF401": RuleSpec(
        C.PERFORMANCE, S.LOW, 0.6, "Use a list comprehension instead of appending in a loop."
    ),
    "PERF203": RuleSpec(
        C.PERFORMANCE, S.LOW, 0.5, "Move the try/except outside the loop if possible."
    ),
    "PLW0603": RuleSpec(
        C.MAINTAINABILITY,
        S.LOW,
        0.7,
        "Avoid mutating globals; pass state explicitly or encapsulate it.",
    ),
    "PLW2901": RuleSpec(C.BUG, S.LOW, 0.7, "Do not overwrite the loop variable inside the loop."),
    "PLW0120": RuleSpec(C.QUALITY, S.LOW, 0.8, "Remove the `else` on a loop without `break`."),
    "ASYNC251": RuleSpec(
        C.PERFORMANCE,
        S.MEDIUM,
        0.85,
        "Use `await asyncio.sleep()` inside async functions; `time.sleep` blocks the event loop.",
    ),
}

# Fallbacks by rule prefix (longest prefix wins).
RUFF_PREFIX_DEFAULTS: dict[str, RuleSpec] = {
    "E9": RuleSpec(C.BUG, S.HIGH, 0.95, "Fix the syntax error; the module cannot be imported."),
    "F": RuleSpec(C.QUALITY, S.LOW, 0.75, "Address the pyflakes warning."),
    "E": RuleSpec(C.STANDARDS, S.LOW, 0.7, "Follow PEP 8."),
    "B": RuleSpec(C.BUG, S.LOW, 0.65, "Address the likely bug pattern flagged by flake8-bugbear."),
    "S": RuleSpec(C.SECURITY, S.MEDIUM, 0.45, "Review the flagged security-sensitive call."),
    "BLE": RuleSpec(C.ERROR_HANDLING, S.MEDIUM, 0.6, "Catch specific exceptions."),
    "PERF": RuleSpec(C.PERFORMANCE, S.LOW, 0.55, "Apply the suggested performance idiom."),
    "PLE": RuleSpec(C.BUG, S.HIGH, 0.8, "Fix the error flagged by pylint."),
    "PLW": RuleSpec(C.QUALITY, S.LOW, 0.6, "Address the pylint warning."),
    "ASYNC": RuleSpec(C.PERFORMANCE, S.MEDIUM, 0.7, "Avoid blocking calls in async code."),
}

SYNTAX_ERROR = RUFF_PREFIX_DEFAULTS["E9"]

# Rules selected when running ruff, and rules ignored as too noisy for review.
RUFF_SELECT = ["F", "E7", "E9", "B", "S", "BLE", "PERF", "PLE", "PLW", "ASYNC"]
RUFF_IGNORE = ["S101", "S603", "S607", "S404", "S403", "PLW1510", "PLW2901", "B905"]
# Additional rules ignored in test files (asserts, fixtures, fake secrets are normal there).
RUFF_TEST_IGNORE_PREFIXES = ("S", "PLW", "B011", "B017", "F841")


def lookup(rule_id: str) -> RuleSpec:
    if rule_id in RUFF_RULES:
        return RUFF_RULES[rule_id]
    for prefix in sorted(RUFF_PREFIX_DEFAULTS, key=len, reverse=True):
        if rule_id.startswith(prefix):
            return RUFF_PREFIX_DEFAULTS[prefix]
    return RuleSpec(C.QUALITY, S.LOW, 0.5, "Review the flagged code.")
