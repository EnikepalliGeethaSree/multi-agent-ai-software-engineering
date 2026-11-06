import type { ComparisonTable, EvaluationSummary, ExperimentRun } from "../api/types";
import { UNAVAILABLE, num } from "../lib/format";
import { StatTile } from "./StatTile";

function find(tables: ComparisonTable[], id: string): ComparisonTable | undefined {
  return tables.find((t) => t.id === id);
}

function metric(table: ComparisonTable | undefined, label: string, key: string): number | null {
  const row = table?.rows.find((r) => r.label.startsWith(label) && r.status === "ok");
  return row?.values[key] ?? null;
}

function shown(x: number | null): string {
  return x === null ? UNAVAILABLE : num(x);
}

/**
 * Headline results, read from the same tables and runs as the sections below. Each tile states the
 * limit that applies to it. Paired comparisons below 30 samples never appear here.
 */
export function EvaluationOverview({ summary, runs }: { summary: EvaluationSummary; runs: ExperimentRun[] }) {
  const { tables } = summary;
  const planted = find(tables, "planted");
  const full = planted?.rows.find((r) => r.label === "Static + LLM + RAG" && r.status === "ok");
  const found = full?.values.issues_found;
  const varies = planted?.observations.some((o) => o.includes("varies between")) ?? false;
  const classifier = [...runs].reverse().find((r) => r.headline.kind === "classifier" && typeof r.headline.roc_auc === "number");
  const static_ = find(tables, "codereviewer_cls_full");
  const retrieval = find(tables, "retrieval");
  const risk = find(tables, "risk");
  const gemini = tables.find((t) => t.section.startsWith("6a"));
  const complete = gemini?.rows.reduce((sum, r) => sum + (r.values.complete ?? 0), 0);
  const planned = gemini?.rows.reduce((sum, r) => sum + r.n_runs, 0);
  const finished = complete !== undefined && complete === planned;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <StatTile
        label="Planted issues found"
        value={typeof found === "number" ? `${found} of ${full?.n ?? 17}` : UNAVAILABLE}
        hint={`Small benchmark, Groq${varies ? ". Varies between runs" : ""}`}
      />
      <StatTile
        label="Classifier ROC-AUC"
        value={classifier ? num(classifier.headline.roc_auc) : UNAVAILABLE}
        hint={classifier ? `Held-out test, n = ${num(classifier.headline.n)}. Proxy label` : undefined}
      />
      <StatTile
        label="Static analysis ROC-AUC"
        value={shown(metric(static_, "Static Only", "adj_roc_auc"))}
        hint={`Adjusted rules, n = ${num(static_?.rows[0]?.n)}`}
      />
      <StatTile
        label="Retrieval Recall@10"
        value={shown(metric(retrieval, "RAG", "recall_at_10"))}
        hint={`Random: ${shown(metric(retrieval, "Random", "recall_at_10"))}. Not review accuracy`}
      />
      <StatTile
        label="Risk model v2 ROC-AUC"
        value={shown(metric(risk, "Risk model v2", "roc_auc"))}
        hint={`Size only: ${shown(metric(risk, "Size only", "roc_auc"))}. ${risk?.badges?.includes("Baseline not beaten") ? "Baseline not beaten" : "See section 6"}`}
      />
      <StatTile
        label="Gemini benchmark runs"
        value={gemini ? `${complete} of ${planned}` : UNAVAILABLE}
        hint={finished ? "Complete" : gemini ? "Incomplete, preliminary" : "No run yet"}
      />
    </div>
  );
}
