import type { BeforeAfterRow, BeforeAfterTable, BenchmarkRun, BenchmarkStat, LLMStatus, PerformanceRecord } from "../api/types";
import { dateTime, num, UNAVAILABLE, value } from "../lib/format";
import { Card, Chip, StatusIcon } from "./ui";
import { HBarChart, type BarDatum } from "./HBarChart";
import { StatTile } from "./StatTile";

const sec = (x: number | null | undefined) => value(x, "s", 2);

const STAGES: [keyof PerformanceRecord, string][] = [
  ["file_ingestion_sec", "File ingestion"],
  ["parsing_sec", "Code parsing"],
  ["ast_call_graph_sec", "AST and call graph"],
  ["static_analysis_sec", "Static analysis"],
  ["rag_index_sec", "RAG indexing"],
  ["rag_retrieval_sec", "RAG retrieval"],
  ["prompt_construction_sec", "Prompt construction"],
  ["llm_inference_sec", "LLM inference"],
  ["evidence_validation_sec", "Evidence validation"],
  ["dedup_severity_sec", "Dedup and severity"],
  ["fix_generation_sec", "Fix generation"],
  ["classifier_sec", "Classifier"],
  ["report_generation_sec", "Report generation"],
];

/** Stages with a measured time, plus the names of those that did not run or were not measured. */
export function stageBars(r: PerformanceRecord): { bars: BarDatum[]; missing: string[] } {
  const bars: BarDatum[] = [];
  const missing: string[] = [];
  for (const [key, label] of STAGES) {
    const v = r[key];
    if (typeof v === "number") bars.push({ key: String(key), label, value: v });
    else missing.push(label);
  }
  return { bars, missing };
}

const STATUS_KIND = { complete: "good", partial: "warning", failed: "critical" } as const;

