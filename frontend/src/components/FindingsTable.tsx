import { Fragment, useMemo, useState } from "react";
import type { Category, Finding, Severity, SuggestedFix } from "../api/types";
import { SEVERITIES } from "../api/types";
import { CATEGORY_LABEL, SEVERITY_LABEL, SOURCE_LABEL, location } from "../lib/format";
import { DiffView } from "./DiffView";
import { Button, Chip, EmptyState, SeverityBadge, StatusIcon } from "./ui";

type SortKey = "priority" | "confidence" | "location";
const RANK: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };

export interface Filters {
  query: string;
  severities: Set<Severity>;
  category: Category | "";
  source: string;
  file: string;
}

export const EMPTY_FILTERS: Filters = { query: "", severities: new Set(), category: "", source: "", file: "" };

export function applyFilters(findings: Finding[], f: Filters, sort: SortKey = "priority"): Finding[] {
  const q = f.query.trim().toLowerCase();
  const out = findings.filter(
    (x) =>
      (f.severities.size === 0 || f.severities.has(x.severity)) &&
      (!f.category || x.category === f.category) &&
      (!f.source || x.sources.includes(f.source as Finding["sources"][number])) &&
      (!f.file || x.file === f.file) &&
      (!q ||
        [x.title, x.description, x.file, x.rule_id ?? "", x.symbol ?? "", x.cwe ?? ""]
          .join(" ")
          .toLowerCase()
          .includes(q)),
  );
  const cmp: Record<SortKey, (a: Finding, b: Finding) => number> = {
    priority: (a, b) => RANK[b.severity] + b.confidence - (RANK[a.severity] + a.confidence),
    confidence: (a, b) => b.confidence - a.confidence,
    location: (a, b) => a.file.localeCompare(b.file) || a.start_line - b.start_line,
  };
  return [...out].sort(cmp[sort]);
}

function ConfidenceBar({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-2" title={`Confidence ${value.toFixed(2)} (ranking signal, not a probability)`}>
      <span className="h-1.5 w-12 overflow-hidden rounded-full" style={{ background: "var(--accent-wash)" }}>
        <span className="bar-fill block h-full rounded-full" style={{ width: `${value * 100}%`, background: "var(--accent)" }} />
      </span>
      <span className="tabular text-xs text-ink-2">{value.toFixed(2)}</span>
    </span>
  );
}

export function fixStatus(fix: SuggestedFix): { label: string; text: string } {
  if (fix.verified)
    return {
      label: "Verified fix",
      text:
        fix.source === "ruff"
          ? "Ruff marks this fix as safe: it does not change behaviour."
          : "Re-analysis of the patched file: the issue is gone and nothing new appeared.",
    };
  return {
    label: "Suggested fix (review before applying)",
    text:
      fix.source === "ruff"
        ? "Ruff marks this fix as unsafe: it can change behaviour."
        : "The patch parses and adds no new issues, but no tool can confirm the problem is solved.",
  };
}

