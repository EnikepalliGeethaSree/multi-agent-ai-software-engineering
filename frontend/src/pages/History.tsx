import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorBanner, JobStatusBadge, Spinner } from "../components/ui";
import { MODE_LABEL, SOURCE_TYPE_LABEL, dateTime, duration } from "../lib/format";
import { useApi } from "../lib/hooks";

export default function History() {
  const navigate = useNavigate();
  const { data, error, loading } = useApi(() => api.listReviews(), [], {
    pollMs: 2000,
    shouldPoll: (jobs) => jobs.some((j) => j.status === "queued" || j.status === "running"),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">Review history</h1>
          <p className="mt-1 text-sm text-ink-2">Every review is saved with its reports until you delete it.</p>
        </div>
        <Link to="/" className="rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:brightness-110">
          New review
        </Link>
      </div>

      {error && <ErrorBanner title="Could not load reviews" message={error} />}
      {loading && !data && (
        <div className="flex items-center gap-2 text-sm text-ink-2">
          <Spinner /> Loading…
        </div>
      )}
      {data && data.length === 0 && (
        <EmptyState title="No reviews yet">
          <Link to="/" className="text-accent-ink underline">
            Start your first review
          </Link>
        </EmptyState>
      )}
      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="px-4 py-2.5 font-medium">Input</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Mode</th>
                <th className="px-4 py-2.5 text-right font-medium">Findings</th>
                <th className="px-4 py-2.5 text-right font-medium">Critical / high</th>
                <th className="px-4 py-2.5 font-medium">Started</th>
                <th className="px-4 py-2.5 text-right font-medium">Duration</th>
              </tr>
            </thead>
            <tbody>
              {data.map((j) => (
                <tr
                  key={j.id}
                  tabIndex={0}
                  onClick={() => navigate(`/reviews/${j.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && navigate(`/reviews/${j.id}`)}
                  className="cursor-pointer border-b border-line last:border-0 hover:bg-surface-2"
                >
                  <td className="px-4 py-2.5">
                    <p className="font-medium text-ink">{j.name}</p>
                    <p className="text-xs text-ink-3">
                      {SOURCE_TYPE_LABEL[j.source_type]}
                    </p>
                  </td>
                  <td className="px-4 py-2.5">
                    <JobStatusBadge status={j.status} />
                    {j.status === "running" && j.progress[0] && (
                      <p className="mt-1 max-w-56 truncate text-xs text-ink-3">{j.progress[0].slice(9)}</p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-ink-2">
                    {MODE_LABEL[j.options.mode]}
                    {j.model && j.options.mode !== "static_only" && <p className="text-xs text-ink-3">{j.model}</p>}
                  </td>
                  <td className="tabular px-4 py-2.5 text-right text-ink">{j.summary?.total_findings ?? "–"}</td>
                  <td className="tabular px-4 py-2.5 text-right text-ink-2">
                    {j.summary ? `${j.summary.by_severity.critical ?? 0} / ${j.summary.by_severity.high ?? 0}` : "–"}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-ink-2">{dateTime(j.created_at)}</td>
                  <td className="tabular px-4 py-2.5 text-right text-ink-2">
                    {j.finished_at ? duration(j.started_at, j.finished_at) : "–"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
