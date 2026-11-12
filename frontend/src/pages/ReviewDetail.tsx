import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Category, ReviewResult, ReviewSummary, Severity } from "../api/types";
import { SEVERITIES } from "../api/types";
import { ChangePanel } from "../components/ChangePanel";
import { SuspectsPanel } from "../components/SuspectsPanel";
import { FindingsTable } from "../components/FindingsTable";
import { HBarChart, type BarDatum } from "../components/HBarChart";
import { StatTile } from "../components/StatTile";
import { Button, Card, Chip, EmptyState, ErrorBanner, JobStatusBadge, Spinner } from "../components/ui";
import { CATEGORY_LABEL, MODE_LABEL, SEVERITY_LABEL, compact, dateTime, duration, num, pct } from "../lib/format";
import { useApi, useNow } from "../lib/hooks";

// Ordinal ramp: critical is the strongest step (validated in both themes, see index.css).
const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "var(--sev-critical)",
  high: "var(--sev-high)",
  medium: "var(--sev-medium)",
  low: "var(--sev-low)",
  info: "var(--sev-info)",
};

export function severityData(s: ReviewSummary): BarDatum[] {
  return SEVERITIES.map((sev) => ({
    key: sev,
    label: SEVERITY_LABEL[sev],
    value: s.by_severity[sev] ?? 0,
    color: SEVERITY_COLOR[sev],
  }));
}

export function categoryData(s: ReviewSummary): BarDatum[] {
  return (Object.entries(s.by_category) as [Category, number][])
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({ key: k, label: CATEGORY_LABEL[k] ?? k, value: v }));
}

function ProgressLog({ lines, running }: { lines: string[]; running: boolean }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines.length]);
  return (
    <pre
      ref={ref}
      aria-live={running ? "polite" : "off"}
      className="max-h-72 overflow-auto rounded-lg bg-code p-3 font-mono text-xs leading-relaxed text-ink-2"
    >
      {lines.length ? lines.join("\n") : "Waiting to start…"}
    </pre>
  );
}

/** When the LLM failed on some review units (quota, timeout, bad reply) the result is partial. */
export function llmFailure(result: ReviewResult): { failed: number; total: number; message: string } | null {
  const st = result.stats as Record<string, unknown>;
  const failed = Number(st.units_failed ?? 0);
  if (!failed || st.mode === "static_only") return null;
  const first = result.errors.find((e) => e.includes("LLM review failed")) ?? result.errors[0] ?? "";
  return { failed, total: Number(st.units_total ?? failed), message: first.replace(/^\[[^\]]*\]\s*/, "") };
}

interface Timing {
  total_sec: number;
  static_analysis_sec: number;
  rag_index_sec: number;
  rag_retrieval_sec: number;
  llm_inference_sec: number;
  llm_calls: number;
  llm_rate_limit_wait_sec: number | null;
  validation_sec: number;
  report_generation_sec: number | null;
  other_sec: number;
}

/** "Time" row from the review's timing breakdown (seconds); null for reviews made before it existed. */
export function timingRow(t: Timing | undefined): [string, string] | null {
  if (!t || typeof t.total_sec !== "number") return null;
  const s = (x: number | null | undefined) => `${(x ?? 0).toFixed(2)}s`;
  const parts = [
    `total ${s(t.total_sec)}`,
    `static analysis ${s(t.static_analysis_sec)}`,
    `RAG ${s(t.rag_index_sec + t.rag_retrieval_sec)}`,
    `LLM ${s(t.llm_inference_sec)} (${t.llm_calls} calls)`,
    `validation ${s(t.validation_sec)}`,
  ];
  if (t.report_generation_sec != null) parts.push(`reports ${s(t.report_generation_sec)}`);
  parts.push(`other ${s(t.other_sec)}`);
  if (t.llm_rate_limit_wait_sec) parts.push(`of which quota waiting ${s(t.llm_rate_limit_wait_sec)}`);
  return ["Time", parts.join(" · ")];
}

