from marl_agents.core.schemas import Category, FindingSource, Severity
from marl_agents.static_analysis import FlowAnalyzer, bug_analyzers, default_analyzers


def rules(make_index, code: str, path: str = "app.py", extra: dict | None = None) -> list[str]:
    index = make_index({path: code, **(extra or {})})
    out = FlowAnalyzer().analyze(index.repo, index, [path])
    return [f.rule_id for f in out.findings]


# ---- None ---------------------------------------------------------------------------------------


def test_dict_get_then_attribute(make_index) -> None:
    code = "def f(d):\n    x = d.get('a')\n    return x.name\n"
    assert rules(make_index, code) == ["BUG-NONE-DEREF"]


def test_regex_match_then_group(make_index) -> None:
    code = "import re\ndef f(s):\n    m = re.match('a', s)\n    return m.group(0)\n"
    assert rules(make_index, code) == ["BUG-NONE-DEREF"]


def test_none_checks_clear_the_fact(make_index) -> None:
    guards = [
        "    if x is None:\n        return 0\n    return x.name\n",
        "    if not x:\n        return 0\n    return x.name\n",
        "    if x is not None:\n        return x.name\n    return 0\n",
        "    if x:\n        return x.name\n    return 0\n",
        "    return x.name if x else 0\n",
        "    return x and x.name\n",
        "    return x is not None and x.name\n",
        "    assert x is not None\n    return x.name\n",
        "    if isinstance(x, str):\n        return x.upper()\n    return ''\n",
        "    if x is None:\n        x = make()\n    return x.name\n",
        "    if x is None or x.name == '':\n        return 0\n    return 1\n",
    ]
    for body in guards:
        code = f"def f(d):\n    x = d.get('a')\n{body}"
        assert rules(make_index, code) == [], body


def test_only_the_unguarded_branch_is_reported(make_index) -> None:
    code = (
        "def f(d, flag):\n"
        "    x = d.get('a')\n"
        "    if flag:\n"
        "        if x is None:\n"
        "            return 0\n"
        "    return x.name\n"
    )
    assert rules(make_index, code) == ["BUG-NONE-DEREF"]


def test_reassignment_clears_the_fact(make_index) -> None:
    code = "def f(d):\n    x = d.get('a')\n    x = g()\n    return x.name\n"
    assert rules(make_index, code) == []


def test_one_report_per_name(make_index) -> None:
    code = "def f(d):\n    x = d.get('a')\n    a = x.one\n    b = x.two\n    return a, b\n"
    assert rules(make_index, code) == ["BUG-NONE-DEREF"]


def test_handled_crash_is_not_reported(make_index) -> None:
    code = (
        "def f(d):\n    x = d.get('a')\n    try:\n        return x.name\n"
        "    except AttributeError:\n        return None\n"
    )
    assert rules(make_index, code) == []


def test_network_get_is_not_a_dict_lookup(make_index) -> None:
    code = "def f(url):\n    r = requests.get(url)\n    return r.json()\n"
    assert rules(make_index, code) == []


def test_default_none_parameter_has_its_own_rule(make_index) -> None:
    code = "def f(items=None):\n    return items.count(1)\n"
    assert rules(make_index, code) == ["BUG-NONE-DEFAULT"]


def test_function_that_can_return_none(make_index) -> None:
    code = (
        "def find(xs):\n"
        "    for x in xs:\n"
        "        if x:\n"
        "            return x\n"
        "    return None\n"
        "def use(xs):\n"
        "    r = find(xs)\n"
        "    return r.name\n"
    )
    assert "BUG-NONE-DEREF" in rules(make_index, code)


def test_function_imported_from_another_file_that_can_return_none(make_index) -> None:
    lookup = "def find(k):\n    if k:\n        return k\n    return None\n"
    code = "from lookup import find\ndef use(k):\n    r = find(k)\n    return r.name\n"
    assert rules(make_index, code, extra={"lookup.py": lookup}) == ["BUG-NONE-DEREF"]


def test_comprehension_guard_is_respected(make_index) -> None:
    code = "def f(d, xs):\n    x = d.get('a')\n    return [x.y for i in xs if x]\n"
    assert rules(make_index, code) == []


# ---- the other checks ----------------------------------------------------------------------------


def test_missing_return(make_index) -> None:
    assert "BUG-MISSING-RETURN" in rules(make_index, "def f(a):\n    if a:\n        return 1\n")


