import { Link } from "react-router-dom";
import type {
  ComparisonColumn,
  ComparisonRow,
  ComparisonTable,
  ExperimentConfiguration,
  MetricDefinition,
} from "../api/types";
import { Card, Chip } from "./ui";

export function Flag({ on, name }: { on: boolean; name: string }) {
  return (
    <span
      aria-label={`${name} ${on ? "on" : "off"}`}
      title={`${name} ${on ? "on" : "off"}`}
      className={on ? "font-semibold text-accent-ink" : "text-ink-3"}
    >
      {on ? "✓" : "✗"}
    </span>
  );
}

/** "Static ✓ · LLM ✗ · RAG ✗": the three switches of an experiment configuration. */
export function ConfigFlags({ c }: { c: ExperimentConfiguration }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-2">
      <span>
        Static <Flag on={c.static} name="Static" />
      </span>
      <span>
        LLM <Flag on={c.llm} name="LLM" />
      </span>
      <span>
        RAG <Flag on={c.rag} name="RAG" />
      </span>
    </span>
  );
}

function value(row: ComparisonRow, col: ComparisonColumn): { text: string; title?: string } {
  if (row.status !== "ok") return { text: "N/A", title: row.na["*"] ?? row.status.replace("_", " ") };
  const v = row.values[col.key];
  if (v === null || v === undefined) return { text: "N/A", title: row.na[col.key] ?? row.na["*"] ?? "not available" };
  const text = Number.isInteger(v) && col.digits === 0 ? v.toLocaleString("en-US") : v.toFixed(col.digits);
  const sd = row.sd[col.key];
  const spread = row.spread[col.key];
  const parts: string[] = [];
  if (spread && spread[0] !== null && spread[1] !== null && spread[0] !== undefined && spread[1] !== undefined)
    parts.push(`min ${spread[0].toFixed(col.digits)}, max ${spread[1].toFixed(col.digits)}`);
  if (sd !== null && sd !== undefined) parts.push(`mean ± SD over ${row.n_runs} runs`);
  return { text: sd !== null && sd !== undefined ? `${text} ± ${sd.toFixed(col.digits)}` : text, title: parts.join("; ") || undefined };
}

function header(col: ComparisonColumn, defs: Record<string, MetricDefinition>): string | undefined {
  const d = col.metric ? defs[col.metric] : undefined;
  if (!d) return undefined;
  const better = d.higher_is_better === null ? "" : d.higher_is_better ? " Higher is better." : " Lower is better.";
  return `${d.name}: ${d.definition} Scale ${d.scale}.${better}`;
}