function FixView({ fix }: { fix: SuggestedFix }) {
  const status = fixStatus(fix);
  return (
    <div>
      <p className="mb-1 flex flex-wrap items-center gap-2 text-xs font-medium text-ink-3">
        <StatusIcon kind={fix.verified ? "good" : "info"} />
        <span className="text-ink">{status.label}</span>
        <Chip>{fix.source === "ruff" ? "Ruff autofix" : "LLM"}</Chip>
      </p>
      <p className="mb-2 text-xs text-ink-3">{status.text} Never applied automatically.</p>
      <DiffView diff={fix.diff} label={`Suggested fix for ${fix.file}`} />
      {fix.checks.length > 0 && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-ink-3">Checks performed ({fix.checks.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-2">
            {fix.checks.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function FindingDetail({ f }: { f: Finding }) {
  return (
    <div className="grid gap-4 px-4 pb-4 pt-1 text-sm lg:grid-cols-2">
      <div className="space-y-3">
        <p className="whitespace-pre-line leading-relaxed text-ink-2">{f.description}</p>
        {f.evidence.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-ink-3">Evidence</p>
            <pre className="overflow-x-auto rounded-lg bg-code p-3 font-mono text-xs leading-relaxed text-ink">
              {f.evidence.slice(0, 3).join("\n\n")}
            </pre>
          </div>
        )}
        {f.related && f.related.length > 0 && (
          <div>
            <p className="mb-1 text-xs font-medium text-ink-3">Related locations</p>
            <ul className="space-y-0.5 font-mono text-xs text-ink-2">
              {f.related.map((r) => (
                <li key={r} className="break-words">
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}
        {f.suggested_fix && <FixView fix={f.suggested_fix} />}
      </div>
      <div className="space-y-3">
        {f.recommendation && (
          <div>
            <p className="mb-1 text-xs font-medium text-ink-3">Recommendation</p>
            <p className="leading-relaxed text-ink">{f.recommendation}</p>
          </div>
        )}
        {f.test_recommendation && (
          <div>
            <p className="mb-1 text-xs font-medium text-ink-3">Test to add</p>
            <p className="leading-relaxed text-ink">{f.test_recommendation}</p>
          </div>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
          {f.symbol && (
            <>
              <dt className="text-ink-3">Symbol</dt>
              <dd className="font-mono text-ink-2">{f.symbol}</dd>
            </>
          )}
          {f.rule_id && (
            <>
              <dt className="text-ink-3">Rule</dt>
              <dd className="font-mono text-ink-2">{f.rule_id}</dd>
            </>
          )}
          {f.cwe && (
            <>
              <dt className="text-ink-3">CWE</dt>
              <dd>
                <a
                  className="text-accent-ink underline underline-offset-2"
                  href={`https://cwe.mitre.org/data/definitions/${f.cwe.replace("CWE-", "")}.html`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {f.cwe}
                </a>
              </dd>
            </>
          )}
          {f.proposed_severity && f.proposed_severity !== f.severity && (
            <>
              <dt className="text-ink-3">Proposed severity</dt>
              <dd className="text-ink-2">
                {SEVERITY_LABEL[f.proposed_severity]} (rubric set {SEVERITY_LABEL[f.severity]})
              </dd>
            </>
          )}
        </dl>
        {f.notes.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer text-ink-3">Validation audit trail ({f.notes.length})</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-2">
              {f.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

export function FindingsTable({ findings }: { findings: Finding[] }) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortKey>("priority");
  const [open, setOpen] = useState<Set<string>>(new Set());

  const files = useMemo(() => [...new Set(findings.map((f) => f.file))].sort(), [findings]);
  const categories = useMemo(
    () => [...new Set(findings.map((f) => f.category))].sort() as Category[],
    [findings],
  );
  const sources = useMemo(() => [...new Set(findings.flatMap((f) => f.sources))].sort(), [findings]);
  const shown = useMemo(() => applyFilters(findings, filters, sort), [findings, filters, sort]);
  const active =
    filters.query || filters.severities.size || filters.category || filters.source || filters.file;

  const toggleSeverity = (s: Severity) =>
    setFilters((f) => {
      const next = new Set(f.severities);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return { ...f, severities: next };
    });
  const toggleOpen = (id: string) =>
    setOpen((o) => {
      const next = new Set(o);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (findings.length === 0) {
    return (
      <EmptyState title="No findings above the confidence threshold">
        The code passed static analysis{" "}
        and, if enabled, the LLM review. Lower the minimum confidence to see weaker signals.
      </EmptyState>
    );
  }

  const selectCls = "rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink";
  return (
    <section className="rounded-xl border border-line bg-surface" aria-label="Findings">
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
        <input
          type="search"
          placeholder="Search title, file, rule, CWE…"
          aria-label="Search findings"
          value={filters.query}
          onChange={(e) => setFilters({ ...filters, query: e.target.value })}
          className="min-w-52 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-ink-3"
        />
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by severity">
          {SEVERITIES.map((s) => {
            const on = filters.severities.has(s);
            const count = findings.filter((f) => f.severity === s).length;
            return (
              <button
                key={s}
                type="button"
                aria-pressed={on}
                onClick={() => toggleSeverity(s)}
                disabled={count === 0}
                className={`rounded-lg border px-2 py-1 text-xs transition disabled:opacity-40 ${
                  on ? "border-accent bg-accent-wash text-ink" : "border-line text-ink-2 hover:bg-surface-2"
                }`}
              >
                {SEVERITY_LABEL[s]} <span className="tabular text-ink-3">{count}</span>
              </button>
            );
          })}
        </div>
        <select
          aria-label="Filter by category"
          className={selectCls}
          value={filters.category}
          onChange={(e) => setFilters({ ...filters, category: e.target.value as Category | "" })}
        >
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter by source"
          className={selectCls}
          value={filters.source}
          onChange={(e) => setFilters({ ...filters, source: e.target.value })}
        >
          <option value="">All sources</option>
          {sources.map((s) => (
            <option key={s} value={s}>
              {SOURCE_LABEL[s] ?? s}
            </option>
          ))}
        </select>
        {files.length > 1 && (
          <select
            aria-label="Filter by file"
            className={`${selectCls} max-w-56`}
            value={filters.file}
            onChange={(e) => setFilters({ ...filters, file: e.target.value })}
          >
            <option value="">All files</option>
            {files.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        )}
        <select
          aria-label="Sort findings"
          className={selectCls}
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
        >
          <option value="priority">Sort: priority</option>
          <option value="confidence">Sort: confidence</option>
          <option value="location">Sort: location</option>
        </select>
        {active ? (
          <Button variant="ghost" onClick={() => setFilters(EMPTY_FILTERS)}>
            Clear
          </Button>
        ) : null}
      </div>

      <p className="px-4 pt-3 text-xs text-ink-3" aria-live="polite">
        Showing {shown.length} of {findings.length} findings
      </p>

      {shown.length === 0 ? (
        <p className="p-8 text-center text-sm text-ink-3">No findings match these filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="w-8" />
                <th className="px-2 py-2 font-medium">ID</th>
                <th className="px-2 py-2 font-medium">Severity</th>
                <th className="px-2 py-2 font-medium">Finding</th>
                <th className="px-2 py-2 font-medium">Category</th>
                <th className="px-2 py-2 font-medium">Sources</th>
                <th className="px-2 py-2 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((f) => {
                const isOpen = open.has(f.id);
                return (
                  <Fragment key={f.id}>
                    <tr
                      className={`cursor-pointer border-b border-line align-top hover:bg-surface-2 ${isOpen ? "bg-surface-2" : ""}`}
                      onClick={() => toggleOpen(f.id)}
                    >
                      <td className="py-2.5 pl-3">
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          aria-label={`${isOpen ? "Collapse" : "Expand"} ${f.id}`}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleOpen(f.id);
                          }}
                          className="rounded p-0.5 text-ink-3 hover:text-ink"
                        >
                          <svg viewBox="0 0 16 16" className={`size-4 transition ${isOpen ? "rotate-90" : ""}`} aria-hidden="true">
                            <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
                          </svg>
                        </button>
                      </td>
                      <td className="tabular whitespace-nowrap px-2 py-2.5 font-mono text-xs text-ink-3">{f.id}</td>
                      <td className="px-2 py-2.5">
                        <SeverityBadge severity={f.severity} />
                      </td>
                      <td className="px-2 py-2.5">
                        <p className="font-medium text-ink">{f.title}</p>
                        <p className="mt-0.5 font-mono text-xs text-ink-3">
                          {location(f.file, f.start_line, f.end_line)}
                          {f.suggested_fix && (
                            <span className="ml-2 font-sans text-accent-ink">
                              {f.suggested_fix.verified ? "verified fix" : "fix suggested"}
                            </span>
                          )}
                        </p>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-ink-2">{CATEGORY_LABEL[f.category]}</td>
                      <td className="px-2 py-2.5">
                        <div className="flex flex-wrap gap-1">
                          {f.sources.map((s) => (
                            <Chip key={s}>{SOURCE_LABEL[s] ?? s}</Chip>
                          ))}
                        </div>
                      </td>
                      <td className="px-2 py-2.5">
                        <ConfidenceBar value={f.confidence} />
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b border-line bg-surface-2">
                        <td colSpan={7}>
                          <FindingDetail f={f} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