def test_missing_return_ignores_stubs_generators_and_procedures(make_index) -> None:
    for code in (
        "def f(a):\n    if a:\n        return\n    g()\n",
        "def f(a):\n    if a:\n        yield 1\n        return\n",
        "class C:\n    def __init__(self):\n        self.x = 1\n",
    ):
        assert rules(make_index, code) == [], code


def test_division_by_length_of_a_collection(make_index) -> None:
    code = "def mean(xs):\n    return sum(xs) / len(xs)\n"
    assert rules(make_index, code) == ["BUG-DIV-BY-LEN"]


def test_division_with_a_guard_or_inside_the_loop_is_fine(make_index) -> None:
    for code in (
        "def mean(xs):\n    if not xs:\n        return 0\n    return sum(xs) / len(xs)\n",
        "def f(xs):\n    for x in xs:\n        print(x / len(xs))\n",
    ):
        assert rules(make_index, code) == [], code


def test_path_division_is_not_arithmetic(make_index) -> None:
    code = "def f(base, name):\n    return base / name\n"
    assert rules(make_index, code) == []


def test_division_by_numeric_parameter(make_index) -> None:
    code = "def f(total: int, n: int):\n    return total / n\n"
    assert rules(make_index, code) == ["BUG-DIV-BY-LEN"]


def test_off_by_one_range(make_index) -> None:
    code = "def f(xs):\n    for i in range(len(xs) + 1):\n        print(xs[i])\n"
    assert rules(make_index, code) == ["BUG-OFF-BY-ONE"]


def test_next_element_at_the_end_of_the_loop(make_index) -> None:
    code = "def f(xs):\n    for i in range(len(xs)):\n        print(xs[i + 1])\n"
    assert rules(make_index, code) == ["BUG-OFF-BY-ONE"]


def test_index_at_length(make_index) -> None:
    assert rules(make_index, "def f(xs):\n    return xs[len(xs)]\n") == ["BUG-OFF-BY-ONE"]


def test_correct_loops_are_fine(make_index) -> None:
    for code in (
        "def f(xs):\n    for i in range(len(xs)):\n        print(xs[i])\n",
        "def f(xs):\n    for i in range(len(xs) - 1):\n        print(xs[i + 1])\n",
        "def f(xs):\n    for i in range(len(xs)):\n"
        "        if i + 1 < len(xs):\n            print(xs[i + 1])\n",
    ):
        assert rules(make_index, code) == [], code


def test_changing_a_list_while_iterating(make_index) -> None:
    code = "def f(xs):\n    for x in xs:\n        if x:\n            xs.remove(x)\n"
    assert rules(make_index, code) == ["BUG-MUTATE-WHILE-ITERATING"]


def test_changing_it_then_leaving_the_loop_is_fine(make_index) -> None:
    code = (
        "def f(xs):\n    for x in xs:\n        if x:\n            xs.remove(x)\n            break\n"
    )
    assert rules(make_index, code) == []


# ---- as an analyzer ------------------------------------------------------------------------------


def test_scope_limits_what_is_reported(make_index) -> None:
    code = (
        "def a(d):\n    x = d.get('a')\n    return x.name\n"
        + "\n" * 8
        + "def b(d):\n    y = d.get('a')\n    return y.name\n"
    )
    index = make_index({"app.py": code})
    out = FlowAnalyzer().analyze(index.repo, index, ["app.py"], {"app.py": [(12, 14)]})
    assert [f.start_line for f in out.findings] == [14]


def test_finding_comes_from_the_rule_table_and_cites_real_code(make_index) -> None:
    index = make_index({"app.py": "def f(d):\n    x = d.get('a')\n    return x.name\n"})
    finding = FlowAnalyzer().analyze(index.repo, index, ["app.py"]).findings[0]
    assert finding.category is Category.BUG and finding.severity is Severity.HIGH
    assert finding.sources == [FindingSource.AST] and finding.symbol == "f"
    assert finding.evidence == ["return x.name"]


def test_syntax_error_is_skipped_not_raised(make_index) -> None:
    index = make_index({"app.py": "def f(:\n"})
    assert FlowAnalyzer().analyze(index.repo, index, ["app.py"]).findings == []


def test_code_review_analyzers_are_unchanged() -> None:
    """Saved Code Review baselines must stay comparable."""
    assert "flow" not in [a.name for a in default_analyzers()]
    assert "flow" in [a.name for a in bug_analyzers()]