function conditionText(v: unknown): string {
  if (v === null || v === undefined) return "–";
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function ComparisonCard({
  table,
  definitions,
}: {
  table: ComparisonTable;
  definitions: Record<string, MetricDefinition>;
}) {
  const hasConfig = table.rows.some((r) => r.configuration);
  const groups = table.columns.some((c) => c.group);
  const groupSpans: { name: string; span: number }[] = [];
  for (const c of table.columns) {
    const name = c.group ?? "";
    const last = groupSpans[groupSpans.length - 1];
    if (last && last.name === name) last.span += 1;
    else groupSpans.push({ name, span: 1 });
  }
  const lead = hasConfig ? 4 : 1;
  const tail = (table.show_counts ? 3 : 0) + (hasConfig ? 1 : 0);
  const notRun = table.rows.filter((r) => r.status !== "ok" && r.how_to_run);
  const sources = [...new Set(table.rows.flatMap((r) => r.run_ids))].sort();
  const conditions = Object.entries(table.conditions).filter(([, v]) => v !== null && v !== undefined);
  return (
    <Card title={table.title} action={table.supplementary ? <Chip>Supplementary</Chip> : undefined}>
      {table.about && <p className="-mt-2 mb-3 text-xs text-ink-3">{table.about}</p>}
      {conditions.length > 0 && (
        <div className="mb-3 rounded-lg bg-surface-2 p-3">
          <p className="mb-1.5 text-xs font-medium text-ink-2">Experiment conditions</p>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            {conditions.map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="shrink-0 text-ink-3">{k}:</dt>
                <dd className="text-ink">{conditionText(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            {groups && (
              <tr className="text-xs text-ink-3">
                <th colSpan={lead} />
                {groupSpans.map((g, i) => (
                  <th key={i} colSpan={g.span} className="border-b border-line px-2 pt-1 text-center font-medium">
                    {g.name}
                  </th>
                ))}
                {tail > 0 && <th colSpan={tail} />}
              </tr>
            )}
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th className="py-2 pr-3 font-medium">{hasConfig ? "Configuration" : "Method"}</th>
              {hasConfig && (
                <>
                  <th className="px-1 py-2 text-center font-medium">Static</th>
                  <th className="px-1 py-2 text-center font-medium">LLM</th>
                  <th className="px-1 py-2 text-center font-medium">RAG</th>
                </>
              )}
              {table.columns.map((c) => (
                <th key={c.key} title={header(c, definitions)} className="px-2 py-2 text-right font-medium">
                  {c.label}
                </th>
              ))}
              {table.show_counts && (
                <>
                  <th className="px-2 py-2 text-right font-medium">n</th>
                  <th className="px-2 py-2 text-right font-medium">Failed</th>
                  <th className="px-2 py-2 text-right font-medium">Runs</th>
                </>
              )}
              {hasConfig && <th className="py-2 pl-2 font-medium">Model</th>}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r) => (
              <tr key={r.label} className="border-b border-line last:border-0">
                <td className="py-2 pr-3 text-ink">
                  {r.label}
                  {r.status !== "ok" && (
                    <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs text-ink-3">
                      {r.status === "not_run" ? "not run" : r.status}
                    </span>
                  )}
                </td>
                {hasConfig && (
                  <>
                    <td className="px-1 py-2 text-center">{r.configuration && <Flag on={r.configuration.static} name="Static" />}</td>
                    <td className="px-1 py-2 text-center">{r.configuration && <Flag on={r.configuration.llm} name="LLM" />}</td>
                    <td className="px-1 py-2 text-center">{r.configuration && <Flag on={r.configuration.rag} name="RAG" />}</td>
                  </>
                )}
                {table.columns.map((c) => {
                  const v = value(r, c);
                  return (
                    <td key={c.key} title={v.title} className={`tabular px-2 py-2 text-right ${v.text === "N/A" ? "text-ink-3" : "text-ink"}`}>
                      {v.text}
                    </td>
                  );
                })}
                {table.show_counts && (
                  <>
                    <td className="tabular px-2 py-2 text-right text-ink-2">{r.n ?? "–"}</td>
                    <td className="tabular px-2 py-2 text-right text-ink-2">{r.n_failed ?? "–"}</td>
                    <td className="tabular px-2 py-2 text-right text-ink-2">{r.status === "ok" && r.n_runs ? r.n_runs : "–"}</td>
                  </>
                )}
                {hasConfig && (
                  <td className="py-2 pl-2 text-xs text-ink-2">
                    {r.model ?? (r.configuration && !r.configuration.llm ? "no LLM" : "–")}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.rows.some((r) => Object.keys(r.sd).length > 0) && (
        <p className="mt-2 text-xs text-ink-3">Values with ± are the mean ± sample standard deviation over repeated runs.</p>
      )}
      {table.rows.some((r) => r.notes.length > 0) && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-3">
          {table.rows.flatMap((r) => r.notes.map((n) => <li key={r.label + n}>{r.label}: {n}</li>))}
        </ul>
      )}
      {notRun.length > 0 && (
        <div className="mt-3 text-xs">
          <p className="mb-1 font-medium text-ink-2">N/A rows: no valid saved run yet. To produce them:</p>
          <ul className="space-y-1">
            {notRun.map((r) => (
              <li key={r.label} className="text-ink-3">
                {r.label}: <code className="break-all font-mono text-ink-2">{r.how_to_run}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {table.fairness.length > 0 && (
        <div className="mt-3 text-xs">
          <p className="mb-1 font-medium text-ink-2">Fairness checks</p>
          <ul className="space-y-0.5">
            {table.fairness.map((f) => (
              <li key={f.name} className="text-ink-2">
                <span className={f.ok === true ? "text-accent-ink" : f.ok === false ? "text-critical" : "text-ink-3"}>
                  {f.ok === true ? "✓" : f.ok === false ? "✗" : "?"}
                </span>{" "}
                {f.name}
                <span className="text-ink-3">: {f.detail}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {table.observations.length > 0 && (
        <div className="mt-3 text-xs">
          <p className="mb-1 font-medium text-ink-2">Observations (computed from the numbers above)</p>
          <ul className="ml-4 list-disc space-y-0.5 text-ink">
            {table.observations.map((o) => (
              <li key={o}>{o}</li>
            ))}
          </ul>
        </div>
      )}
      {table.notes.length > 0 && (
        <ul className="mt-3 ml-4 list-disc space-y-0.5 text-xs text-ink-3">
          {table.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {sources.length > 0 && (
        <p className="mt-3 text-xs text-ink-3">
          Source runs:{" "}
          {sources.map((s, i) => (
            <span key={s}>
              {i > 0 && ", "}
              <Link to={`/evaluation/${s}`} className="font-mono text-accent-ink hover:underline">
                {s}
              </Link>
            </span>
          ))}
        </p>
      )}
    </Card>
  );
}

export function DefinitionsTable({ definitions }: { definitions: MetricDefinition[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-line text-left text-xs text-ink-3">
            <th className="py-2 pr-4 font-medium">Metric</th>
            <th className="py-2 pr-4 font-medium">Definition</th>
            <th className="py-2 pr-4 font-medium">Scale</th>
            <th className="py-2 font-medium">Better</th>
          </tr>
        </thead>
        <tbody>
          {definitions.map((d) => (
            <tr key={d.key} className="border-b border-line align-top last:border-0">
              <td className="py-2 pr-4 font-medium text-ink">{d.name}</td>
              <td className="py-2 pr-4 text-ink-2">{d.definition}</td>
              <td className="py-2 pr-4 text-ink-2">{d.scale}</td>
              <td className="py-2 text-ink-2">{d.higher_is_better === null ? "–" : d.higher_is_better ? "higher" : "lower"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
