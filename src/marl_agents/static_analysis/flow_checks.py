"""Control-flow bug checks: the hints static tools miss and the LLM should look at.

Each check is a may-analysis over one function's CFG, or a syntactic pattern. They are deliberately
narrow. A check here must point at a real line and say which path goes wrong; deciding whether that
path happens is left to the LLM and the reader. Nothing is executed or imported.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from marl_agents.core.schemas import Finding, FindingSource
from marl_agents.ingestion.models import Repository
from marl_agents.parsing.cfg import CFG, FunctionNode, build_cfg
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
from marl_agents.static_analysis.rules import FLOW_RULES

_NONE_CALLS = {"re.match", "re.search", "re.fullmatch", "shutil.which", "os.environ.get"}
_MATCH_METHODS = {"match", "search", "fullmatch"}
# `.get` on these is a network or queue call, not a dict lookup.
_NOT_A_MAPPING = re.compile(r"(requests?|session|client|http|api|queue|q|browser|driver)$", re.I)
_PATTERN_NAME = re.compile(r"(_re|regex|pattern|rx)$", re.I)
_CATCHES_DEREF = {"AttributeError", "TypeError", "Exception", "BaseException"}
_MUTATORS = {"remove", "pop", "append", "insert", "clear", "extend", "discard", "add"}
_STUB_DECORATORS = {"abstractmethod", "overload"}
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


@dataclass(frozen=True)
class _MaybeNone:
    """Why a local may be None; the origin decides which rule reports it."""

    rule: str
    origin: str


Facts = dict[str, _MaybeNone]


def _none_source(value: ast.expr, maybe_none_funcs: set[str]) -> _MaybeNone | None:
    if isinstance(value, ast.Constant) and value.value is None:
        return _MaybeNone("BUG-NONE-DEREF", "assigned None")
    if not isinstance(value, ast.Call):
        return None
    name = dotted_name(value.func) or ""
    if name in _NONE_CALLS:
        return _MaybeNone("BUG-NONE-DEREF", f"{name}() can return None")
    if name == "getattr" and len(value.args) == 3 and _is_none(value.args[2]):
        return _MaybeNone("BUG-NONE-DEREF", "getattr(..., None) can return None")
    if isinstance(value.func, ast.Attribute):
        receiver = dotted_name(value.func.value) or ""
        attr = value.func.attr
        is_lookup = attr == "get" and len(value.args) == 1 and not value.keywords
        if is_lookup and receiver and not _NOT_A_MAPPING.search(receiver):
            return _MaybeNone("BUG-NONE-DEREF", f"{receiver}.get() can return None")
        if attr in _MATCH_METHODS and _PATTERN_NAME.search(receiver):
            return _MaybeNone("BUG-NONE-DEREF", f"{receiver}.{attr}() can return None")
    last = name.split(".")[-1]
    if last and last in maybe_none_funcs:
        return _MaybeNone("BUG-NONE-DEREF", f"{last}() can return None")
    return None


def _assigned_names(target: ast.expr) -> Iterator[str]:
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, ast.Tuple | ast.List):
        for item in target.elts:
            yield from _assigned_names(item)
    elif isinstance(target, ast.Starred):
        yield from _assigned_names(target.value)


def _walrus(expr: ast.AST, facts: Facts, sources: set[str]) -> None:
    for node in ast.walk(expr):
        if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            source = _none_source(node.value, sources)
            if source is not None:
                facts[node.target.id] = source
            else:
                facts.pop(node.target.id, None)


def _forget(target: ast.expr, facts: Facts) -> None:
    for name in _assigned_names(target):
        facts.pop(name, None)


def _transfer(item: ast.AST, facts: Facts, sources: set[str]) -> None:
    """Update `facts` for one block item."""
    if isinstance(item, ast.Assign):
        _walrus(item.value, facts, sources)
        source = _none_source(item.value, sources)
        for target in item.targets:
            _forget(target, facts)
            if source is not None and isinstance(target, ast.Name):
                facts[target.id] = source
    elif isinstance(item, ast.AnnAssign):
        if item.value is not None and isinstance(item.target, ast.Name):
            source = _none_source(item.value, sources)
            facts.pop(item.target.id, None)
            if source is not None:
                facts[item.target.id] = source
    elif isinstance(item, ast.AugAssign | ast.For | ast.AsyncFor):
        _forget(item.target, facts)
    elif isinstance(item, ast.With | ast.AsyncWith):
        for w in item.items:
            if w.optional_vars is not None:
                _forget(w.optional_vars, facts)
    elif isinstance(item, ast.ExceptHandler):
        if item.name:
            facts.pop(item.name, None)
    elif isinstance(item, ast.Delete):
        for target in item.targets:
            _forget(target, facts)
    elif isinstance(item, ast.expr):
        _walrus(item, facts, sources)
    elif isinstance(item, ast.Expr | ast.Return) and item.value is not None:
        _walrus(item.value, facts, sources)


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _narrow_compare(test: ast.Compare, outcome: bool, out: Facts) -> None:
    left, right, op = test.left, test.comparators[0], test.ops[0]
    if _is_none(left):
        left, right = right, left
    if not isinstance(left, ast.Name):
        return
    if _is_none(right):
        if isinstance(op, ast.IsNot | ast.NotEq) == outcome:
            out.pop(left.id, None)
    elif isinstance(op, ast.Eq | ast.Is | ast.In) and outcome:
        out.pop(left.id, None)  # equal to something that is not None


def _narrow(test: ast.expr, outcome: bool, facts: Facts) -> Facts:
    """`facts` once `test` is known to be `outcome`."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _narrow(test.operand, not outcome, facts)
    if isinstance(test, ast.NamedExpr):
        return _narrow(test.target, outcome, facts)
    if isinstance(test, ast.BoolOp):
        # `a and b` being true means both are; being false says nothing about either. `or` mirrors.
        if isinstance(test.op, ast.And) == outcome:
            for value in test.values:
                facts = _narrow(value, outcome, facts)
        return facts
    out = dict(facts)
    if isinstance(test, ast.Name):
        if outcome:
            out.pop(test.id, None)
    elif isinstance(test, ast.Compare) and len(test.ops) == 1:
        _narrow_compare(test, outcome, out)
    elif isinstance(test, ast.Call) and outcome:
        name = dotted_name(test.func)
        if name in {"isinstance", "callable", "hasattr"} and test.args:
            first = test.args[0]
            if isinstance(first, ast.Name):
                out.pop(first.id, None)
    return out