export function ReviewPerformance({ record }: { record: PerformanceRecord }) {
  const { bars, missing } = stageBars(record);
  const failedCalls = record.llm_calls_detail?.filter((c) => !c.ok).length ?? 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-ink">{record.file_name}</span>
        <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
          <StatusIcon kind={STATUS_KIND[record.status]} /> {record.status}
        </span>
        <Chip>{record.run_type} run</Chip>
        <Chip>{record.provider ? `${record.provider} · ${record.model}` : "no LLM"}</Chip>
        <span className="text-xs text-ink-3">{dateTime(record.created_at)}</span>
      </div>
      {record.message && (
        <p className="rounded-lg bg-surface-2 px-3 py-2 text-xs text-ink-2">
          {record.message}
          {record.resets_at ? ` Quota resets at ${dateTime(record.resets_at)}.` : ""}
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatTile label="Total time" value={sec(record.total_sec)} />
        <StatTile label="File size" value={value(record.file_size_kb, " KB", 1)} />
        <StatTile label="Lines of code" value={record.lines_of_code ?? UNAVAILABLE} />
        <StatTile label="LLM inference" value={sec(record.llm_inference_sec)} hint={record.llm_quota_wait_sec ? `plus ${sec(record.llm_quota_wait_sec)} waiting for quota` : undefined} />
        <StatTile label="RAG retrieval" value={sec(record.rag_retrieval_sec)} />
        <StatTile label="Static analysis" value={sec(record.static_analysis_sec)} />
        <StatTile label="Input tokens" value={record.input_tokens ?? UNAVAILABLE} />
        <StatTile label="Output tokens" value={record.output_tokens ?? UNAVAILABLE} />
        <StatTile
          label="Chunks processed"
          value={record.review_units ?? UNAVAILABLE}
          hint={record.units_from_cache ? `${record.units_from_cache} reused from cache` : undefined}
        />
        <StatTile label="Findings" value={record.findings ?? UNAVAILABLE} />
        <StatTile label="Failed chunks" value={record.failed_units ?? UNAVAILABLE} />
        <StatTile label="Skipped chunks" value={record.skipped_units ?? UNAVAILABLE} />
        <StatTile
          label="API requests"
          value={record.llm_calls ?? UNAVAILABLE}
          hint={record.llm_calls ? (failedCalls ? `${failedCalls} failed` : "all succeeded") : undefined}
        />
      </div>
      <HBarChart
        title="Time per stage"
        subtitle="Seconds. Stages can overlap: fix generation includes its own LLM calls."
        data={bars}
        valueLabel="Seconds"
        format={(v) => `${v.toFixed(3)}s`}
        labelWidth={148}
      />
      {missing.length > 0 && <p className="text-xs text-ink-3">Not measured in this run: {missing.join(", ")}.</p>}
      {(record.llm_calls_detail?.length ?? 0) > 0 && (
        <details className="rounded-xl border border-line bg-surface p-4 text-sm">
          <summary className="cursor-pointer text-ink-2">Every LLM call ({record.llm_calls_detail!.length})</summary>
          <div className="mt-3 max-h-72 overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th className="py-1.5 font-medium">Review unit</th>
                  <th className="py-1.5 font-medium">Result</th>
                  <th className="py-1.5 text-right font-medium">Duration</th>
                  <th className="py-1.5 text-right font-medium">Tokens in</th>
                  <th className="py-1.5 text-right font-medium">Tokens out</th>
                </tr>
              </thead>
              <tbody>
                {record.llm_calls_detail!.map((c, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="py-1.5 font-mono text-xs text-ink-2">{c.label ?? "other"}</td>
                    <td className="py-1.5 text-xs text-ink-2">{c.ok ? (c.retry ? "ok (retry)" : "ok") : (c.error_kind ?? "failed")}</td>
                    <td className="tabular py-1.5 text-right text-ink">{sec(c.latency_s)}</td>
                    <td className="tabular py-1.5 text-right text-ink">{c.input_tokens ?? UNAVAILABLE}</td>
                    <td className="tabular py-1.5 text-right text-ink">{c.output_tokens ?? UNAVAILABLE}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

export function ProviderCard({ llm }: { llm: LLMStatus | null }) {
  if (!llm) return null;
  const q = llm.quota;
  const classifier = llm.classifier;
  return (
    <Card title="Model and provider">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        <Row k="Provider" v={llm.provider} />
        <Row k="Model" v={llm.model ?? UNAVAILABLE} />
        <Row k="API status" v={llm.ready ? "ready" : (llm.error ?? "not configured")} />
        <Row k="Tier" v={llm.free_tier ? "free tier, limited" : "as configured"} />
        <Row
          k="Requests today (this machine)"
          v={q ? `${q.requests_used}${q.requests_limit ? ` of ${q.requests_limit}` : ""}` : UNAVAILABLE}
        />
        <Row
          k="Tokens today (this machine)"
          v={q ? `${q.tokens_used.toLocaleString("en-US")}${q.tokens_limit ? ` of ${q.tokens_limit.toLocaleString("en-US")}` : ""}` : UNAVAILABLE}
        />
        <Row k="Quota resets" v={q ? dateTime(q.resets_at) : UNAVAILABLE} />
        <Row k="Change classifier" v={classifier?.enabled ? `${classifier.mode}: ${classifier.model_dir}` : "off"} />
      </dl>
      {llm.data_notice && (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs text-ink-2">
          <StatusIcon kind="warning" /> <span>{llm.data_notice}</span>
        </p>
      )}
    </Card>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-ink-3">{k}:</dt>
      <dd className="min-w-0 break-words text-ink">{v}</dd>
    </div>
  );
}

const CATEGORY = { small: "Small (1-100 lines)", medium: "Medium (101-1,000)", large: "Large (1,001-5,000)" } as const;

export function BenchmarkTable({ run }: { run: BenchmarkRun }) {
  const c = run.conditions;
  const cell = (x: number | null) => (x === null ? UNAVAILABLE : num(x, 2));
  return (
    <div>
      <p className="mb-2 text-xs text-ink-3">
        {c.provider ? `${c.provider} · ${c.model}` : "Static analysis only: no LLM, so no inference time or tokens"} ·{" "}
        {run.repeats} rounds · {c.date} · {c.api_conditions}
      </p>
      {run.pipeline_check_only && (
        <p className="mb-2 text-xs font-medium text-ink">Mock LLM: this checks the pipeline. Do not report these times.</p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              {["Size", "Run", "Complete", "Mean", "Median", "P95", "Min", "Max", "LLM", "RAG", "Static", "Tokens in", "Tokens out", "Findings", "Chunks", "Skipped"].map((h, i) => (
                <th key={h} className={`py-2 pr-3 font-medium ${i > 1 ? "text-right" : ""}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {run.results.map((r: BenchmarkStat) => (
              <tr key={`${r.category}-${r.run_type}`} className="border-b border-line last:border-0">
                <td className="py-2 pr-3 text-ink-2">{CATEGORY[r.category as keyof typeof CATEGORY] ?? r.category}</td>
                <td className="py-2 pr-3 text-ink-2">{r.run_type}</td>
                <td className="tabular py-2 pr-3 text-right text-ink">
                  {r.complete}/{r.runs}
                </td>
                {[r.mean_sec, r.median_sec, r.p95_sec, r.min_sec, r.max_sec, r.mean_llm_inference_sec, r.mean_rag_retrieval_sec, r.mean_static_analysis_sec, r.mean_input_tokens, r.mean_output_tokens, r.mean_findings, r.mean_review_chunks].map((v, i) => (
                  <td key={i} className="tabular py-2 pr-3 text-right text-ink">
                    {cell(v)}
                  </td>
                ))}
                <td className="tabular py-2 pr-3 text-right text-ink">{r.skipped_chunks}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-3">Seconds, over complete runs only. Failed and skipped runs never enter the statistics.</p>
    </div>
  );
}

function verdict(r: BeforeAfterRow): string {
  if (r.original === null || r.improved === null) return "";
  if (r.original === r.improved) return "no change";
  const better = (r.improved > r.original) === (r.higher_is_better ?? true);
  return better ? "better" : "worse";
}

export function comparedBars(rows: BeforeAfterRow[]): BarDatum[] {
  return rows
    .filter((r) => r.original !== null && r.improved !== null)
    .flatMap((r) => [
      { key: `${r.metric}-o`, label: `${r.metric}: original`, value: r.original as number, color: "var(--sev-info)" },
      { key: `${r.metric}-i`, label: `${r.metric}: improved`, value: r.improved as number },
    ]);
}

export function BeforeAfter({ table }: { table: BeforeAfterTable }) {
  const bars = comparedBars(table.rows);
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-xl border border-line bg-surface p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th className="py-2 pr-4 font-medium">Benchmark</th>
              <th className="py-2 pr-4 font-medium">Metric</th>
              <th className="py-2 pr-4 text-right font-medium">Original</th>
              <th className="py-2 pr-4 text-right font-medium">Improved</th>
              <th className="py-2 pr-4 font-medium">Result</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r) => (
              <tr key={`${r.benchmark}-${r.metric}`} className="border-b border-line align-top last:border-0">
                <td className="py-2 pr-4 text-ink-2">{r.benchmark}</td>
                <td className="py-2 pr-4 text-ink">{r.metric}</td>
                <td className="tabular py-2 pr-4 text-right text-ink">{r.original === null ? "N/A" : num(r.original)}</td>
                <td className="tabular py-2 pr-4 text-right text-ink">{r.improved === null ? "N/A" : num(r.improved)}</td>
                <td className="py-2 pr-4 text-xs text-ink-3">{verdict(r) || r.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="ml-4 mt-3 list-disc space-y-1 text-xs text-ink-3">
          {table.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </div>
      {bars.length > 0 && (
        <HBarChart title="Original vs improved" subtitle="Only metrics measured on the same samples." data={bars} valueLabel="Value" format={(v) => v.toFixed(3)} labelWidth={200} />
      )}
    </div>
  );
}
