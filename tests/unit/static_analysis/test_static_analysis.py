import pytest

from marl_agents.core.schemas import Category, Severity
from marl_agents.static_analysis import (
    AstChecksAnalyzer,
    RadonAnalyzer,
    RuffAnalyzer,
    SecretsAnalyzer,
    TestGapAnalyzer,
)
from marl_agents.static_analysis.ast_checks import redact
from marl_agents.static_analysis.ruff_analyzer import find_ruff
from marl_agents.static_analysis.rules import lookup


def run(analyzer, index):  # type: ignore[no-untyped-def]
    files = [f.path for f in index.repo.files]
    return analyzer.analyze(index.repo, index, files)


# ---- rule table ------------------------------------------------------------------------------


def test_rule_lookup_exact_prefix_and_default() -> None:
    assert lookup("S608").severity is Severity.HIGH and lookup("S608").cwe == "CWE-89"
    assert lookup("E999").category is Category.BUG  # E9 prefix: syntax error
    assert lookup("B999").category is Category.BUG  # bugbear default
    assert lookup("ZZZ1").severity is Severity.LOW  # unknown rule


# ---- ruff --------------------------------------------------------------------------------------


@pytest.mark.skipif(find_ruff() is None, reason="ruff not installed")
def test_ruff_findings_are_mapped_and_located(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(
        {
            "app/q.py": (
                "import os\n\n"
                "def find(cur, name):\n"
                "    cur.execute(f\"SELECT * FROM t WHERE n = '{name}'\")\n"
                "    try:\n"
                "        return cur.fetchone()\n"
                "    except:\n"
                "        return None\n"
            ),
            "tests/test_q.py": "import os\n\ndef test_x():\n    assert True\n",
        }
    )
    out = run(RuffAnalyzer(), index)
    by_rule = {f.rule_id: f for f in out.findings}
    assert {"F401", "S608", "E722"} <= set(by_rule)
    assert by_rule["S608"].start_line == 4 and by_rule["S608"].category is Category.SECURITY
    assert by_rule["S608"].symbol == "find"
    assert "cur.execute" in by_rule["S608"].evidence[0]
    # test file: F401 still applies, security rules do not
    test_rules = {f.rule_id for f in out.findings if f.file.startswith("tests/")}
    assert "F401" in test_rules and not any(r and r.startswith("S") for r in test_rules)


@pytest.mark.skipif(find_ruff() is None, reason="ruff not installed")
def test_ruff_reports_syntax_errors(make_index) -> None:  # type: ignore[no-untyped-def]
    out = run(RuffAnalyzer(), make_index({"bad.py": "def f(:\n    pass\n"}))
    assert any(f.category is Category.BUG and f.severity is Severity.HIGH for f in out.findings)


@pytest.mark.skipif(find_ruff() is None, reason="ruff not installed")
def test_ruff_ignores_repo_config(make_index) -> None:  # type: ignore[no-untyped-def]
    # a malicious/odd config in the analyzed repo must not change our rule set (--isolated)
    index = make_index({"ruff.toml": "lint.ignore = ['F401']\n", "m.py": "import os\n"})
    assert any(f.rule_id == "F401" for f in run(RuffAnalyzer(), index).findings)


def test_ruff_missing_binary_is_reported_not_fatal(make_index) -> None:  # type: ignore[no-untyped-def]
    analyzer = RuffAnalyzer()
    analyzer.binary = None
    out = run(analyzer, make_index({"m.py": "import os\n"}))
    assert out.skipped and out.errors and not out.findings


# ---- radon -----------------------------------------------------------------------------------


def _branchy(n: int) -> str:
    body = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(n))
    return f"def branchy(x):\n{body}    return -1\n"