def _join(a: Facts | None, b: Facts) -> Facts:
    if a is None:
        return dict(b)
    return {**a, **{k: v for k, v in b.items() if k not in a}}


def solve_none_facts(cfg: CFG, entry: Facts, sources: set[str]) -> dict[int, Facts]:
    """Facts on entry to each reachable block. Facts only grow, so this terminates."""
    reachable = cfg.reachable()
    preds = cfg.predecessors()
    state: dict[int, Facts | None] = {b: None for b in reachable}
    state[cfg.entry] = dict(entry)
    work = sorted(reachable)
    while work:
        block_id = work.pop(0)
        if block_id != cfg.entry:
            merged: Facts | None = None
            for pred, edge in preds[block_id]:
                incoming = state.get(pred)
                if incoming is None:
                    continue
                out = dict(incoming)
                for item in cfg.blocks[pred].items:
                    _transfer(item, out, sources)
                if edge.test is not None and edge.outcome is not None:
                    out = _narrow(edge.test, edge.outcome, out)
                merged = _join(merged, out)
            if merged is None or merged == state[block_id]:
                continue
            state[block_id] = merged
        for edge in cfg.blocks[block_id].edges:
            if edge.target in reachable and edge.target not in work:
                work.append(edge.target)
    return {b: f for b, f in state.items() if f is not None}


@dataclass
class _Use:
    name: str
    node: ast.expr
    how: str


def _comprehension_uses(
    expr: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp, facts: Facts
) -> Iterator[_Use]:
    current = facts
    for gen in expr.generators:
        yield from _uses(gen.iter, current)
        if isinstance(gen.iter, ast.Name) and gen.iter.id in current:
            yield _Use(gen.iter.id, gen.iter, "iterated over")
        for cond in gen.ifs:
            yield from _uses(cond, current)
            current = _narrow(cond, True, current)
    parts = [expr.key, expr.value] if isinstance(expr, ast.DictComp) else [expr.elt]
    for part in parts:
        yield from _uses(part, current)


