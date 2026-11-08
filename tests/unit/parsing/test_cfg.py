import ast

from marl_agents.parsing.cfg import CFG, build_cfg


def cfg_of(code: str) -> CFG:
    func = ast.parse(code).body[0]
    assert isinstance(func, ast.FunctionDef)
    return build_cfg(func)


def test_plain_function_falls_off_the_end() -> None:
    assert cfg_of("def f():\n    x = 1\n").can_fall_off()


def test_return_on_every_path_cannot_fall_off() -> None:
    code = "def f(a):\n    if a:\n        return 1\n    else:\n        return 2\n"
    assert not cfg_of(code).can_fall_off()


def test_if_without_else_can_fall_off() -> None:
    assert cfg_of("def f(a):\n    if a:\n        return 1\n").can_fall_off()


def test_raise_ends_a_path() -> None:
    code = "def f(a):\n    if a:\n        return 1\n    raise ValueError\n"
    assert not cfg_of(code).can_fall_off()


def test_sys_exit_ends_a_path() -> None:
    code = "def f(a):\n    if a:\n        return 1\n    sys.exit(1)\n"
    assert not cfg_of(code).can_fall_off()


def test_infinite_loop_without_break_cannot_fall_off() -> None:
    code = "def f():\n    while True:\n        if g():\n            return 1\n"
    assert not cfg_of(code).can_fall_off()


def test_break_leaves_an_infinite_loop() -> None:
    code = "def f():\n    while True:\n        if g():\n            break\n"
    assert cfg_of(code).can_fall_off()


def test_for_loop_may_run_zero_times() -> None:
    assert cfg_of("def f(xs):\n    for x in xs:\n        return x\n").can_fall_off()


def test_try_handler_is_a_path_of_its_own() -> None:
    code = "def f():\n    try:\n        return g()\n    except KeyError:\n        log()\n"
    assert cfg_of(code).can_fall_off()
    code = "def f():\n    try:\n        return g()\n    except KeyError:\n        return 0\n"
    assert not cfg_of(code).can_fall_off()


def test_code_after_return_is_unreachable() -> None:
    cfg = cfg_of("def f():\n    return 1\n    x = 2\n")
    assert len(cfg.reachable()) < len(cfg.blocks)


def test_match_without_wildcard_can_fall_off() -> None:
    code = "def f(a):\n    match a:\n        case 1:\n            return 1\n"
    assert cfg_of(code).can_fall_off()
    code += "        case _:\n            return 2\n"
    assert not cfg_of(code).can_fall_off()


def test_edges_from_a_test_carry_its_outcome() -> None:
    cfg = cfg_of("def f(a):\n    if a:\n        x = 1\n    else:\n        x = 2\n    return x\n")
    outcomes = {e.outcome for b in cfg.blocks.values() for e in b.edges if e.test is not None}
    assert outcomes == {True, False}
