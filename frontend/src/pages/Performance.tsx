import { useState } from "react";
import { useOutletContext, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { BenchmarkRow, LLMStatus, PerformanceRecord } from "../api/types";
import { BeforeAfter, BenchmarkTable, ProviderCard, ReviewPerformance } from "../components/PerformancePanels";
import { ScatterChart, type ScatterPoint } from "../components/ScatterChart";
import { Card, EmptyState, ErrorBanner, Spinner } from "../components/ui";
import { dateTime } from "../lib/format";
import { useApi } from "../lib/hooks";

type Measured = Pick<PerformanceRecord, "file_name" | "file_size_kb" | "lines_of_code" | "input_tokens" | "total_sec"> & {
  key: string;
  source: string;
};

/** Points for one x measure; runs missing a value are counted and left out, never drawn at 0. */
export function pointsFor(runs: Measured[], x: (r: Measured) => number | null | undefined) {
  const points: ScatterPoint[] = [];
  let excluded = 0;
  for (const r of runs) {
    const xv = x(r);
    if (typeof xv === "number" && typeof r.total_sec === "number") {
      points.push({ key: r.key, x: xv, y: r.total_sec, label: r.file_name, detail: r.source });
    } else excluded += 1;
  }
  return { points, excluded };
}

function fromReviews(reviews: PerformanceRecord[]): Measured[] {
  return reviews
    .filter((r) => r.status === "complete")
    .map((r) => ({ ...r, key: r.review_id, source: `review, ${r.run_type} run` }));
}

function fromBenchmark(rows: BenchmarkRow[], name: string): Measured[] {
  return rows
    .filter((r) => r.status === "complete" && r.run_type === "cold")
    .map((r, i) => ({ ...r, key: `${name}-${i}`, source: `benchmark round ${r.repeat}, ${r.category}` }));
}

export default function Performance() {
  const { llm } = useOutletContext<{ llm: LLMStatus | null }>();
  const [params, setParams] = useSearchParams();
  const reviews = useApi(() => api.performanceReviews(), []);
  const benchmarks = useApi(() => api.benchmarks(), []);
  const comparison = useApi(() => api.beforeAfter(), []);
  const [benchmarkName, setBenchmarkName] = useState<string | null>(null);

  const selectedBenchmark = benchmarks.data?.find((b) => b.name === benchmarkName) ?? benchmarks.data?.[0] ?? null;
  const detail = useApi(
    () => (selectedBenchmark ? api.benchmark(selectedBenchmark.name) : Promise.resolve(null)),
    [selectedBenchmark?.name],
  );
  const reviewId = params.get("review") ?? reviews.data?.[0]?.review_id ?? null;
  const review = useApi(() => (reviewId ? api.performanceReview(reviewId) : Promise.resolve(null)), [reviewId]);

  const runs = [
    ...fromReviews(reviews.data ?? []),
    ...(selectedBenchmark && detail.data ? fromBenchmark(detail.data.runs, selectedBenchmark.name) : []),
  ];
  const bySize = pointsFor(runs, (r) => r.file_size_kb);
  const byLines = pointsFor(runs, (r) => r.lines_of_code);
  const byTokens = pointsFor(runs, (r) => r.input_tokens);
  const error = reviews.error ?? benchmarks.error;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-ink">Performance analysis</h1>
        <p className="mt-1 text-sm text-ink-2">
          Measured from saved reviews and benchmark runs. A value that was not measured shows as “Unavailable”, not zero.
        </p>
      </div>
      {error && <ErrorBanner title="Could not load performance data" message={error} />}
      <ProviderCard llm={llm} />

      <h2 className="pt-2 text-base font-semibold text-ink">Review breakdown</h2>
      {reviews.loading && !reviews.data ? (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <Spinner /> Loading…
        </div>
      ) : reviews.data && reviews.data.length === 0 ? (
        <EmptyState title="No reviews yet">Run a review and its timing appears here.</EmptyState>
      ) : (
        <>
          <label className="block text-xs text-ink-3">
            Review{" "}
            <select
              value={reviewId ?? ""}
              onChange={(e) => setParams({ review: e.target.value })}
              className="ml-1 max-w-full rounded-lg border border-line bg-surface px-2 py-1 text-sm text-ink"
            >
              {(reviews.data ?? []).map((r) => (
                <option key={r.review_id} value={r.review_id}>
                  {r.file_name} · {dateTime(r.created_at)}
                </option>
              ))}
            </select>
          </label>
          {review.error && <ErrorBanner title="Could not load this review" message={review.error} />}
          {review.data && <ReviewPerformance record={review.data.record} />}
        </>
      )}

      <h2 className="pt-2 text-base font-semibold text-ink">File size and execution time</h2>
      <p className="-mt-2 text-xs text-ink-3">Complete reviews, plus the cold runs of the selected benchmark.</p>
      <div className="grid gap-3 lg:grid-cols-2">
        <ScatterChart title="File size vs execution time" xLabel="File size (KB)" yLabel="Total seconds" {...bySize} />
        <ScatterChart title="Lines of code vs execution time" xLabel="Lines of code" yLabel="Total seconds" {...byLines} />
        <ScatterChart
          title="Input tokens vs execution time"
          xLabel="Input tokens"
          yLabel="Total seconds"
          emptyText="No run has token counts yet: they need a real LLM run."
          {...byTokens}
        />
      </div>

      <h2 className="pt-2 text-base font-semibold text-ink">Benchmark history</h2>
      {benchmarks.data && benchmarks.data.length === 0 ? (
        <EmptyState title="No benchmark runs yet">
          Run <code className="font-mono text-xs">python -m marl_agents.evaluation.benchmark_runtime</code>
        </EmptyState>
      ) : (
        selectedBenchmark && (
          <Card
            title={dateTime(selectedBenchmark.started_at)}
            action={
              <select
                aria-label="Benchmark run"
                value={selectedBenchmark.name}
                onChange={(e) => setBenchmarkName(e.target.value)}
                className="max-w-64 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink-2"
              >
                {benchmarks.data!.map((b) => (
                  <option key={b.name} value={b.name}>
                    {dateTime(b.started_at)} · {b.mode} · {b.conditions.model ?? "no LLM"}
                  </option>
                ))}
              </select>
            }
          >
            <BenchmarkTable run={selectedBenchmark} />
          </Card>
        )
      )}

      <h2 className="pt-2 text-base font-semibold text-ink">Original vs improved</h2>
      {comparison.error && <ErrorBanner title="Could not load the comparison" message={comparison.error} />}
      {comparison.data && <BeforeAfter table={comparison.data} />}
    </div>
  );
}
