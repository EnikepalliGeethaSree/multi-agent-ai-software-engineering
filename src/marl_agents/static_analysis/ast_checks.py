"""Custom AST checks the off-the-shelf tools miss, plus secret scanning and test-gap detection."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

from marl_agents.core.schemas import Category, Finding, FindingSource, Severity
from marl_agents.ingestion.models import FileKind, Repository
from marl_agents.parsing.python_ast import SymbolKind, dotted_name, parse_tree
from marl_agents.parsing.repo_index import RepoIndex
from marl_agents.static_analysis.base import (
    AnalyzerOutput,
    Scope,
    StaticAnalyzer,
    line_evidence,
    make_finding,
    overlaps_scope,
)

MAX_PARAMS = 6
MAX_FUNCTION_LINES = 80
MAX_NESTING = 4
_BROAD = {"Exception", "BaseException"}
_NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(dotted_name(t) in _BROAD for t in types)


def _handler_swallows(handler: ast.ExceptHandler) -> bool:
    """True if the handler neither re-raises nor calls anything (no logging, no cleanup)."""
    for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])):
        if isinstance(node, ast.Raise | ast.Call):
            return False
    return True


def _nesting_depth(node: ast.AST, depth: int = 0) -> int:
    best = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        inc = 1 if isinstance(child, _NESTING_NODES) else 0
        best = max(best, _nesting_depth(child, depth + inc))
    return best


def _enclosing_function(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    cur = parents.get(node)
    while cur is not None:
        if isinstance(cur, ast.FunctionDef | ast.AsyncFunctionDef):
            return cur
        cur = parents.get(cur)
    return None


def _closed_names(func: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name and name.endswith(".close"):
                names.add(name.rsplit(".", 1)[0])
    return names


class AstChecksAnalyzer(StaticAnalyzer):
    """Resource leaks, swallowed exceptions, long/complex signatures, deep nesting, docstrings."""

    name = "ast"

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        for rel in files:
            if not repo.has(rel) or repo.by_path[rel].language != "python":
                continue
            if repo.by_path[rel].kind is FileKind.TEST:
                continue
            tree = parse_tree(repo.read_text(rel), rel)
            if tree is None:
                continue
            out.findings.extend(self._check_file(repo, index, rel, tree, scope))
        return out

    def _check_file(
        self,
        repo: Repository,
        index: RepoIndex,
        rel: str,
        tree: ast.Module,
        scope: Scope | None = None,
    ) -> Iterator[Finding]:
        parents = _parents(tree)
        module = index.modules.get(rel)

        def sym_at(line: int) -> str | None:
            s = module.symbol_at(line) if module else None
            return s.qualname if s else None

        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            if scope is not None and (
                lineno is None
                or not overlaps_scope(
                    scope, rel, lineno, getattr(node, "end_lineno", None) or lineno
                )
            ):
                continue
            # --- open() outside a with-statement: file handle may leak ------------------------
            if isinstance(node, ast.Call) and dotted_name(node.func) in {"open", "io.open"}:
                parent = parents.get(node)
                if isinstance(parent, ast.withitem):
                    continue
                func = _enclosing_function(node, parents)
                target_name = None
                if isinstance(parent, ast.Assign) and len(parent.targets) == 1:
                    target_name = dotted_name(parent.targets[0])
                if target_name and func is not None and target_name in _closed_names(func):
                    continue
                if isinstance(parent, ast.Return):
                    continue  # the caller owns the handle
                yield make_finding(
                    source=FindingSource.AST,
                    file=rel,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    category=Category.BUG,
                    severity=Severity.MEDIUM,
                    title="File opened without a context manager",
                    description=(
                        "`open()` is called outside a `with` block and the handle is not closed "
                        "in this function, so it can leak (especially if an exception occurs)."
                    ),
                    confidence=0.6,
                    evidence=[line_evidence(repo, rel, node.lineno, node.lineno)],
                    recommendation="Use `with open(...) as fh:` so the file is always closed.",
                    rule_id="AST-RESOURCE-LEAK",
                    cwe="CWE-772",
                    symbol=sym_at(node.lineno),
                )

            # --- broad except that silently swallows the error -------------------------------
            elif isinstance(node, ast.ExceptHandler):
                if _is_broad_handler(node) and _handler_swallows(node):
                    end = node.body[-1].end_lineno or node.lineno
                    yield make_finding(
                        source=FindingSource.AST,
                        file=rel,
                        start_line=node.lineno,
                        end_line=end,
                        category=Category.ERROR_HANDLING,
                        severity=Severity.MEDIUM,
                        title="Broad exception silently swallowed",
                        description=(
                            "A broad `except` catches every error and neither logs nor re-raises "
                            "it, hiding bugs and making failures invisible."
                        ),
                        confidence=0.8,
                        evidence=[line_evidence(repo, rel, node.lineno, end)],
                        recommendation=(
                            "Catch the specific exceptions you expect; otherwise log with "
                            "`logger.exception(...)` and re-raise."
                        ),
                        test_recommendation=(
                            "Force the guarded call to fail and assert the error is surfaced."
                        ),
                        rule_id="AST-SWALLOWED-EXCEPTION",
                        cwe="CWE-390",
                        symbol=sym_at(node.lineno),
                    )

            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield from self._check_function(repo, rel, node, sym_at(node.lineno))

    def _check_function(
        self,
        repo: Repository,
        rel: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        qualname: str | None,
    ) -> Iterator[Finding]:
        args = node.args
        params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
        params = [p for p in params if p not in ("self", "cls")]
        name = qualname or node.name
        def_evidence = line_evidence(repo, rel, node.lineno, node.lineno)
        if len(params) > MAX_PARAMS:
            yield make_finding(
                source=FindingSource.AST,
                file=rel,
                start_line=node.lineno,
                end_line=node.lineno,
                category=Category.MAINTAINABILITY,
                severity=Severity.LOW,
                title=f"Too many parameters in {name} ({len(params)})",
                description=(
                    f"`{name}` takes {len(params)} parameters (limit {MAX_PARAMS}); long "
                    "signatures are error-prone to call and hard to test."
                ),
                confidence=0.75,
                evidence=[def_evidence],
                recommendation="Group related parameters into a dataclass or config object.",
                rule_id="AST-TOO-MANY-PARAMS",
                symbol=name,
            )
        span = (node.end_lineno or node.lineno) - node.lineno + 1
        if span > MAX_FUNCTION_LINES:
            yield make_finding(
                source=FindingSource.AST,
                file=rel,
                start_line=node.lineno,
                end_line=node.lineno,
                category=Category.MAINTAINABILITY,
                severity=Severity.LOW,
                title=f"Long function {name} ({span} lines)",
                description=f"`{name}` spans {span} lines (limit {MAX_FUNCTION_LINES}).",
                confidence=0.7,
                evidence=[def_evidence],
                recommendation="Extract cohesive blocks into well-named helper functions.",
                rule_id="AST-LONG-FUNCTION",
                symbol=name,
            )
        depth = _nesting_depth(node)
        if depth > MAX_NESTING:
            yield make_finding(
                source=FindingSource.AST,
                file=rel,
                start_line=node.lineno,
                end_line=node.lineno,
                category=Category.MAINTAINABILITY,
                severity=Severity.LOW,
                title=f"Deeply nested control flow in {name} (depth {depth})",
                description=(
                    f"`{name}` nests control structures {depth} levels deep (limit {MAX_NESTING})."
                ),
                confidence=0.7,
                evidence=[def_evidence],
                recommendation="Use guard clauses / early returns and extract nested blocks.",
                rule_id="AST-DEEP-NESTING",
                symbol=name,
            )
        is_public = not node.name.startswith("_")
        if is_public and span > 10 and ast.get_docstring(node) is None:
            yield make_finding(
                source=FindingSource.AST,
                file=rel,
                start_line=node.lineno,
                end_line=node.lineno,
                category=Category.DOCUMENTATION,
                severity=Severity.INFO,
                title=f"Missing docstring on public function {name}",
                description=f"`{name}` is public and {span} lines long but has no docstring.",
                confidence=0.9,
                evidence=[def_evidence],
                recommendation=(
                    "Add a docstring describing purpose, parameters, return value and errors."
                ),
                rule_id="AST-MISSING-DOCSTRING",
                symbol=name,
            )


# ---------------------------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "hard-coded credential",
        re.compile(
            r"""(?ix)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b
            \s*[:=]\s*['"]([^'"\s]{8,})['"]"""
        ),
    ),
]
_PLACEHOLDER = re.compile(r"(?i)(xxx|changeme|example|dummy|placeholder|your[_-]|<|\$\{|%\()")


def redact(line: str) -> str:
    """Mask secret-looking values so reports never re-publish the secret."""
    for _, pattern in _SECRET_PATTERNS:
        line = pattern.sub(lambda m: m.group(0)[:4] + "****", line)
    return line.strip()


class SecretsAnalyzer(StaticAnalyzer):
    """Regex secret scanning over code *and* config/doc files (YAML, JSON, TOML, .ini...)."""

    name = "secrets"

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        for rel in files:
            if not repo.has(rel) or repo.by_path[rel].kind is FileKind.TEST:
                continue
            for lineno, line in enumerate(repo.lines(rel), start=1):
                for label, pattern in _SECRET_PATTERNS:
                    match = pattern.search(line)
                    if not match or _PLACEHOLDER.search(match.group(0)):
                        continue
                    out.findings.append(
                        make_finding(
                            source=FindingSource.AST,
                            file=rel,
                            start_line=lineno,
                            end_line=lineno,
                            category=Category.SECURITY,
                            severity=Severity.CRITICAL
                            if label != "hard-coded credential"
                            else Severity.HIGH,
                            title=f"Possible {label} committed to the repository",
                            description=(
                                f"Line {lineno} appears to contain a secret ({label}). "
                                "Secrets in source control are exposed to everyone with "
                                "repository access and persist "
                                "in git history."
                            ),
                            confidence=0.7 if label != "hard-coded credential" else 0.5,
                            evidence=[redact(line)],
                            recommendation=(
                                "Remove the secret, rotate it immediately, and load it from an "
                                "environment variable or secrets manager."
                            ),
                            rule_id="SECRET-" + label.upper().replace(" ", "-"),
                            cwe="CWE-798",
                        )
                    )
                    break
        return out


# ---------------------------------------------------------------------------------------------
# Test gaps
# ---------------------------------------------------------------------------------------------


class TestGapAnalyzer(StaticAnalyzer):
    """Public functions never referenced by any test file (identifier-level, simple)."""

    name = "test_gap"
    __test__ = False  # not a pytest test class

    def __init__(self, min_function_lines: int = 5) -> None:
        self.min_function_lines = min_function_lines

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        has_tests = index.has_tests()
        for rel in files:
            if not repo.has(rel) or repo.by_path[rel].kind is not FileKind.CODE:
                continue
            module = index.modules.get(rel)
            if module is None or module.syntax_error:
                continue
            candidates = [
                s
                for s in module.symbols
                if s.kind in (SymbolKind.FUNCTION, SymbolKind.ASYNC_FUNCTION, SymbolKind.METHOD)
                and not s.name.startswith("_")
                and s.line_span >= self.min_function_lines
            ]
            if not candidates:
                continue
            if not has_tests:
                first = candidates[0]
                out.findings.append(
                    make_finding(
                        source=FindingSource.AST,
                        file=rel,
                        start_line=first.def_line,
                        end_line=first.def_line,
                        category=Category.TESTING,
                        severity=Severity.LOW,
                        title="Module has no tests",
                        description=(
                            f"The repository has no test files, so the {len(candidates)} public "
                            f"function(s) in {rel} are untested: "
                            + ", ".join(f"`{s.qualname}`" for s in candidates[:8])
                        ),
                        confidence=0.8,
                        evidence=[line_evidence(repo, rel, first.def_line, first.def_line)],
                        recommendation="Add a pytest test module covering the public functions.",
                        test_recommendation=f"Create tests/test_{rel.rsplit('/', 1)[-1]} with "
                        "happy-path and edge-case tests for each public function.",
                        rule_id="TEST-NO-TESTS",
                    )
                )
                continue
            for sym in candidates:
                if index.tests_referencing(sym.name):
                    continue
                out.findings.append(
                    make_finding(
                        source=FindingSource.AST,
                        file=rel,
                        start_line=sym.def_line,
                        end_line=sym.def_line,
                        category=Category.TESTING,
                        severity=Severity.INFO,
                        title=f"No test references {sym.qualname}",
                        description=(
                            f"No test file mentions `{sym.name}`; it is likely untested or only "
                            "covered indirectly."
                        ),
                        confidence=0.5,
                        evidence=[line_evidence(repo, rel, sym.def_line, sym.def_line)],
                        recommendation=f"Add unit tests for `{sym.qualname}`.",
                        test_recommendation=(
                            f"Test `{sym.name}` with typical input, boundary values and "
                            "invalid input."
                        ),
                        rule_id="TEST-UNREFERENCED",
                        symbol=sym.qualname,
                    )
                )
        return out
