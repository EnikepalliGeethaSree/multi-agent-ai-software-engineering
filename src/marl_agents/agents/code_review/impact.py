"""Change impact analysis: what ELSE does this change break?

For every function the change added, modified or removed, find its call sites across the repository
(AST call graph) and check them:

1. removed function still called                -> deterministic, high (IMPACT-REMOVED)
2. call no longer matches the new signature      -> deterministic, high (IMPACT-SIGNATURE),
   checked like Python's own argument binding
3. behaviour change callers may not handle       -> LLM, given old + new version + untouched callers
   (IMPACT-BEHAVIOR); validated like every other LLM finding, scoped to the caller lines

This is "impact analysis for code review" (functions that must co-change but did not) from the
code-review automation literature, done without training anything.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field

from marl_agents.agents.code_review.llm_schema import LLMReviewEnvelope, parse_items
from marl_agents.agents.code_review.prompts import load_prompt
from marl_agents.core.schemas import Category, ChangedSymbol, Finding, FindingSource, Severity
from marl_agents.findings import FindingValidator, validate_all
from marl_agents.ingestion.changes import ChangeSet
from marl_agents.llm.base import LLMError, LLMProvider, Message, Usage
from marl_agents.parsing.python_ast import (
    SymbolInfo,
    SymbolKind,
    dotted_name,
    parse_python,
    parse_tree,
)
from marl_agents.parsing.repo_index import RepoIndex

logger = logging.getLogger(__name__)

MAX_CALLERS_IN_PROMPT = 6
CALLER_CONTEXT_LINES = 40


# ---------------------------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    positional: tuple[tuple[str, bool], ...]  # (name, has_default), incl. positional-only
    vararg: bool
    kwonly: tuple[tuple[str, bool], ...]
    varkw: bool
    bound: bool  # first positional param is self/cls (method or classmethod)

    def text(self) -> str:
        parts = [n + ("=…" if d else "") for n, d in self.positional]
        if self.vararg:
            parts.append("*args")
        elif self.kwonly:
            parts.append("*")
        parts += [n + ("=…" if d else "") for n, d in self.kwonly]
        if self.varkw:
            parts.append("**kwargs")
        return "(" + ", ".join(parts) + ")"


def signature_of(node: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> Signature:
    a = node.args
    pos = [*a.posonlyargs, *a.args]
    n_def = len(a.defaults)
    positional = tuple((p.arg, i >= len(pos) - n_def) for i, p in enumerate(pos))
    kwonly = tuple((k.arg, d is not None) for k, d in zip(a.kwonlyargs, a.kw_defaults, strict=True))
    decorators = {dotted_name(d) for d in node.decorator_list}
    bound = is_method and "staticmethod" not in decorators
    return Signature(positional, a.vararg is not None, kwonly, a.kwarg is not None, bound)


def call_mismatch(sig: Signature, call: ast.Call, via_attribute: bool) -> str | None:
    """Why `call` cannot bind to `sig`, or None if it can (or cannot be decided statically)."""
    if any(isinstance(arg, ast.Starred) for arg in call.args) or any(
        k.arg is None for k in call.keywords
    ):
        return None  # *args / **kwargs at the call site: not decidable
    params = list(sig.positional)
    if sig.bound and via_attribute and params:
        params = params[1:]  # obj.method(...) supplies self
    n_pos = len(call.args)
    if n_pos > len(params) and not sig.vararg:
        return f"passes {n_pos} positional argument(s) but at most {len(params)} are accepted"
    names = {k.arg for k in call.keywords if k.arg}
    accepted = {n for n, _ in params} | {n for n, _ in sig.kwonly}
    unknown = sorted(names - accepted)
    if unknown and not sig.varkw:
        return f"passes unknown keyword argument(s): {', '.join(unknown)}"
    covered = {n for n, _ in params[:n_pos]} | names
    missing = [n for n, d in params if not d and n not in covered]
    missing += [n for n, d in sig.kwonly if not d and n not in names]
    if missing:
        return f"is missing required argument(s): {', '.join(missing)}"
    return None


# ---------------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------------


@dataclass
class CallSite:
    file: str
    line: int
    end_line: int
    caller: str  # qualname of the enclosing symbol, or <module>
    call: ast.Call
    via_attribute: bool
    updated: bool  # the call line itself is inside the change


@dataclass
class ImpactReport:
    symbols: list[ChangedSymbol] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    impacted_files: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    llm_checked: int = 0
    llm_raw: int = 0
    llm_rejected: int = 0


def _in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    return any(s <= line <= e for s, e in ranges)


def _overlaps(sym: SymbolInfo, ranges: list[tuple[int, int]]) -> bool:
    return any(sym.start_line <= e and s <= sym.end_line for s, e in ranges)


def _function_nodes(tree: ast.Module) -> dict[int, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        n.lineno: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }


class ImpactAnalyzer:
    def __init__(
        self,
        change: ChangeSet,
        index: RepoIndex,
        llm: LLMProvider | None = None,
        max_llm_checks: int = 15,
    ) -> None:
        self.change = change
        self.index = index
        self.repo = change.repo
        self.llm = llm
        self.max_llm_checks = max_llm_checks
        self._trees: dict[str, ast.Module | None] = {}
        self._call_index: dict[str, list[CallSite]] | None = None
        self._scope = change.scope()
        # (file, qualname) of a changed symbol -> its call sites (kept off the public model)
        self._sites: dict[tuple[str, str], list[CallSite]] = {}

    # ---- helpers -------------------------------------------------------------------------------

    def _tree(self, path: str) -> ast.Module | None:
        if path not in self._trees:
            self._trees[path] = (
                parse_tree(self.repo.read_text(path), path) if self.repo.has(path) else None
            )
        return self._trees[path]

    def _calls_by_name(self) -> dict[str, list[CallSite]]:
        """Every call site in the new version, keyed by the called name's last component."""
        if self._call_index is not None:
            return self._call_index
        out: dict[str, list[CallSite]] = {}
        for path, module in self.index.modules.items():
            tree = self._tree(path)
            if tree is None:
                continue
            ranges = self._scope.get(path, [])
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = dotted_name(node.func)
                if not name:
                    continue
                enclosing = module.symbol_at(node.lineno)
                out.setdefault(name.split(".")[-1], []).append(
                    CallSite(
                        file=path,
                        line=node.lineno,
                        end_line=node.end_lineno or node.lineno,
                        caller=enclosing.qualname if enclosing else "<module>",
                        call=node,
                        via_attribute=isinstance(node.func, ast.Attribute),
                        updated=_in_ranges(node.lineno, ranges),
                    )
                )
        self._call_index = out
        return out

    def _sites_for(self, file: str, sym: SymbolInfo) -> list[CallSite]:
        """Call sites that resolve (via the call graph) to this symbol."""
        sites = []
        for site in self._calls_by_name().get(sym.name, []):
            if site.file == file and sym.start_line <= site.line <= sym.end_line:
                continue  # recursion
            refs = self.index.resolve_call(site.file, dotted_name(site.call.func) or sym.name)
            if any(r.file == file and r.symbol.qualname == sym.qualname for r in refs):
                sites.append(site)
        return sites

    def _line(self, path: str, line: int) -> str:
        lines = self.repo.lines(path)
        return lines[line - 1].strip() if 0 < line <= len(lines) else ""

    def call_sites(self) -> dict[tuple[str, int], str]:
        """(file, line) of every call to a changed symbol -> 'file:line qualname' of that symbol."""
        out: dict[tuple[str, int], str] = {}
        for (file, qual), sites in self._sites.items():
            for site in sites:
                out[(site.file, site.line)] = f"{file} `{qual}` changed by this change"
        return out

    # ---- main --------------------------------------------------------------------------------

    def run(self, run_usage: Usage | None = None) -> ImpactReport:
        report = ImpactReport()
        for fd in self.change.python_files:
            try:
                self._analyze_file(fd.path, fd.old_path, fd.status, fd.changed_ranges, report)
            except (SyntaxError, ValueError) as exc:
                report.errors.append(f"impact analysis skipped {fd.path}: {exc}")
        if self.llm is not None:
            self._llm_checks(report, run_usage)
        changed_paths = {f.path for f in self.change.files}
        report.impacted_files = sorted(
            {
                site.file
                for sites in self._sites.values()
                for site in sites
                if site.file not in changed_paths
            }
        )
        report.stats = {
            "changed_symbols": len(report.symbols),
            "signature_changes": sum(1 for s in report.symbols if s.signature_changed),
            "removed_symbols": sum(1 for s in report.symbols if s.kind == "removed"),
            "impact_findings": len(report.findings),
            "impacted_files": len(report.impacted_files),
            "llm_caller_checks": report.llm_checked,
            "llm_impact_findings_raw": report.llm_raw,
            "llm_impact_rejected": report.llm_rejected,
        }
        return report

    def _analyze_file(
        self,
        path: str,
        old_path: str | None,
        status: str,
        ranges: list[tuple[int, int]],
        report: ImpactReport,
    ) -> None:
        new_module = self.index.modules.get(path) if status != "deleted" else None
        old_src = self.change.old_sources.get(old_path or path, "")
        old_module = parse_python(old_src, old_path or path) if old_src else None
        old_tree = parse_tree(old_src, old_path or path) if old_src else None
        new_tree = self._tree(path) if new_module else None
        old_syms = {s.qualname: s for s in (old_module.symbols if old_module else [])}
        new_syms = {s.qualname: s for s in (new_module.symbols if new_module else [])}
        old_nodes = _function_nodes(old_tree) if old_tree else {}
        new_nodes = _function_nodes(new_tree) if new_tree else {}

        # added / modified
        for qual, sym in new_syms.items():
            if sym.kind is SymbolKind.CLASS or not _overlaps(sym, ranges):
                continue
            old = old_syms.get(qual)
            kind = "modified" if old else "added"
            new_sig = (
                signature_of(new_nodes[sym.def_line], sym.kind is SymbolKind.METHOD)
                if sym.def_line in new_nodes
                else None
            )
            old_sig = (
                signature_of(old_nodes[old.def_line], old.kind is SymbolKind.METHOD)
                if old and old.def_line in old_nodes
                else None
            )
            sites = self._sites_for(path, sym)
            changed = ChangedSymbol(
                file=path,
                qualname=qual,
                kind=kind,
                line=sym.def_line,
                end_line=sym.end_line,
                signature_changed=bool(old_sig and new_sig and old_sig != new_sig),
                old_signature=old_sig.text() if old_sig else None,
                new_signature=new_sig.text() if new_sig else None,
                callers=len(sites),
                callers_not_updated=sum(1 for s in sites if not s.updated),
            )
            self._sites[(path, qual)] = sites
            report.symbols.append(changed)
            if new_sig is not None:
                for site in sites:
                    why = call_mismatch(new_sig, site.call, site.via_attribute)
                    if why:
                        report.findings.append(
                            self._signature_finding(path, sym, new_sig, site, why)
                        )

        # removed (from this file)
        for qual, sym in old_syms.items():
            if (
                sym.kind is SymbolKind.CLASS
                or qual in new_syms
                or (sym.parent and sym.parent not in old_syms)
            ):
                continue
            if self.index.by_name.get(sym.name):
                still_defined = [
                    r for r in self.index.by_name[sym.name] if r.symbol.kind is not SymbolKind.CLASS
                ]
            else:
                still_defined = []
            removed = ChangedSymbol(file=path, qualname=qual, kind="removed", line=None)
            sites = [] if still_defined else self._calls_by_name().get(sym.name, [])
            removed.callers = len(sites)
            removed.callers_not_updated = len(sites)
            self._sites[(path, qual)] = sites
            report.symbols.append(removed)
            for site in sites:
                report.findings.append(self._removed_finding(path, sym, site))

    # ---- findings ----------------------------------------------------------------------------

    def _signature_finding(
        self, path: str, sym: SymbolInfo, sig: Signature, site: CallSite, why: str
    ) -> Finding:
        return Finding(
            id="TMP",
            file=site.file,
            start_line=site.line,
            end_line=site.end_line,
            category=Category.BUG,
            severity=Severity.HIGH,
            proposed_severity=Severity.HIGH,
            title=f"Call to {sym.qualname} no longer matches its new signature",
            description=(
                f"The change gave `{sym.qualname}` the signature `{sig.text()}`, but this call "
                f"{why}. It will raise TypeError at runtime."
            ),
            evidence=[self._line(site.file, site.line)],
            recommendation=f"Update this call to match `{sym.name}{sig.text()}`, or keep the old "
            "parameters backward compatible (defaults / keyword aliases).",
            test_recommendation=f"Add a test that exercises `{site.caller}` end to end.",
            confidence=0.9,
            sources=[FindingSource.AST],
            rule_id="IMPACT-SIGNATURE",
            symbol=site.caller,
            related=[f"{path}:{sym.def_line} `{sym.qualname}` changed signature to {sig.text()}"],
        )

    def _removed_finding(self, path: str, sym: SymbolInfo, site: CallSite) -> Finding:
        return Finding(
            id="TMP",
            file=site.file,
            start_line=site.line,
            end_line=site.end_line,
            category=Category.BUG,
            severity=Severity.HIGH,
            proposed_severity=Severity.HIGH,
            title=f"Call to removed function {sym.name}",
            description=(
                f"The change removed `{sym.qualname}` from {path}, and no other definition of "
                f"`{sym.name}` exists, but it is still called here. This raises NameError / "
                "AttributeError at runtime."
            ),
            evidence=[self._line(site.file, site.line)],
            recommendation=(
                f"Remove or replace this call, or keep `{sym.name}` as a deprecated wrapper."
            ),
            confidence=0.85,
            sources=[FindingSource.AST],
            rule_id="IMPACT-REMOVED",
            symbol=site.caller,
            related=[f"{path} `{sym.qualname}` removed by this change"],
        )

    # ---- LLM behaviour check -----------------------------------------------------------------

    def _numbered(self, path: str, start: int, end: int) -> str:
        lines = self.repo.lines(path)
        end = min(end, len(lines), start + CALLER_CONTEXT_LINES - 1)
        return "\n".join(f"{n:>5} | {lines[n - 1]}" for n in range(start, end + 1))

    def _old_code(self, sym: ChangedSymbol) -> str:
        fd = next((f for f in self.change.files if f.path == sym.file), None)
        old_src = self.change.old_sources.get((fd.old_path if fd else None) or sym.file, "")
        if not old_src:
            return "(new function)"
        module = parse_python(old_src, sym.file)
        old = next((s for s in module.symbols if s.qualname == sym.qualname), None)
        if old is None:
            return "(new function)"
        return "\n".join(old_src.splitlines()[old.start_line - 1 : old.end_line])

    def _llm_checks(self, report: ImpactReport, run_usage: Usage | None) -> None:
        assert self.llm is not None
        flagged = {(f.file, f.start_line) for f in report.findings}
        candidates = [
            s for s in report.symbols if s.kind == "modified" and s.callers_not_updated > 0
        ]
        candidates.sort(key=lambda s: -s.callers_not_updated)
        checked = 0
        template = load_prompt("impact")
        for sym in candidates[: self.max_llm_checks]:
            new_info = next(
                (x for x in self.index.modules[sym.file].symbols if x.qualname == sym.qualname),
                None,
            )
            if new_info is None:
                continue
            sites: list[CallSite] = [
                s
                for s in self._sites.get((sym.file, sym.qualname), [])
                if not s.updated and (s.file, s.line) not in flagged
            ][:MAX_CALLERS_IN_PROMPT]
            if not sites:
                continue
            caller_blocks: list[str] = []
            scope: dict[str, list[tuple[int, int]]] = {}
            for site in sites:
                mod = self.index.modules[site.file]
                enclosing = mod.symbol_at(site.line)
                start, end = (
                    (enclosing.start_line, enclosing.end_line)
                    if enclosing
                    else (max(1, site.line - 5), site.line + 5)
                )
                code = self._numbered(site.file, start, end)
                caller_blocks.append(f"### `{site.file}` ({site.caller})\n```python\n{code}\n```")
                scope.setdefault(site.file, []).append((start, end))
            prompt = template.render(
                file=sym.file,
                qualname=sym.qualname,
                old_code=self._old_code(sym),
                new_code=self._numbered(sym.file, new_info.start_line, new_info.end_line),
                callers="\n\n".join(caller_blocks),
            )
            messages = [
                Message(role="system", content=load_prompt("system").text),
                Message(role="user", content=prompt),
            ]
            try:
                env = self.llm.generate_structured(messages, LLMReviewEnvelope, usage=run_usage)
            except LLMError as exc:
                report.errors.append(f"impact check for {sym.qualname} failed: {exc}")
                continue
            checked += 1
            items, _, parse_errors = parse_items(env)
            report.errors.extend(parse_errors)
            raw = []
            for item in items:
                f = item.to_finding(sites[0].file)
                raw.append(
                    f.model_copy(
                        update={
                            "rule_id": "IMPACT-BEHAVIOR",
                            "related": [
                                f"{sym.file}:{sym.line} `{sym.qualname}` changed by this change"
                            ],
                        }
                    )
                )
            validated = validate_all(FindingValidator(self.repo, True, scope, 2), raw)
            report.findings.extend(validated.accepted)
            report.llm_raw += len(raw)
            report.llm_rejected += len(validated.rejected)
        report.llm_checked = checked
        logger.info("impact: %d LLM caller checks", checked)