def _uses(expr: ast.AST, facts: Facts) -> Iterator[_Use]:
    """Places that crash when a name is None, respecting short-circuit evaluation."""
    if isinstance(expr, ast.BoolOp):
        current = facts
        for value in expr.values:
            yield from _uses(value, current)
            current = _narrow(value, isinstance(expr.op, ast.And), current)
        return
    if isinstance(expr, ast.IfExp):
        yield from _uses(expr.test, facts)
        yield from _uses(expr.body, _narrow(expr.test, True, facts))
        yield from _uses(expr.orelse, _narrow(expr.test, False, facts))
        return
    if isinstance(expr, _SCOPES):
        return
    if isinstance(expr, ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp):
        yield from _comprehension_uses(expr, facts)
        return
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        if expr.value.id in facts:
            yield _Use(expr.value.id, expr, f"attribute .{expr.attr} read")
    elif isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
        if expr.value.id in facts:
            yield _Use(expr.value.id, expr, "subscripted")
    elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in facts:
        yield _Use(expr.func.id, expr, "called")
    for child in ast.iter_child_nodes(expr):
        yield from _uses(child, facts)


def _item_exprs(item: ast.AST) -> list[ast.AST]:
    """The expressions an item evaluates; compound statements keep theirs in other blocks."""
    if isinstance(item, ast.For | ast.AsyncFor):
        return [item.iter]
    if isinstance(item, ast.With | ast.AsyncWith):
        return [w.context_expr for w in item.items]
    if isinstance(item, ast.ExceptHandler):
        return []
    return [item]


def _parents(root: ast.AST) -> dict[ast.AST, ast.AST]:
    return {c: p for p in ast.walk(root) for c in ast.iter_child_nodes(p)}


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"Exception"}
    if isinstance(handler.type, ast.Tuple):
        return {dotted_name(e) or "" for e in handler.type.elts}
    return {dotted_name(handler.type) or ""}