function PipelinePanel({ result }: { result: ReviewResult }) {
  const st = result.stats as Record<string, any>;
  const usage = st.llm_usage as { calls: number; input_tokens: number; output_tokens: number; parse_retries: number } | undefined;
  const rejected = (st.llm_rejected_by_reason ?? {}) as Record<string, number>;
  const triage = (st.static_assessments ?? {}) as Record<string, number>;
  const ctx = (st.context_items_by_reason ?? {}) as Record<string, number>;
  const timings = (st.timings_s ?? {}) as Record<string, number>;
  const staticRaw = (st.static_findings_raw ?? {}) as Record<string, number>;
  const rows: [string, string][] = [
    ["Mode", MODE_LABEL[st.mode] ?? String(st.mode)],
    ["Files / lines reviewed", `${num(st.files_reviewed)} / ${compact(Number(st.lines_reviewed ?? 0))}`],
    ["Static findings (raw)", Object.entries(staticRaw).map(([k, v]) => `${k} ${v}`).join(", ") || "–"],
  ];
  if (usage) {
    rows.push(
      ["LLM calls", `${usage.calls} (${num(st.units_total)} review units, ${num(st.units_failed)} failed)`],
      ["Tokens (in + out)", `${compact(usage.input_tokens)} + ${compact(usage.output_tokens)}`],
      ["LLM findings", `${num(st.llm_findings_raw)} proposed, ${num(st.llm_findings_valid)} verified`],
      [
        "Rejected as unverifiable",
        `${pct(st.llm_rejection_rate as number, 1)}${
          Object.keys(rejected).length ? ` (${Object.entries(rejected).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(", ")})` : ""
        }`,
      ],
      ["Relocated by validator", num(st.llm_repaired ?? 0)],
      ["LLM triage of static findings", Object.entries(triage).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(", ") || "–"],
      ["Context items (per unit)", `${num(st.avg_context_items_per_unit, 1)} · ${Object.entries(ctx).map(([k, v]) => `${k} ${v}`).join(", ") || "none"}`],
    );
  }
  rows.push(
    ["Duplicates merged", num(st.dedup_merged ?? 0)],
    ["Below confidence threshold", num(st.filtered_low_confidence ?? 0)],
    timingRow(st.timing as Timing | undefined) ?? [
      "Time",
      Object.entries(timings).map(([k, v]) => `${k.replaceAll("_", " ")} ${v.toFixed(1)}s`).join(" · "),
    ],
  );
  return (
    <Card title="How this review was produced">
      <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-ink-3">{k}</dt>
            <dd className="tabular break-words text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {result.errors.length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-ink-2">Pipeline warnings ({result.errors.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-3">
            {result.errors.slice(0, 50).map((e, i) => (
              <li key={i} className="break-words">
                {e}
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

export default function ReviewDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [resumes, setResumes] = useState(0); // a resume restarts the status polling
  const [resumeError, setResumeError] = useState<string | null>(null);
  const { data, error, loading } = useApi(() => api.getReview(id), [id, resumes], {
    pollMs: 1500,
    shouldPoll: (d) => d.job.status === "queued" || d.job.status === "running",
  });
  const running = data?.job.status === "queued" || data?.job.status === "running";
  const now = useNow(1000, running);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <Spinner /> Loading review…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="space-y-3">
        <ErrorBanner title="Review not available" message={error} />
        <Link to="/reviews" className="text-sm text-accent-ink underline">
          Back to history
        </Link>
      </div>
    );
  }
  if (!data) return null;
  const { job, result } = data;
  const s = job.summary;

  const remove = async () => {
    if (!window.confirm(`Delete the review of ${job.name}? This removes its reports too.`)) return;
    setDeleting(true);
    try {
      await api.deleteReview(job.id);
      navigate("/reviews");
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : String(e));
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs text-ink-3">
            <Link to="/reviews" className="hover:underline">
              History
            </Link>{" "}
            / {job.id}
          </p>
          <h1 className="mt-1 flex flex-wrap items-center gap-3 text-xl font-semibold text-ink">
            <span className="truncate">{job.name}</span>
            <JobStatusBadge status={job.status} />
          </h1>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {job.change && (
              <Chip>
                {job.change.kind === "git" ? "git" : "ZIPs"}: {job.change.base} → {job.change.head}
              </Chip>
            )}
            <Chip>{job.options.agent === "bug_detection" ? "Bug Detection Agent" : "Code Review Agent"}</Chip>
            <Chip>{MODE_LABEL[job.options.mode]}</Chip>
            {job.options.mode !== "static_only" && <Chip>{job.provider} · {job.model}</Chip>}
            {job.options.mode !== "static_only" && <Chip>RAG {job.options.rag_enabled ? "on" : "off"}</Chip>}
            <Chip>min confidence {job.options.min_confidence.toFixed(2)}</Chip>
            <Chip>{dateTime(job.created_at)}</Chip>
            <Chip>{duration(job.started_at, job.finished_at, now)}</Chip>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {job.status === "done" &&
            (["pdf", "md", "json", "sarif"] as const).map((fmt) => (
              <a
                key={fmt}
                href={api.reportUrl(job.id, fmt)}
                download
                className="inline-flex items-center rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-2"
              >
                {fmt.toUpperCase()}
              </a>
            ))}
          {!running && (
            <Button variant="danger" onClick={remove} disabled={deleting}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {deleteError && <ErrorBanner title="Could not delete" message={deleteError} />}
      {resumeError && <ErrorBanner title="Could not resume" message={resumeError} />}
      {error && <ErrorBanner title="Connection problem (retrying)" message={error} />}

      {running && (
        <Card
          title={
            <span className="flex items-center gap-2">
              <Spinner className="size-4 text-accent" /> Reviewing… {duration(job.started_at ?? job.created_at, null, now)}
            </span>
          }
        >
          <ProgressLog lines={job.progress} running />
        </Card>
      )}

      {job.status === "failed" && (
        <>
          <ErrorBanner title="The review failed" message={job.error ?? "Unknown error"} />
          <Card title="Progress log">
            <ProgressLog lines={job.progress} running={false} />
          </Card>
        </>
      )}

      {job.status === "done" && result && llmFailure(result) && (
        <ErrorBanner
          title={`The LLM could not review ${llmFailure(result)!.failed} of ${llmFailure(result)!.total} part(s): results are partial`}
          message={`Those parts have static-analysis findings only. ${llmFailure(result)!.message}`}
        />
      )}

      {job.status === "done" && job.resumable && (
        <Card
          title="This review is partial"
          action={
            <Button
              variant="primary"
              onClick={async () => {
                setResumeError(null);
                try {
                  await api.resumeReview(job.id);
                  setResumes((n) => n + 1);
                } catch (e) {
                  setResumeError(e instanceof Error ? e.message : String(e));
                }
              }}
            >
              Resume review
            </Button>
          }
        >
          <p className="text-sm text-ink-2">
            {job.error ?? "Some parts were not reviewed."} Finished parts are saved and will not be repeated.
          </p>
        </Card>
      )}

      {job.status === "done" && (
        <p className="text-xs text-ink-3">
          <Link to={`/performance?review=${job.id}`} className="text-accent-ink hover:underline">
            Performance analysis of this review
          </Link>
        </p>
      )}

      {job.status === "done" && s && result && (
        <>
          <div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="Total findings" value={s.total_findings} hint={`${s.by_severity.critical ?? 0} critical · ${s.by_severity.high ?? 0} high`} />
              <StatTile label="Security issues" value={s.security_issues} />
              <StatTile label="Potential bugs" value={s.potential_bugs} hint="bugs + edge cases" />
              <StatTile label="Error handling" value={s.error_handling_issues} />
              <StatTile label="Maintainability" value={s.maintainability_issues} hint="incl. code quality" />
              <StatTile label="Testing gaps" value={s.testing_gaps} />
              <StatTile label="Files analyzed" value={s.files_analyzed} hint={`${compact(s.lines_analyzed)} lines`} />
              <StatTile label="Issue density" value={s.weighted_density_per_kloc.toFixed(1)} hint="weighted findings / 1k lines" />
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <HBarChart
              title="Findings by severity"
              subtitle="Darker = more severe"
              data={severityData(s)}
              labelWidth={64}
              valueLabel="Findings"
            />
            <HBarChart
              title="Findings by category"
              data={categoryData(s)}
              valueLabel="Findings"
              emptyText="No findings."
            />
            <HBarChart
              title="Most affected files"
              subtitle="Severity-weighted score (critical 10, high 5, medium 2, low 0.5)"
              data={s.top_files.map(([file, w]) => ({ key: file, label: file, value: w, detail: "severity-weighted score" }))}
              valueLabel="Score"
              format={(v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))}
              labelWidth={150}
              emptyText="No affected files."
            />
          </div>

          {result.change && <ChangePanel change={result.change} findings={result.findings} />}
          {result.artifacts?.localization && <SuspectsPanel found={result.artifacts.localization} />}
          <FindingsTable findings={result.findings} />
          <PipelinePanel result={result} />
        </>
      )}

      {job.status === "done" && !result && (
        <EmptyState title="Result file missing">The review finished but its result could not be loaded.</EmptyState>
      )}
    </div>
  );
}
