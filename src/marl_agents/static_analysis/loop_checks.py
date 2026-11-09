"""Loops that cannot end: a `while` whose condition nothing in the loop can change.

Two shapes, both conservative:

- `while True:` (or another constant truth) with no `break`, `return`, `raise` or exit call that
  belongs to this loop. Generators are skipped: an endless generator is a normal design.
- `while <condition>:` where every name in the condition is a plain local that the loop body never
  assigns, passes to a call, or mutates, and nothing leaves the loop. Conditions that call functions
  or read attributes are skipped, because those can change behind the loop's back.

These are hints with evidence. The LLM and a human decide; nothing is executed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator

from marl_agents.core.schemas import FindingSource
from marl_agents.ingestion.models import Repository
from marl_agents.parsing.python_ast import SymbolKind, parse_tree
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    line_evidence,
    make_finding,
    overlaps_scope,
)
from marl_agents.static_analysis.rules import FLOW_RULES

RULE = "BUG-INFINITE-LOOP"
EXIT_CALLS = {"sys.exit", "exit", "quit", "os._exit", "os.abort"}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _own_nodes(loop: ast.While) -> Iterator[ast.AST]:
    """Nodes of the loop body, not entering nested functions, classes or nested loops' breaks."""
    stack: list[ast.AST] = list(loop.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _leaves(loop: ast.While) -> bool:
    """True if something in the loop can end it: break (of this loop), return, raise, exit."""
    stack: list[tuple[ast.AST, bool]] = [(n, False) for n in loop.body]
    while stack:
        node, nested = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        if isinstance(node, ast.Break) and not nested:
            return True
        if isinstance(node, ast.Return | ast.Raise):
            return True
        if isinstance(node, ast.Call) and _dotted(node.func) in EXIT_CALLS:
            return True
        inner = nested or isinstance(node, ast.For | ast.AsyncFor | ast.While)
        stack.extend((child, inner) for child in ast.iter_child_nodes(node))
    return False


def _always_true(test: ast.expr) -> bool:
    return isinstance(test, ast.Constant) and bool(test.value) and test.value is not Ellipsis


def _plain_names(test: ast.expr) -> set[str] | None:
    """Names in a condition made only of names, constants, comparisons and boolean operators."""
    names: set[str] = set()
    for node in ast.walk(test):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif not isinstance(
            node,
            ast.Constant
            | ast.Compare
            | ast.BoolOp
            | ast.UnaryOp
            | ast.Load
            | ast.cmpop
            | ast.boolop
            | ast.unaryop,
        ):
            return None
    return names


def _changed_names(loop: ast.While) -> set[str]:
    """Names the body could change: assigned, deleted, passed to a call, or used as an object."""
    changed: set[str] = set()
    for node in _own_nodes(loop):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            changed.add(node.id)
        elif isinstance(node, ast.Call):
            for arg in (*node.args, *(k.value for k in node.keywords)):
                changed.update(n.id for n in ast.walk(arg) if isinstance(n, ast.Name))
            if isinstance(node.func, ast.Attribute):
                changed.update(n.id for n in ast.walk(node.func.value) if isinstance(n, ast.Name))
        elif isinstance(node, ast.Global | ast.Nonlocal):
            changed.update(node.names)
        elif isinstance(node, ast.Attribute | ast.Subscript) and isinstance(node.ctx, ast.Store):
            changed.update(n.id for n in ast.walk(node.value) if isinstance(n, ast.Name))
        elif isinstance(node, ast.Await | ast.Yield | ast.YieldFrom):
            changed.add("*")  # another coroutine or the consumer can change state meanwhile
    return changed


def endless_loops(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[tuple[ast.While, str]]:
    """(loop, reason) for each loop in `func` that cannot end."""
    if any(isinstance(n, ast.Yield | ast.YieldFrom) for n in ast.walk(func)):
        return
    for node in ast.walk(func):
        if not isinstance(node, ast.While) or _leaves(node):
            continue
        if _always_true(node.test):
            yield node, "the condition is always true and nothing in the loop leaves it"
            continue
        names = _plain_names(node.test)
        if names and not (names & _changed_names(node)) and "*" not in _changed_names(node):
            listed = ", ".join(f"`{n}`" for n in sorted(names))
            yield node, f"nothing in the loop changes {listed}, so the condition never changes"


class LoopAnalyzer(StaticAnalyzer):
    """Loops that cannot terminate."""

    name = "loop"

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        spec = FLOW_RULES[RULE]
        for path in files:
            module = index.modules.get(path)
            if module is None or module.syntax_error:
                continue
            tree = parse_tree(repo.read_text(path), path)
            if tree is None:
                continue
            for func in ast.walk(tree):
                if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for loop, reason in endless_loops(func):
                    if not overlaps_scope(scope, path, loop.lineno, loop.lineno):
                        continue
                    symbol = module.symbol_at(loop.lineno)
                    out.findings.append(
                        make_finding(
                            source=FindingSource.AST,
                            file=path,
                            start_line=loop.lineno,
                            end_line=loop.lineno,
                            category=spec.category,
                            severity=spec.severity,
                            title=f"Loop in {func.name} can never end",
                            description=f"This `while` loop cannot terminate: {reason}.",
                            confidence=spec.confidence,
                            evidence=[line_evidence(repo, path, loop.lineno, loop.lineno)],
                            recommendation=spec.recommendation,
                            test_recommendation=spec.test_recommendation,
                            rule_id=RULE,
                            symbol=symbol.qualname
                            if symbol is not None and symbol.kind is not SymbolKind.CLASS
                            else None,
                        )
                    )
        return out