def _in_handler_try(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Inside a `try` whose handlers would catch the crash, so it is presumably intended."""
    child, cur = node, parents.get(node)
    while cur is not None:
        if (
            isinstance(cur, ast.Try)
            and child in cur.body
            and any(_handler_names(h) & _CATCHES_DEREF for h in cur.handlers)
        ):
            return True
        child, cur = cur, parents.get(cur)
    return False


def _walk_own(func: FunctionNode) -> Iterator[ast.AST]:
    """Every node of a function, without entering nested functions or classes."""
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _is_generator(func: FunctionNode) -> bool:
    return any(isinstance(n, ast.Yield | ast.YieldFrom) for n in _walk_own(func))


def _returns(func: FunctionNode) -> list[ast.Return]:
    return [n for n in _walk_own(func) if isinstance(n, ast.Return)]


def _functions(tree: ast.AST) -> Iterator[FunctionNode]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def may_return_none(func: FunctionNode) -> bool:
    """A function that returns a value on some paths and None on others (an implicit Optional)."""
    returns = _returns(func)
    with_value = [r for r in returns if r.value is not None and not _is_none(r.value)]
    without = [r for r in returns if r.value is None or _is_none(r.value)]
    if not with_value or _is_generator(func):
        return False
    return bool(without) or build_cfg(func).can_fall_off()


def _is_stub(func: FunctionNode) -> bool:
    decorators = {(dotted_name(d) or "").split(".")[-1] for d in func.decorator_list}
    if decorators & _STUB_DECORATORS:
        return True
    body = [
        s for s in func.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
    ]
    return not body or all(isinstance(s, ast.Pass) for s in body)


def _none_default_params(func: FunctionNode) -> Facts:
    args = func.args
    positional = [*args.posonlyargs, *args.args]
    with_default = positional[len(positional) - len(args.defaults) :]
    pairs: list[tuple[ast.arg, ast.expr | None]] = [
        *zip(with_default, args.defaults, strict=True),
        *zip(args.kwonlyargs, args.kw_defaults, strict=True),
    ]
    return {
        a.arg: _MaybeNone("BUG-NONE-DEFAULT", "the parameter defaults to None")
        for a, d in pairs
        if d is not None and _is_none(d)
    }


def _mentions(expr: ast.AST, name: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(expr))


def _guards(func: FunctionNode) -> list[tuple[int, ast.expr]]:
    """(line, test) of every condition in the function."""
    out: list[tuple[int, ast.expr]] = []
    for node in ast.walk(func):
        if isinstance(node, ast.If | ast.While | ast.IfExp | ast.Assert):
            out.append((node.test.lineno, node.test))
        elif isinstance(node, ast.comprehension):
            out.extend((c.lineno, c) for c in node.ifs)
    return out


def _len_arg(node: ast.expr) -> str | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
    ):
        return node.args[0].id
    return None


def _numeric_params(func: FunctionNode) -> set[str]:
    names: set[str] = set()
    for arg in [*func.args.posonlyargs, *func.args.args, *func.args.kwonlyargs]:
        if isinstance(arg.annotation, ast.Name) and arg.annotation.id in {"int", "float"}:
            names.add(arg.arg)
    return names


def _range_over_len(call: ast.expr) -> tuple[str, int] | None:
    """`range(len(x) + k)` or `range(a, len(x) + k)` -> (x, k)."""
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
        return None
    if call.func.id != "range" or not 1 <= len(call.args) <= 2:
        return None
    bound = call.args[-1]
    name = _len_arg(bound)
    if name is not None:
        return name, 0
    if (
        isinstance(bound, ast.BinOp)
        and isinstance(bound.op, ast.Add)
        and isinstance(bound.right, ast.Constant)
        and isinstance(bound.right.value, int)
    ):
        name = _len_arg(bound.left)
        if name is not None:
            return name, bound.right.value
    return None


def _indexed_with(body: list[ast.stmt], seq: str, var: str) -> Iterator[tuple[ast.Subscript, int]]:
    """`seq[var]` and `seq[var + k]` in a loop body -> (node, k)."""
    for stmt in body:
        for node in ast.walk(stmt):
            if not (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == seq
            ):
                continue
            index = node.slice
            if isinstance(index, ast.Name) and index.id == var:
                yield node, 0
            elif (
                isinstance(index, ast.BinOp)
                and isinstance(index.op, ast.Add)
                and isinstance(index.left, ast.Name)
                and index.left.id == var
                and isinstance(index.right, ast.Constant)
                and isinstance(index.right.value, int)
            ):
                yield node, index.right.value


@dataclass
class _Hit:
    rule: str
    line: int
    end_line: int
    title: str
    description: str


@dataclass
class _FunctionChecks:
    func: FunctionNode
    maybe_none_funcs: set[str]
    hits: list[_Hit] = field(default_factory=list)

    def run(self) -> list[_Hit]:
        cfg = build_cfg(self.func)
        self.none_uses(cfg)
        self.missing_return(cfg)
        self.division()
        self.loops()
        return self.hits

    def none_uses(self, cfg: CFG) -> None:
        entry = _none_default_params(self.func)
        states = solve_none_facts(cfg, entry, self.maybe_none_funcs)
        parents = _parents(self.func)
        seen: set[str] = set()  # one report per name: after the first crash the rest cannot run
        for block_id in sorted(states):
            facts = dict(states[block_id])
            for item in cfg.blocks[block_id].items:
                for expr in _item_exprs(item):
                    for use in _uses(expr, facts):
                        if use.name in seen or _in_handler_try(use.node, parents):
                            continue
                        seen.add(use.name)
                        why = facts[use.name]
                        self.hits.append(
                            _Hit(
                                why.rule,
                                use.node.lineno,
                                use.node.end_lineno or use.node.lineno,
                                f"`{use.name}` may be None here ({use.how})",
                                f"{why.origin}, and a path reaches this line without a None "
                                f"check, so `{use.name}` being None raises an exception.",
                            )
                        )
                _transfer(item, facts, self.maybe_none_funcs)

    def missing_return(self, cfg: CFG) -> None:
        func = self.func
        if _is_generator(func) or _is_stub(func) or func.name == "__init__":
            return
        valued = [r for r in _returns(func) if r.value is not None and not _is_none(r.value)]
        if not valued or not cfg.can_fall_off():
            return
        last = func.body[-1]
        self.hits.append(
            _Hit(
                "BUG-MISSING-RETURN",
                func.lineno,
                func.lineno,
                f"`{func.name}` can end without returning a value",
                f"It returns a value on line {valued[0].lineno}, but a path reaches the end of "
                f"the function (after line {last.end_lineno or last.lineno}) and returns None.",
            )
        )

    def division(self) -> None:
        numeric = _numeric_params(self.func)
        guards = _guards(self.func)
        loops = [n for n in ast.walk(self.func) if isinstance(n, ast.For | ast.AsyncFor)]
        for node in ast.walk(self.func):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div | ast.FloorDiv)):
                continue
            right = node.right
            name = _len_arg(right)
            what = f"len({name})" if name else None
            if isinstance(right, ast.Name) and right.id in numeric:
                name, what = right.id, right.id
            if name is None:
                continue
            guarded = any(line <= node.lineno and _mentions(t, name) for line, t in guards)
            in_loop = any(
                _mentions(loop.iter, name)
                and any(n is node for s in loop.body for n in ast.walk(s))
                for loop in loops
            )
            if guarded or in_loop:
                continue
            self.hits.append(
                _Hit(
                    "BUG-DIV-BY-LEN",
                    node.lineno,
                    node.end_lineno or node.lineno,
                    f"Division by `{what}` with no zero check",
                    f"Nothing before this line checks `{name}`, so an empty or zero input raises "
                    "ZeroDivisionError.",
                )
            )

    def loops(self) -> None:
        for node in ast.walk(self.func):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and _len_arg(node.slice) == node.value.id
            ):
                self._off_by_one(node, f"`{node.value.id}[len({node.value.id})]`")
            if not isinstance(node, ast.For | ast.AsyncFor):
                continue
            self._mutation(node)
            over = _range_over_len(node.iter)
            if over is None or not isinstance(node.target, ast.Name):
                continue
            seq, extra = over
            guards = [n for s in node.body for n in ast.walk(s) if isinstance(n, ast.If)]
            conditional = any(_mentions(g.test, node.target.id) for g in guards)
            for sub, offset in _indexed_with(node.body, seq, node.target.id):
                if extra + offset > 0 and not conditional:
                    self._off_by_one(sub, f"`{seq}[...]` in a loop over `range(len({seq})...)`")
                    break

    def _off_by_one(self, node: ast.expr, what: str) -> None:
        self.hits.append(
            _Hit(
                "BUG-OFF-BY-ONE",
                node.lineno,
                node.end_lineno or node.lineno,
                f"Index one past the end: {what}",
                "The last index reached is the length of the sequence, which raises IndexError.",
            )
        )

    def _mutation(self, loop: ast.For | ast.AsyncFor) -> None:
        if not isinstance(loop.iter, ast.Name):
            return
        seq = loop.iter.id
        nodes = [n for s in loop.body for n in ast.walk(s)]
        if any(isinstance(n, ast.Break | ast.Return) for n in nodes):
            return  # the loop stops after changing it
        for node in nodes:
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == seq
                and node.func.attr in _MUTATORS
            ):
                self.hits.append(
                    _Hit(
                        "BUG-MUTATE-WHILE-ITERATING",
                        node.lineno,
                        node.end_lineno or node.lineno,
                        f"`{seq}` is changed while the loop iterates over it",
                        "Changing a collection during iteration skips items, or raises "
                        "RuntimeError for dicts and sets.",
                    )
                )
                return


def _maybe_none_names(tree: ast.AST, index: RepoIndex, path: str) -> set[str]:
    """Functions callable from this file that can return None: same file or resolved imports."""
    names = {f.name for f in _functions(tree) if may_return_none(f)}
    for imported in index.imported_files(path):
        module = index.modules.get(imported)
        if module is None or module.syntax_error:
            continue
        other = parse_tree(index.repo.read_text(imported), imported)
        if other is not None:
            names |= {f.name for f in _functions(other) if may_return_none(f)}
    return names


class FlowAnalyzer(StaticAnalyzer):
    """None dereferences, missing returns, unguarded division, off-by-one, mutation in a loop."""

    name = "flow"

    def analyze(
        self, repo: Repository, index: RepoIndex, files: list[str], scope: Scope | None = None
    ) -> AnalyzerOutput:
        out = AnalyzerOutput()
        for path in files:
            module = index.modules.get(path)
            if module is None or module.syntax_error:
                continue
            tree = parse_tree(repo.read_text(path), path)
            if tree is None:
                continue
            maybe_none = _maybe_none_names(tree, index, path)
            for func in _functions(tree):
                if scope is not None and not overlaps_scope(
                    scope, path, func.lineno, func.end_lineno or func.lineno
                ):
                    continue
                for hit in _FunctionChecks(func, maybe_none).run():
                    if overlaps_scope(scope, path, hit.line, hit.end_line):
                        out.findings.append(self._finding(repo, index, path, hit))
        return out

    @staticmethod
    def _finding(repo: Repository, index: RepoIndex, path: str, hit: _Hit) -> Finding:
        spec = FLOW_RULES[hit.rule]
        symbol = index.modules[path].symbol_at(hit.line)
        return make_finding(
            source=FindingSource.AST,
            file=path,
            start_line=hit.line,
            end_line=hit.end_line,
            category=spec.category,
            severity=spec.severity,
            title=hit.title,
            description=hit.description,
            confidence=spec.confidence,
            evidence=[line_evidence(repo, path, hit.line, hit.end_line)],
            recommendation=spec.recommendation,
            test_recommendation=spec.test_recommendation,
            rule_id=hit.rule,
            symbol=symbol.qualname
            if symbol is not None and symbol.kind is not SymbolKind.CLASS
            else None,
        )
