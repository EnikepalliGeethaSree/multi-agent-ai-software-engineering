"""Design checks for code review: duplicated functions and PEP 8 naming.

Duplicates are found by structure, not text: two functions match when their bodies have the same
syntax tree once local names are replaced by placeholders, so a copy with renamed variables still
counts. Short functions are ignored, because small helpers often look alike on purpose.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterator

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.python_ast import parse_tree
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    line_evidence,
    make_finding,
    overlaps_scope,
)

MIN_DUPLICATE_STATEMENTS = 5
SNAKE = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
DUNDER = re.compile(r"^__[a-z][a-z0-9_]*__$")
CAPWORDS = re.compile(r"^_?[A-Z][A-Za-z0-9]*$")
# Names a framework dictates, so they are not the author's choice.
FRAMEWORK_NAMES = re.compile(
    r"^(visit_|depart_|generic_visit$|setUp|tearDown|setUpClass|tearDownClass|setUpModule|"
    r"tearDownModule|asyncSetUp|asyncTearDown)"
)

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class _Placeholders(ast.NodeTransformer):
    """Rename every local name and argument by order of first use."""

    def __init__(self) -> None:
        self.names: dict[str, str] = {}

    def _alias(self, name: str) -> str:
        return self.names.setdefault(name, f"v{len(self.names)}")

    def visit_Name(self, node: ast.Name) -> ast.AST:
        return ast.copy_location(ast.Name(id=self._alias(node.id), ctx=node.ctx), node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._alias(node.arg)
        node.annotation = None
        return node


def _body_without_docstring(func: FunctionNode) -> list[ast.stmt]:
    body = list(func.body)
    first = body[0] if body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    return body


def structural_key(func: FunctionNode) -> str | None:
    """A fingerprint equal for functions that differ only in names; None for small ones."""
    body = _body_without_docstring(func)
    statements = sum(1 for stmt in body for n in ast.walk(stmt) if isinstance(n, ast.stmt))
    if statements < MIN_DUPLICATE_STATEMENTS:
        return None
    copy = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
    args = ast.parse(ast.unparse(func.args).join(("def _(", "): pass"))).body[0]
    renamer = _Placeholders()
    renamer.visit(args)
    renamer.visit(copy)
    dump = ast.dump(args, annotate_fields=False) + ast.dump(copy, annotate_fields=False)
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def _functions(tree: ast.Module) -> Iterator[FunctionNode]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def naming_problem(kind: str, name: str) -> str | None:
    """What is wrong with a name under PEP 8, or None."""
    if kind == "class":
        return None if CAPWORDS.match(name) else "class names use CapWords"
    if DUNDER.match(name) or FRAMEWORK_NAMES.match(name):
        return None
    if SNAKE.match(name):
        return None
    return f"{kind} names use lower_case_with_underscores"


class DesignChecksAnalyzer(StaticAnalyzer):
    """Duplicated functions across the repository and PEP 8 naming of definitions."""

    name = "design"

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        first_seen: dict[str, tuple[str, FunctionNode]] = {}
        python = [
            f
            for f in sorted(repo.by_path)
            if repo.by_path[f].language == "python" and repo.by_path[f].kind is not FileKind.TEST
        ]
        reviewed = set(files)
        for rel in python:
            tree = parse_tree(repo.read_text(rel), rel)
            if tree is None:
                continue
            for func in _functions(tree):
                key = structural_key(func)
                if key is None:
                    continue
                if key not in first_seen:
                    first_seen[key] = (rel, func)
                    continue
                if rel in reviewed and overlaps_scope(scope, rel, func.lineno, func.lineno):
                    out.findings.append(self._duplicate(repo, rel, func, *first_seen[key]))
            if rel in reviewed:
                out.findings.extend(self._naming(repo, rel, tree, scope))
        return out

    @staticmethod
    def _duplicate(
        repo: Repository, rel: str, func: FunctionNode, first_file: str, first: FunctionNode
    ) -> Finding:
        where = f"{first_file}:{first.lineno}"
        return make_finding(
            source=FindingSource.AST,
            file=rel,
            start_line=func.lineno,
            end_line=func.lineno,
            category=Category.MAINTAINABILITY,
            severity=Severity.LOW,
            title=f"Duplicated function {func.name} (same as {first.name} at {where})",
            description=(
                f"`{func.name}` has the same structure as `{first.name}` in {where}, apart from "
                "names. A fix applied to one copy can be missed in the other."
            ),
            confidence=0.8,
            evidence=[line_evidence(repo, rel, func.lineno, func.lineno)],
            recommendation=f"Keep one implementation and call it from both places ({where}).",
            rule_id="AST-DUPLICATE-FUNCTION",
            symbol=func.name,
        )

    @staticmethod
    def _naming(
        repo: Repository, rel: str, tree: ast.Module, scope: Scope | None
    ) -> Iterator[Finding]:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                checks = [("class", node.name)]
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                checks = [("function", node.name)] + [
                    ("argument", a.arg) for a in args if a.arg not in ("self", "cls")
                ]
            else:
                continue
            if not overlaps_scope(scope, rel, node.lineno, node.lineno):
                continue
            problems = [
                (kind, name, problem)
                for kind, name in checks
                if (problem := naming_problem(kind, name)) is not None
            ]
            if not problems:
                continue
            # One finding per definition: findings on one line would be merged by dedup anyway.
            names = ", ".join(f"{kind} `{name}`" for kind, name, _ in problems)
            reasons = "; ".join(f"`{name}`: {problem}" for _, name, problem in problems)
            yield make_finding(
                source=FindingSource.AST,
                file=rel,
                start_line=node.lineno,
                end_line=node.lineno,
                category=Category.STANDARDS,
                severity=Severity.LOW,
                title=f"Naming: {names}",
                description=f"Not PEP 8 names. {reasons}.",
                confidence=0.85,
                evidence=[line_evidence(repo, rel, node.lineno, node.lineno)],
                recommendation=f"Rename following PEP 8 ({reasons}).",
                rule_id="AST-NAMING",
                symbol=getattr(node, "name", None),
            )
