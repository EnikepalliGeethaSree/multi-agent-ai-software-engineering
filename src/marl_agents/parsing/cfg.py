"""Control-flow graph of one Python function, from its AST. Nothing is executed.

Each block holds what runs in order: plain statements, plus the header of a compound statement
(an `if` test expression, or the `ast.For` / `ast.With` node itself, whose body lives in other
blocks). Edges from a test carry that test, so a dataflow pass can narrow facts along them.

This is an approximation made for bug hints. Any statement in a `try` body may jump to its handlers,
but only from the end of its block, and `finally` runs once on the normal path.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef
Item = ast.stmt | ast.expr | ast.ExceptHandler
_NO_RETURN_CALLS = {"sys.exit", "exit", "quit", "os._exit", "os.abort"}


@dataclass
class Edge:
    target: int
    test: ast.expr | None = None
    outcome: bool | None = None  # which way `test` went to take this edge


@dataclass
class Block:
    id: int
    items: list[Item] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


@dataclass
class CFG:
    blocks: dict[int, Block]
    entry: int
    exit: int
    fall_off: set[int]  # blocks that reach the end of the function without a return

    def predecessors(self) -> dict[int, list[tuple[int, Edge]]]:
        preds: dict[int, list[tuple[int, Edge]]] = {b: [] for b in self.blocks}
        for block in self.blocks.values():
            for edge in block.edges:
                preds[edge.target].append((block.id, edge))
        return preds

    def reachable(self) -> set[int]:
        seen = {self.entry}
        stack = [self.entry]
        while stack:
            for edge in self.blocks[stack.pop()].edges:
                if edge.target not in seen:
                    seen.add(edge.target)
                    stack.append(edge.target)
        return seen

    def can_fall_off(self) -> bool:
        return bool(self.fall_off & self.reachable())


def _constant_truth(test: ast.expr) -> bool | None:
    return bool(test.value) if isinstance(test, ast.Constant) else None


def _never_returns(stmt: ast.stmt) -> bool:
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
        return False
    func = stmt.value.func
    if isinstance(func, ast.Name):
        return func.id in _NO_RETURN_CALLS
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}" in _NO_RETURN_CALLS
    return False


class _Builder:
    def __init__(self) -> None:
        self.blocks: dict[int, Block] = {}
        self.exit = self.new().id
        self.loops: list[tuple[int, int]] = []  # (continue target, break target)
        self.fall_off: set[int] = set()

    def new(self) -> Block:
        block = Block(len(self.blocks))
        self.blocks[block.id] = block
        return block

    def link(
        self,
        source: Block | None,
        target: Block,
        test: ast.expr | None = None,
        outcome: bool | None = None,
    ) -> None:
        if source is not None:
            source.edges.append(Edge(target.id, test, outcome))

    def body(self, stmts: list[ast.stmt], current: Block | None) -> Block | None:
        """Add statements after `current`; returns the open block, or None when all paths ended."""
        for stmt in stmts:
            if current is None:
                # Unreachable code still gets a block: analyses skip it via CFG.reachable().
                current = self.new()
            current = self.stmt(stmt, current)
        return current

    def stmt(self, stmt: ast.stmt, cur: Block) -> Block | None:
        if isinstance(stmt, ast.Return):
            cur.items.append(stmt)
            self.link(cur, self.blocks[self.exit])
            return None
        if isinstance(stmt, ast.Raise):
            cur.items.append(stmt)  # no edge: the path leaves the function by exception
            return None
        if isinstance(stmt, ast.Break):
            if self.loops:
                self.link(cur, self.blocks[self.loops[-1][1]])
            return None
        if isinstance(stmt, ast.Continue):
            if self.loops:
                self.link(cur, self.blocks[self.loops[-1][0]])
            return None
        if isinstance(stmt, ast.If):
            return self._if(stmt, cur)
        if isinstance(stmt, ast.Assert):
            return self._assert(stmt, cur)
        if isinstance(stmt, ast.Match):
            return self._match(stmt, cur)
        if isinstance(stmt, ast.While):
            return self._while(stmt, cur)
        if isinstance(stmt, ast.For | ast.AsyncFor):
            return self._for(stmt, cur)
        if isinstance(stmt, ast.With | ast.AsyncWith):
            cur.items.append(stmt)
            return self.body(stmt.body, cur)
        if isinstance(stmt, ast.Try | ast.TryStar):
            return self._try(stmt, cur)
        cur.items.append(stmt)
        return None if _never_returns(stmt) else cur

    def _if(self, stmt: ast.If, cur: Block) -> Block | None:
        cur.items.append(stmt.test)
        truth = _constant_truth(stmt.test)
        join = self.new()
        joined = False
        if truth is not False:
            then = self.new()
            self.link(cur, then, stmt.test, True)
            end = self.body(stmt.body, then)
            self.link(end, join)
            joined = joined or end is not None
        if truth is not True:
            other = self.new()
            self.link(cur, other, stmt.test, False)
            end = self.body(stmt.orelse, other)
            self.link(end, join)
            joined = joined or end is not None
        return join if joined else None

    def _assert(self, stmt: ast.Assert, cur: Block) -> Block:
        cur.items.append(stmt.test)
        after = self.new()
        self.link(cur, after, stmt.test, True)
        return after

    def _match(self, stmt: ast.Match, cur: Block) -> Block | None:
        cur.items.append(stmt.subject)
        join = self.new()
        joined = False
        wildcard = False
        for case in stmt.cases:
            start = self.new()
            self.link(cur, start)
            end = self.body(case.body, start)
            self.link(end, join)
            joined = joined or end is not None
            if isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None:
                wildcard = case.guard is None or wildcard
        if not wildcard:
            self.link(cur, join)
            joined = True
        return join if joined else None

    def _while(self, stmt: ast.While, cur: Block) -> Block | None:
        head = self.new()
        self.link(cur, head)
        head.items.append(stmt.test)
        truth = _constant_truth(stmt.test)
        after = self.new()
        self.loops.append((head.id, after.id))
        first = self.new()
        if truth is not False:
            self.link(head, first, stmt.test, True)
        self.link(self.body(stmt.body, first), head)
        self.loops.pop()
        if truth is not True:
            other = self.new()
            self.link(head, other, stmt.test, False)
            self.link(self.body(stmt.orelse, other), after)
        reached = any(e.target == after.id for b in self.blocks.values() for e in b.edges)
        return after if reached else None

    def _for(self, stmt: ast.For | ast.AsyncFor, cur: Block) -> Block:
        head = self.new()
        self.link(cur, head)
        head.items.append(stmt)
        after = self.new()
        self.loops.append((head.id, after.id))
        first = self.new()
        self.link(head, first)
        self.link(self.body(stmt.body, first), head)
        self.loops.pop()
        other = self.new()
        self.link(head, other)
        self.link(self.body(stmt.orelse, other), after)
        return after

    def _try(self, stmt: ast.Try | ast.TryStar, cur: Block) -> Block | None:
        start = self.new()
        self.link(cur, start)
        first_id = start.id
        end = self.body(stmt.body, start)
        body_ids = [b for b in self.blocks if b >= first_id]
        join = self.new()
        joined = False
        for handler in stmt.handlers:
            entry = self.new()
            if handler.name:
                entry.items.append(handler)  # binds the exception name
            for b in body_ids:
                self.link(self.blocks[b], entry)
            h_end = self.body(handler.body, entry)
            self.link(h_end, join)
            joined = joined or h_end is not None
        if end is not None:
            else_end = self.body(stmt.orelse, end)
            self.link(else_end, join)
            joined = joined or else_end is not None
        if not stmt.finalbody:
            return join if joined else None
        # A `finally` also runs on the paths that left, so its code is analysed even then.
        tail = self.body(stmt.finalbody, join)
        return tail if joined else None


def build_cfg(func: FunctionNode) -> CFG:
    builder = _Builder()
    entry = builder.new()
    end = builder.body(func.body, entry)
    if end is not None:
        builder.fall_off.add(end.id)
        builder.link(end, builder.blocks[builder.exit])
    return CFG(builder.blocks, entry.id, builder.exit, builder.fall_off)
