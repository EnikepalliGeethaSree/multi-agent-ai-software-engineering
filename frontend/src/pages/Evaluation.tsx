import type { ReactNode } from "react";
import Markdown from "react-markdown";
import { Link, NavLink, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { ComparisonTable, ExperimentRun, MetricDefinition } from "../api/types";
import { ComparisonCard, ConfigFlags, DefinitionsTable } from "../components/ComparisonTable";
import { EvaluationOverview } from "../components/EvaluationOverview";
import { EvaluationStatusCard } from "../components/EvaluationStatus";
import { Card, Chip, EmptyState, Expandable, ErrorBanner, Spinner } from "../components/ui";
import { UNAVAILABLE, dateTime, num } from "../lib/format";
import { useApi } from "../lib/hooks";

const KIND: Record<string, { title: string; about: string; columns: [string, string][]; config?: boolean }> = {
  planted: {
    title: "Planted-issue benchmark",
    about: "17 hand-labelled issues in a fixture repository plus a clean negative-control file.",
    config: true,
    columns: [
      ["recall", "Issue recall"],
      ["recall_llm", "Semantic recall (1 issue)"],
      ["defect_precision", "Defect precision"],
      ["negative_fp", "False positives (clean file)"],
      ["mean_line_error", "Line error"],
    ],
  },
  codereviewer_cls: {
    title: "CodeReviewer: does this change need a comment?",
    about: "Python test split. Raw counts every finding; “Adjusted” excludes rules that cannot be judged from one hunk.",
    config: true,
    columns: [
      ["n", "Samples"],
      ["accuracy", "Raw accuracy"],
      ["precision", "Raw precision"],
      ["f1", "Raw F1"],
      ["roc_auc", "Raw ROC-AUC"],
      ["adj_accuracy", "Adj. accuracy"],
      ["adj_precision", "Adj. precision"],
      ["adj_roc_auc", "Adj. ROC-AUC"],
    ],
  },
  codereviewer_msg: {
    title: "CodeReviewer: review comment generation",
    about: "Similarity of the top finding to the human reviewer's comment: BLEU-4, ROUGE-L, chrF on 0-100 (higher is better); coverage on 0-1.",
    config: true,
    columns: [
      ["n", "Samples"],
      ["bleu4", "BLEU-4"],
      ["rouge_l", "ROUGE-L"],
      ["chrf", "chrF"],
      ["coverage", "Coverage"],
    ],
  },
  hunk_risk: {
    title: "Change review: does “review these hunks first” point at the right hunks?",
    about: "Hunk risk vs. whether a human commented (CodeReviewer cls, Python). Size is the no-analysis baseline.",
    columns: [
      ["n", "Samples"],
      ["base_rate", "Commented (base rate)"],
      ["auc_risk", "ROC-AUC risk"],
      ["auc_size", "ROC-AUC size"],
      ["p10_risk", "Precision@Top10% risk"],
      ["p10_size", "Precision@Top10% size"],
      ["high_commented", "Commented if high"],
      ["low_commented", "Commented if low"],
    ],
  },
  usefulness: {
    title: "Supplementary comment usefulness evaluation (LLM judge, 1-5)",
    about: "Supplementary, not a primary result. Blind, reference-free ratings of the agent's comment and the human reviewer's comment on the same diff; one judge model, small sample, possible judge and length bias.",
    columns: [
      ["n", "Comments"],
      ["agent_relevance", "Agent relevance"],
      ["agent_informativeness", "Agent informativeness"],
      ["human_relevance", "Human relevance"],
      ["human_informativeness", "Human informativeness"],
    ],
  },
  retrieval: {
    title: "RAG retrieval (call-graph relevance)",
    about: "Can retrieval find the functions a piece of code calls?",
    columns: [
      ["n_queries", "Queries"],
      ["hashing_recall@10", "Recall@10"],
      ["hashing_mrr", "MRR"],
      ["random_baseline_recall@10", "Random Recall@10"],
      ["random_baseline_mrr", "Random MRR"],
    ],
  },
  timing: {
    title: "Historical timing benchmark, Groq (median total seconds per review, first input)",
    about: "Fixed inputs, interleaved repeats, concurrency 1. A Static Only, B LLM Only, C Static + LLM, D Static + LLM + RAG.",
    columns: [
      ["repeats", "Repeats"],
      ["inputs", "Inputs"],
      ["static_only_total", "A"],
      ["llm_only_total", "B"],
      ["llm_no_rag_total", "C"],
      ["llm_rag_total", "D"],
    ],
  },
  classifier: {
    title: "Change classifier (repository-disjoint test)",
    about: "Fine-tuned model predicting whether a human commented on a change. A proxy for attention, not for defects.",
    columns: [
      ["n", "Samples"],
      ["accuracy", "Accuracy"],
      ["f1", "F1"],
      ["roc_auc", "ROC-AUC"],
    ],
  },
  runtime: {
    title: "File-size benchmark",
    about: "Review time for small, medium and large files. Rounds and files are what was planned; the run counts show what finished. Details are on the Performance page.",
    columns: [
      ["mode", "Mode"],
      ["repeats", "Rounds planned"],
      ["inputs", "Files planned"],
      ["complete", "Runs complete"],
      ["partial", "Partial"],
      ["failed", "Failed"],
      ["skipped", "Skipped"],
    ],
  },
  gemini_smoke: {
    title: "Gemini smoke test",
    about: "Small live requests on one synthetic file. Rate-limit behaviour is simulated in unit tests.",
    columns: [
      ["live_checks", "Live checks"],
      ["live_passed", "Passed"],
      ["failed", "Failed"],
    ],
  },
  ablation: {
    title: "Ablation groups (configurations A-D run together)",
    about: "Each group runs every configuration on identical inputs; its runs appear in the tables above.",
    columns: [
      ["benchmark", "Benchmark"],
      ["repeats", "Repeats"],
      ["group_id", "Group"],
    ],
  },
};

const MIN_PAIRED_N = 30;
const COUNT_KEYS = new Set([
  "n", "n_queries", "repeats", "inputs", "complete", "partial", "failed", "skipped",
  "live_checks", "live_passed", "negative_fp",
]); // prettier-ignore

/** One cell of the runs table. A run that scored nothing has no metrics, only a sample count. */
function cell(run: ExperimentRun, key: string): { text: string; title?: string } {
  const x = run.headline[key];
  const n = typeof run.headline.n === "number" ? run.headline.n : null;
  if (x === null || x === undefined) return { text: UNAVAILABLE };
  if (n === 0 && key !== "n") return { text: UNAVAILABLE, title: "no samples were evaluated in this run" };
  if (n !== null && n < MIN_PAIRED_N && key.includes("roc_auc")) {
    return { text: UNAVAILABLE, title: `not reported: ${n} samples are too few for ROC-AUC` };
  }
  if (typeof x === "string") return { text: x };
  return { text: COUNT_KEYS.has(key) ? num(x) : x.toFixed(3) };
}

function smallRunLabel(run: ExperimentRun): string | null {
  const n = run.headline.n;
  if (typeof n !== "number" || n >= MIN_PAIRED_N) return null;
  return n === 0 ? "no samples evaluated" : `preliminary, n = ${n}`;
}

function RunTable({ kind, runs }: { kind: string; runs: ExperimentRun[] }) {
  const spec = KIND[kind];
  if (!spec) return null;
  return (
    <Card title={spec.title}>
      <p className="-mt-2 mb-3 text-xs text-ink-3">{spec.about}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th className="py-2 pr-4 font-medium">Run</th>
              <th className="py-2 pr-4 font-medium">Model</th>
              {spec.config && <th className="py-2 pr-4 font-medium">Configuration</th>}
              {spec.columns.map(([, label]) => (
                <th key={label} className="py-2 pr-4 text-right font-medium">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.name} className="border-b border-line last:border-0">
                <td className="py-2 pr-4">
                  <Link to={`/evaluation/${r.name}`} className="text-accent-ink hover:underline">
                    {dateTime(r.started_at)}
                  </Link>
                  {r.errors > 0 && <span className="ml-2 text-xs text-ink-3">({r.errors} failed samples)</span>}
                  {smallRunLabel(r) && (
                    <span className="ml-2 inline-block whitespace-nowrap rounded bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2">{smallRunLabel(r)}</span>
                  )}
                </td>
                <td className="py-2 pr-4 text-ink-2">{r.experiment?.model ?? r.model ?? "static only"}</td>
                {spec.config && (
                  <td className="whitespace-nowrap py-2 pr-4 text-xs text-ink-2">
                    {r.experiment?.configuration ? (
                      <span className="flex flex-col gap-0.5">
                        <span className="text-ink">{r.experiment.configuration.label}</span>
                        <ConfigFlags c={r.experiment.configuration} />
                      </span>
                    ) : (
                      <span title="configuration not recorded for this run">–</span>
                    )}
                  </td>
                )}
                {spec.columns.map(([key]) => {
                  const c = cell(r, key);
                  return (
                    <td key={key} title={c.title} className={`tabular py-2 pr-4 text-right ${c.text === UNAVAILABLE ? "text-xs text-ink-3" : "text-ink"}`}>
                      {c.text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function EvaluationTabs() {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-accent-wash font-medium text-ink" : "text-ink-2 hover:bg-surface-2"}`;
  return (
    <nav aria-label="Evaluation views" className="flex gap-1">
      <NavLink to="/evaluation" end className={tab}>
        Overview
      </NavLink>
      <NavLink to="/evaluation/runs" className={tab}>
        Saved runs
      </NavLink>
    </nav>
  );
}

function Section({ id, number, title, children }: { id: string; number: number; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 space-y-3">
      <h2 className="text-base font-semibold text-ink">
        {number}. {title}
      </h2>
      {children}
    </section>
  );
}

const SECTIONS = [
  { id: "planted", title: "Planted-issue detection", prefix: "1." },
  { id: "classification", title: "CodeReviewer classification", prefix: "2." },
  { id: "comments", title: "Review comment generation", prefix: "3." },
  { id: "retrieval", title: "RAG retrieval", prefix: "4." },
  { id: "risk", title: "Risk ranking", prefix: "5." },
];

export function EvaluationList() {
  const summary = useApi(() => api.evaluationSummary(), []);
  const runs = useApi(() => api.listExperiments(), []);
  const data = summary.data;
  const defs: Record<string, MetricDefinition> = Object.fromEntries((data?.definitions ?? []).map((d) => [d.key, d]));
  const cards = (tables: ComparisonTable[]) => tables.map((t) => <ComparisonCard key={t.id} table={t} definitions={defs} />);
  const tables = data?.tables ?? [];
  const supplementary = tables.filter((t) => t.supplementary);
  const known = tables.filter((t) => !t.supplementary && t.section.match(/^[1-6]/));
  const other = tables.filter((t) => !t.supplementary && !t.section.match(/^[1-6]/));
  const gemini = tables.filter((t) => t.section.startsWith("6a"));
  const staticOnly = tables.filter((t) => t.section.startsWith("6b"));
  const historical = known.filter((t) => t.section.startsWith("6") && !gemini.includes(t) && !staticOnly.includes(t));
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Evaluation</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">
            Results of the Code Review Agent, read from saved benchmark runs. Unmeasured values show as Unavailable.
          </p>
        </div>
        <EvaluationTabs />
      </div>
      {summary.error && <ErrorBanner title="Could not load the evaluation summary" message={summary.error} />}
      {runs.error && <ErrorBanner title="Could not load evaluation runs" message={runs.error} />}
      {summary.loading && !data && (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <Spinner /> Building the evaluation summary…
        </div>
      )}
      {data && (
        <>
          <EvaluationOverview summary={data} runs={runs.data ?? []} />
          {data.status && <EvaluationStatusCard status={data.status} />}
          <nav aria-label="Evaluation sections" className="flex flex-wrap gap-x-1 gap-y-1 text-xs">
            {[{ id: "baseline", title: "Baseline comparison" }, ...SECTIONS, { id: "performance", title: "Performance and efficiency" }, { id: "supplementary", title: "Supplementary" }].map((s) => (
              <a key={s.id} href={`#${s.id}`} className="rounded-md bg-surface-2 px-2 py-1 text-ink-2 hover:text-ink">
                {s.title}
              </a>
            ))}
          </nav>
          <Section id="baseline" number={1} title="Baseline comparison">
            {data.master ? <ComparisonCard table={data.master} definitions={defs} /> : <EmptyState title="No baseline comparison yet" />}
          </Section>
          {SECTIONS.map((s, i) => (
            <Section key={s.id} id={s.id} number={i + 2} title={s.title}>
              {cards(known.filter((t) => t.section.startsWith(s.prefix)))}
            </Section>
          ))}
          <Section id="performance" number={7} title="Performance and efficiency">
            {cards(gemini)}
            {cards(staticOnly)}
            {historical.length > 0 && (
              <Expandable title="Historical timing, not Gemini" count={historical.length}>
                <p className="mb-2 text-ink-2">A different provider. These are not an estimate for Gemini.</p>
                <div className="space-y-3">{cards(historical)}</div>
              </Expandable>
            )}
          </Section>
          {other.length > 0 && <div className="space-y-3">{cards(other)}</div>}
          {supplementary.length > 0 && (
            <section id="supplementary" className="scroll-mt-20 space-y-3">
              <h2 className="text-base font-semibold text-ink">Supplementary evaluation</h2>
              <p className="text-xs text-ink-2">Not a primary result. It has not been checked against human ratings.</p>
              {cards(supplementary)}
            </section>
          )}
          <div className="grid items-start gap-2 md:grid-cols-2">
            <Expandable title="Metric definitions" count={data.definitions.length}>
              <DefinitionsTable definitions={data.definitions} />
            </Expandable>
            <Expandable title="Scope of these results" count={data.scope.length}>
              <ul className="ml-4 list-disc space-y-1 text-ink-2">
                {data.scope.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </Expandable>
          </div>
        </>
      )}
    </div>
  );
}

const RUN_KINDS = ["planted", "codereviewer_cls", "codereviewer_msg", "hunk_risk", "retrieval", "runtime", "gemini_smoke", "timing", "classifier", "ablation", "usefulness"];

/** The complete history: every saved run, grouped, including stopped ones. */
export function EvaluationRuns() {
  const { data, error, loading } = useApi(() => api.listExperiments(), []);
  const summary = useApi(() => api.evaluationSummary(), []);
  const groups = new Map<string, ExperimentRun[]>();
  for (const r of data ?? []) groups.set(r.headline.kind, [...(groups.get(r.headline.kind) ?? []), r]);
  const other = [...groups.keys()].filter((k) => !RUN_KINDS.includes(k));
  const stopped = summary.data?.status?.unfinished_runs ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Saved runs</h1>
          <p className="mt-1 max-w-3xl text-sm text-ink-2">
            Every saved run{data ? ` (${data.length})` : ""}, newest first within each group. Each number comes from that run's{" "}
            <code className="font-mono text-xs">metrics.json</code>.
          </p>
        </div>
        <EvaluationTabs />
      </div>
      {error && <ErrorBanner title="Could not load evaluation runs" message={error} />}
      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <Spinner /> Loading…
        </div>
      )}
      {data && data.length === 0 && <EmptyState title="No evaluation runs saved yet" />}
      {stopped.length > 0 && (
        <Card title={`Stopped runs (${stopped.length})`}>
          <p className="-mt-2 mb-2 text-xs text-ink-3">These never saved metrics, so they have no results to open.</p>
          <ul className="ml-4 list-disc space-y-0.5 break-all font-mono text-xs text-ink-2">
            {stopped.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Card>
      )}
      {RUN_KINDS.map((kind) => groups.has(kind) && <RunTable key={kind} kind={kind} runs={groups.get(kind)!} />)}
      {other.length > 0 && (
        <Card title="Other runs">
          <ul className="space-y-0.5 text-xs">
            {other.flatMap((k) => groups.get(k)!).map((r) => (
              <li key={r.name}>
                <Link to={`/evaluation/${r.name}`} className="break-all font-mono text-accent-ink hover:underline">
                  {r.name}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export function EvaluationDetail() {
  const { name = "" } = useParams();
  const { data, error, loading } = useApi(() => api.getExperiment(name), [name]);
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <Spinner /> Loading…
      </div>
    );
  }
  if (error || !data) return <ErrorBanner title="Run not found" message={error ?? name} />;
  const meta = data.meta as Record<string, unknown>;
  const exp = (meta.experiment ?? null) as Record<string, unknown> | null;
  return (
    <div className="space-y-4">
      <p className="text-xs text-ink-3">
        <Link to="/evaluation" className="hover:underline">
          Evaluation
        </Link>{" "}
        /{" "}
        <Link to="/evaluation/runs" className="hover:underline">
          Saved runs
        </Link>{" "}
        / {data.name}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {typeof meta.llm_model === "string" && <Chip>{meta.llm_model}</Chip>}
        {typeof meta.git_commit === "string" && <Chip>commit {meta.git_commit.slice(0, 12)}</Chip>}
        {typeof meta.started_at === "string" && <Chip>{dateTime(meta.started_at)}</Chip>}
        {typeof meta.errors === "number" && <Chip>{meta.errors} failed samples</Chip>}
      </div>
      {exp && <ExperimentCard exp={exp} />}
      <Card>
        <div className="markdown text-sm text-ink [&_code]:font-mono [&_h1]:mb-3 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_p]:my-2 [&_p]:text-ink-2 [&_table]:my-3 [&_table]:w-full [&_td]:border-b [&_td]:border-line [&_td]:px-2 [&_td]:py-1.5 [&_td]:tabular-nums [&_th]:border-b [&_th]:border-line [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-xs [&_th]:font-medium [&_th]:text-ink-3">
          <Markdown remarkPlugins={[remarkGfm]}>{data.summary_md || "_No summary saved for this run._"}</Markdown>
        </div>
      </Card>
      <details className="rounded-xl border border-line bg-surface p-4 text-sm">
        <summary className="cursor-pointer text-ink-2">Raw metrics.json</summary>
        <pre className="mt-3 max-h-[480px] overflow-auto rounded-lg bg-code p-3 font-mono text-xs text-ink-2">
          {JSON.stringify(data.metrics, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function ExperimentCard({ exp }: { exp: Record<string, unknown> }) {
  const c = exp.configuration as
    | { label: string; static: boolean; llm: boolean; rag: boolean; key: string; letter: string | null; mode: string }
    | undefined;
  const llm = exp.llm as Record<string, unknown> | null;
  const rag = exp.rag as Record<string, unknown> | null;
  const items: [string, unknown][] = [
    ["Benchmark", exp.benchmark],
    ["Dataset", exp.dataset],
    ["Split", exp.split],
    ["Samples", exp.sample_count],
    ["Evaluated", exp.n_evaluated],
    ["Failed", exp.n_failed],
    ["Sampling seed", exp.sampling_seed],
    ["Model", llm ? `${llm.provider} / ${llm.model}` : "no LLM"],
    ["Temperature", llm?.temperature],
    ["LLM seed", llm?.seed],
    ["Confidence threshold", exp.confidence_threshold],
    ["RAG top-k", rag ? `${rag.top_k} code + ${rag.guideline_k} guideline chunks (${rag.embedding_model})` : "RAG off"],
    ["Repeat", exp.repeat ? `${exp.repeat} of ${exp.repeats}` : null],
    ["Ablation group", exp.group_id],
  ];
  return (
    <Card title="Experiment configuration">
      {c && (
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium text-ink">
            {c.letter ? `${c.letter}. ` : ""}
            {c.label}
          </span>
          <ConfigFlags c={{ ...c, letter: c.letter ?? null }} />
        </div>
      )}
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        {items
          .filter(([, v]) => v !== null && v !== undefined && v !== "")
          .map(([k, v]) => (
            <div key={k} className="flex gap-2">
              <dt className="shrink-0 text-ink-3">{k}:</dt>
              <dd className="text-ink">{String(v)}</dd>
            </div>
          ))}
      </dl>
    </Card>
  );
}
