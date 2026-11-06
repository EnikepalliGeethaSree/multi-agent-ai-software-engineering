import Markdown from "react-markdown";
import { Link, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { api } from "../api/client";
import type { ComparisonTable, ExperimentRun, MetricDefinition } from "../api/types";
import { ComparisonCard, ConfigFlags, DefinitionsTable } from "../components/ComparisonTable";
import { Card, Chip, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { dateTime, num } from "../lib/format";
import { useApi } from "../lib/hooks";

const KIND: Record<string, { title: string; about: string; columns: [string, string][]; config?: boolean }> = {
  planted: {
    title: "Planted-issue benchmark",
    about: "17 hand-labelled issues in a fixture repository plus a clean negative-control file.",
    config: true,
    columns: [
      ["recall", "Recall"],
      ["recall_llm", "Recall (LLM-only issues)"],
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
    title: "Timing benchmark (median total seconds per review, first input)",
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
    about: "Review time for small, medium and large files. Details are on the Performance page.",
    columns: [
      ["mode", "Mode"],
      ["repeats", "Rounds"],
      ["inputs", "Files"],
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

function cell(x: unknown): string {
  return typeof x === "string" ? x : num(x);
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
                </td>
                <td className="py-2 pr-4 text-ink-2">{r.experiment?.model ?? r.model ?? "static only"}</td>
                {spec.config && (
                  <td className="py-2 pr-4 text-xs text-ink-2">
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
                {spec.columns.map(([key]) => (
                  <td key={key} className="tabular py-2 pr-4 text-right text-ink">
                    {cell(r.headline[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function BaselineComparison() {
  const { data, error, loading } = useApi(() => api.evaluationSummary(), []);
  if (error) return <ErrorBanner title="Could not load the baseline comparison" message={error} />;
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm text-ink-2">
        <Spinner /> Building the baseline comparison…
      </div>
    );
  }
  if (!data) return null;
  const defs: Record<string, MetricDefinition> = Object.fromEntries(data.definitions.map((d) => [d.key, d]));
  const sections = new Map<string, ComparisonTable[]>();
  for (const t of data.tables) sections.set(t.section, [...(sections.get(t.section) ?? []), t]);
  return (
    <div className="space-y-4">
      <Card>
        <ul className="ml-4 list-disc space-y-1 text-xs text-ink-2">
          {data.scope.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </Card>
      {data.master && <ComparisonCard table={data.master} definitions={defs} />}
      {[...sections.entries()].map(([section, tables]) => (
        <section key={section} className="space-y-3">
          <h2 className="pt-2 text-base font-semibold text-ink">{section}</h2>
          {tables.map((t) => (
            <ComparisonCard key={t.id} table={t} definitions={defs} />
          ))}
        </section>
      ))}
      <details className="rounded-xl border border-line bg-surface p-4 text-sm">
        <summary className="cursor-pointer font-medium text-ink">Metric definitions (formula, scale, direction)</summary>
        <div className="mt-3">
          <DefinitionsTable definitions={data.definitions} />
        </div>
      </details>
    </div>
  );
}

export function EvaluationList() {
  const { data, error, loading } = useApi(() => api.listExperiments(), []);
  const groups = new Map<string, ExperimentRun[]>();
  for (const r of data ?? []) groups.set(r.headline.kind, [...(groups.get(r.headline.kind) ?? []), r]);
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">Evaluation</h1>
        <p className="mt-1 text-sm text-ink-2">
          Results of saved benchmark runs (<code className="font-mono text-xs">experiments/results</code>). Every number
          comes from a run's <code className="font-mono text-xs">metrics.json</code>; run more with{" "}
          <code className="font-mono text-xs">python -m marl_agents.cli eval …</code>
        </p>
      </div>
      {error && <ErrorBanner title="Could not load evaluation runs" message={error} />}
      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <Spinner /> Loading…
        </div>
      )}
      <h2 className="text-base font-semibold text-ink">Baseline comparison</h2>
      <BaselineComparison />
      <h2 className="pt-4 text-base font-semibold text-ink">All saved runs</h2>
      {data && data.length === 0 && <EmptyState title="No evaluation runs saved yet" />}
      {["planted", "codereviewer_cls", "codereviewer_msg", "hunk_risk", "retrieval", "timing", "runtime", "classifier", "ablation", "usefulness"].map(
        (kind) => groups.has(kind) && <RunTable key={kind} kind={kind} runs={groups.get(kind)!} />,
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