def test_radon_flags_only_complex_functions(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(
        {"a.py": _branchy(12) + "\n" + "def simple():\n    return 1\n", "b.py": _branchy(20)}
    )
    out = run(RadonAnalyzer(), index)
    by_file = {f.file: f for f in out.findings}
    assert set(by_file) == {"a.py", "b.py"}
    assert by_file["a.py"].severity is Severity.LOW  # CC 13
    assert by_file["b.py"].severity is Severity.MEDIUM  # CC 21
    assert by_file["a.py"].rule_id == "RADON-CC" and by_file["a.py"].start_line == 1


# ---- custom AST checks -------------------------------------------------------------------------


AST_SOURCE = """
def leak(p):
    fh = open(p)
    return fh.read()

def ok_with(p):
    with open(p) as fh:
        return fh.read()

def ok_closed(p):
    fh = open(p)
    data = fh.read()
    fh.close()
    return data

def ok_return(p):
    return open(p)

def swallow():
    try:
        risky()
    except Exception:
        pass

def logs():
    try:
        risky()
    except Exception:
        log.exception("x")

def many(a, b, c, d, e, f, g):
    return a

def nested(x):
    if x:
        for i in x:
            while i:
                try:
                    if i:
                        return i
                except ValueError:
                    raise
"""


def test_ast_checks(make_index) -> None:  # type: ignore[no-untyped-def]
    out = run(AstChecksAnalyzer(), make_index({"m.py": AST_SOURCE}))
    rules = [(f.rule_id, f.symbol) for f in out.findings if f.rule_id != "AST-MISSING-DOCSTRING"]
    assert ("AST-RESOURCE-LEAK", "leak") in rules
    assert sum(1 for r, _ in rules if r == "AST-RESOURCE-LEAK") == 1  # with/close/return are fine
    assert ("AST-SWALLOWED-EXCEPTION", "swallow") in rules
    assert not any(r == "AST-SWALLOWED-EXCEPTION" and s == "logs" for r, s in rules)
    assert ("AST-TOO-MANY-PARAMS", "many") in rules
    assert ("AST-DEEP-NESTING", "nested") in rules


def test_ast_checks_skip_test_files(make_index) -> None:  # type: ignore[no-untyped-def]
    out = run(AstChecksAnalyzer(), make_index({"tests/test_m.py": AST_SOURCE}))
    assert out.findings == []


def test_missing_docstring_only_for_long_public_functions(make_index) -> None:  # type: ignore[no-untyped-def]
    long_body = "".join(f"    x{i} = {i}\n" for i in range(12))
    src = f"def public():\n{long_body}\ndef _private():\n{long_body}\ndef short():\n    return 1\n"
    out = run(AstChecksAnalyzer(), make_index({"m.py": src}))
    assert [f.symbol for f in out.findings if f.rule_id == "AST-MISSING-DOCSTRING"] == ["public"]


# ---- secrets -----------------------------------------------------------------------------------


def test_secret_scanning_finds_real_keys_skips_placeholders_and_redacts(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(
        {
            "settings.yaml": "aws_key: AKIAQ3EGUSPW7XJ2LM4K\nplaceholder: AKIAIOSFODNN7EXAMPLE\n",
            "app.py": 'api_key = "sk-abcdefghijklmnopqrstuvwxyz123456"\npassword = "changeme-please"\n',
            "tests/test_app.py": 'token = "ghp_' + "a" * 36 + '"\n',
        }
    )
    out = run(SecretsAnalyzer(), index)
    located = sorted((f.file, f.start_line) for f in out.findings)
    assert located == [("app.py", 1), ("settings.yaml", 1)]
    for f in out.findings:
        assert f.cwe == "CWE-798" and "****" in f.evidence[0]
        assert (
            "AKIAQ3EGUSPW7XJ2LM4K" not in f.evidence[0] and "abcdefghijklmnop" not in f.evidence[0]
        )
    assert redact("key = AKIAQ3EGUSPW7XJ2LM4K") == "key = AKIA****"


# ---- test gaps -------------------------------------------------------------------------------


FUNC = "def {name}(x):\n    y = x + 1\n    y = y * 2\n    y = y - 3\n    return y\n\n"


def test_test_gap_no_tests_at_all(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index({"app.py": FUNC.format(name="alpha") + FUNC.format(name="beta")})
    out = run(TestGapAnalyzer(), index)
    assert len(out.findings) == 1 and out.findings[0].rule_id == "TEST-NO-TESTS"
    assert "alpha" in out.findings[0].description and "beta" in out.findings[0].description


def test_test_gap_unreferenced_functions(make_index) -> None:  # type: ignore[no-untyped-def]
    index = make_index(
        {
            "app.py": FUNC.format(name="alpha") + FUNC.format(name="beta"),
            "tests/test_app.py": "from app import alpha\n\ndef test_alpha():\n    assert alpha(1)\n",
        }
    )
    out = run(TestGapAnalyzer(), index)
    assert [f.symbol for f in out.findings] == ["beta"]
    assert out.findings[0].severity is Severity.INFO
