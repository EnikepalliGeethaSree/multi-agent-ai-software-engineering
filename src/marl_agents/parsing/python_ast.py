"""Extract code structure from Python source with `ast` only (the code is never executed)."""

from __future__ import annotations

import ast
import logging
import warnings
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SymbolKind(StrEnum):
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    CLASS = "class"


class ImportInfo(BaseModel):
    module: str | None = Field(description="'os.path' for `import os.path`; base for from-imports.")
    names: list[str] = Field(default_factory=list, description="Imported names (after `import`).")
    alias_map: dict[str, str] = Field(default_factory=dict, description="local name -> origin")
    line: int
    is_from: bool = False
    level: int = 0


class SymbolInfo(BaseModel):
    name: str
    qualname: str
    kind: SymbolKind
    start_line: int = Field(description="First line, including decorators.")
    end_line: int
    def_line: int = Field(description="Line of the `def`/`class` keyword.")
    decorators: list[str] = Field(default_factory=list)
    params: list[str] = Field(default_factory=list)
    docstring: str | None = None
    calls: list[str] = Field(default_factory=list, description="Called names, e.g. 'db.execute'.")
    bases: list[str] = Field(default_factory=list)
    parent: str | None = None
    return_count: int = 0

    @property
    def is_public(self) -> bool:
        return not self.name.startswith("_") or (
            self.name.startswith("__") and self.name.endswith("__")
        )

    @property
    def line_span(self) -> int:
        return self.end_line - self.start_line + 1


class ModuleInfo(BaseModel):
    path: str
    line_count: int
    docstring: str | None = None
    imports: list[ImportInfo] = Field(default_factory=list)
    symbols: list[SymbolInfo] = Field(default_factory=list)
    module_calls: list[str] = Field(default_factory=list)
    syntax_error: str | None = None
    syntax_error_line: int | None = None

    def symbol_at(self, line: int) -> SymbolInfo | None:
        """Innermost symbol containing `line`."""
        best: SymbolInfo | None = None
        for s in self.symbols:
            if s.start_line <= line <= s.end_line and (
                best is None or s.line_span < best.line_span
            ):
                best = s
        return best

    def top_level_symbols(self) -> list[SymbolInfo]:
        return [s for s in self.symbols if s.parent is None]

    def imported_names(self) -> set[str]:
        names: set[str] = set()
        for imp in self.imports:
            names.update(imp.alias_map)
        return names


def dotted_name(node: ast.AST) -> str | None:
    """'a.b.c' for Name/Attribute chains, the callee for calls, else None."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    return None


class _CallCollector(ast.NodeVisitor):
    """Collect calls in a body without descending into nested defs/classes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.returns = 0

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        if name:
            self.calls.append(name)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        self.returns += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.generic_visit(node)


def _collect(body: list[ast.stmt]) -> _CallCollector:
    collector = _CallCollector()
    for stmt in body:
        collector.visit(stmt)
    return collector


def _params(args: ast.arguments) -> list[str]:
    names = [a.arg for a in (*args.posonlyargs, *args.args)]
    if args.vararg:
        names.append("*" + args.vararg.arg)
    names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append("**" + args.kwarg.arg)
    return names


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.symbols: list[SymbolInfo] = []
        self.imports: list[ImportInfo] = []
        self._stack: list[tuple[str, bool]] = []  # (qualname, is_class)

    def _start_line(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> int:
        lines = [node.lineno] + [d.lineno for d in node.decorator_list]
        return min(lines)

    def _add_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent = self._stack[-1] if self._stack else None
        in_class = parent is not None and parent[1]
        if in_class:
            kind = SymbolKind.METHOD
        elif isinstance(node, ast.AsyncFunctionDef):
            kind = SymbolKind.ASYNC_FUNCTION
        else:
            kind = SymbolKind.FUNCTION
        qualname = f"{parent[0]}.{node.name}" if parent else node.name
        collected = _collect(node.body)
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                qualname=qualname,
                kind=kind,
                start_line=self._start_line(node),
                end_line=node.end_lineno or node.lineno,
                def_line=node.lineno,
                decorators=[dotted_name(d) or ast.unparse(d) for d in node.decorator_list],
                params=_params(node.args),
                docstring=ast.get_docstring(node),
                calls=collected.calls,
                parent=parent[0] if parent else None,
                return_count=collected.returns,
            )
        )
        self._stack.append((qualname, False))
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._add_def(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._add_def(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        parent = self._stack[-1] if self._stack else None
        qualname = f"{parent[0]}.{node.name}" if parent else node.name
        body_without_defs = [
            s
            for s in node.body
            if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        ]
        self.symbols.append(
            SymbolInfo(
                name=node.name,
                qualname=qualname,
                kind=SymbolKind.CLASS,
                start_line=self._start_line(node),
                end_line=node.end_lineno or node.lineno,
                def_line=node.lineno,
                decorators=[dotted_name(d) or ast.unparse(d) for d in node.decorator_list],
                docstring=ast.get_docstring(node),
                calls=_collect(body_without_defs).calls,
                bases=[dotted_name(b) or ast.unparse(b) for b in node.bases],
                parent=parent[0] if parent else None,
            )
        )
        self._stack.append((qualname, True))
        self.generic_visit(node)
        self._stack.pop()

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(
            ImportInfo(
                module=None,
                names=[a.name for a in node.names],
                alias_map={(a.asname or a.name.split(".")[0]): a.name for a in node.names},
                line=node.lineno,
            )
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        self.imports.append(
            ImportInfo(
                module=node.module,
                names=[a.name for a in node.names],
                alias_map={
                    (a.asname or a.name): (f"{base}.{a.name}" if base else a.name)
                    for a in node.names
                },
                line=node.lineno,
                is_from=True,
                level=node.level,
            )
        )


def parse_python(source: str, path: str) -> ModuleInfo:
    """Parse source into a `ModuleInfo`. Syntax errors are reported, not raised."""
    line_count = len(source.splitlines())
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        lineno = getattr(exc, "lineno", None)
        logger.info("Syntax error in %s: %s", path, exc)
        return ModuleInfo(
            path=path,
            line_count=line_count,
            syntax_error=str(exc),
            syntax_error_line=lineno if isinstance(lineno, int) else None,
        )

    visitor = _Visitor()
    visitor.visit(tree)
    module_body = [
        s
        for s in tree.body
        if not isinstance(s, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    ]
    return ModuleInfo(
        path=path,
        line_count=line_count,
        docstring=ast.get_docstring(tree),
        imports=visitor.imports,
        symbols=sorted(visitor.symbols, key=lambda s: (s.start_line, -s.end_line)),
        module_calls=_collect(module_body).calls,
    )


def parse_tree(source: str, path: str) -> ast.Module | None:
    """Raw AST for checks that need it; None on syntax error."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source, filename=path)
    except (SyntaxError, ValueError):
        return None
