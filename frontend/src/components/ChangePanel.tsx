import { useState } from "react";
import type { ChangeReview, Finding, HunkRisk } from "../api/types";
import { location } from "../lib/format";
import { DiffView } from "./DiffView";
import { Card, Chip, SeverityBadge, StatusIcon } from "./ui";

const LEVEL_ICON: Record<HunkRisk["level"], "critical" | "warning" | "info"> = {
  high: "critical",
  medium: "warning",
  low: "info",
};
const LEVEL_LABEL: Record<HunkRisk["level"], string> = { high: "High risk", medium: "Medium risk", low: "Low risk" };

/** Findings about code OUTSIDE the diff that the change breaks (callers, type contracts). */
export function impactFindings(findings: Finding[]): Finding[] {
  return findings.filter((f) => (f.rule_id ?? "").startsWith("IMPACT-"));
}

function HunkItem({ hunk, rank, defaultOpen }: { hunk: HunkRisk; rank: number; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <li className="rounded-lg border border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 p-3 text-left hover:bg-surface-2"
      >
        <span className="tabular w-5 text-xs text-ink-3">{rank}</span>
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-ink">
          <StatusIcon kind={LEVEL_ICON[hunk.level]} />
          {LEVEL_LABEL[hunk.level]}
        </span>
        <span className="tabular text-xs text-ink-3" title="Estimated chance (%) that a reviewer comments on this hunk (risk model v2, see docs/change-review.md)">
          {hunk.score.toFixed(0)}
        </span>
        <span className="font-mono text-xs text-ink">{location(hunk.file, hunk.start_line, hunk.end_line)}</span>
        {hunk.finding_ids.map((id) => (
          <Chip key={id}>{id}</Chip>
        ))}
      </button>
      {hunk.reasons.length > 0 && (
        <ul className="list-disc space-y-0.5 px-3 pb-2 pl-12 text-xs text-ink-2">
          {hunk.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {open && hunk.patch && (
        <div className="px-3 pb-3">
          <DiffView diff={hunk.patch} label={`Diff of ${hunk.file} lines ${hunk.start_line}-${hunk.end_line}`} />
        </div>
      )}
    </li>
  );
}

export function ChangePanel({ change, findings }: { change: ChangeReview; findings: Finding[] }) {
  const s = change.summary;
  const impact = impactFindings(findings);
  const symbols = s.symbols.filter((x) => x.kind !== "added" || x.callers > 0 || x.signature_changed);
  const [showAll, setShowAll] = useState(false);
  const hunks = showAll ? change.hunks : change.hunks.slice(0, 8);

  return (
    <div className="space-y-4" aria-label="Change review">
      <Card title="What changed">
        <p className="text-sm text-ink">
          <span className="font-mono">{s.base}</span> <span className="text-ink-3">→</span>{" "}
          <span className="font-mono">{s.head}</span>
        </p>
        <p className="tabular mt-1 text-sm text-ink-2">
          {s.files_changed} file{s.files_changed === 1 ? "" : "s"} changed ·{" "}
          <span className="text-[var(--status-good-ink)]">+{s.lines_added}</span>{" "}
          <span className="text-critical">−{s.lines_deleted}</span>
        </p>
        {s.narrative && <p className="mt-3 whitespace-pre-line text-sm leading-relaxed text-ink">{s.narrative}</p>}
        {s.salient && (
          <p className="mt-2 text-xs text-ink-3">
            Central change: <span className="font-mono text-ink-2">{s.salient}</span>
          </p>
        )}
        {s.impacted_files.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
            <StatusIcon kind="warning" />
            <span>Unchanged files that call the changed code:</span>
            {s.impacted_files.map((f) => (
              <Chip key={f}>{f}</Chip>
            ))}
          </div>
        )}
      </Card>

      {impact.length > 0 && (
        <Card title={`Breaks outside the diff (${impact.length})`}>
          <p className="mb-2 text-xs text-ink-3">
            Code this change did not touch but which no longer fits it. A diff-only review cannot see these.
          </p>
          <ul className="space-y-2">
            {impact.map((f) => (
              <li key={f.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                <SeverityBadge severity={f.severity} />
                <span className="font-mono text-xs text-ink-3">{f.id}</span>
                <span className="text-ink">{f.title}</span>
                <span className="font-mono text-xs text-ink-3">{location(f.file, f.start_line, f.end_line)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {symbols.length > 0 && (
        <Card title="Changed functions">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-3">
                  <th className="py-2 pr-3 font-medium">Function</th>
                  <th className="px-3 py-2 font-medium">Change</th>
                  <th className="px-3 py-2 font-medium">Signature</th>
                  <th className="px-3 py-2 text-right font-medium">Call sites</th>
                  <th className="py-2 pl-3 text-right font-medium">Not updated</th>
                </tr>
              </thead>
              <tbody>
                {symbols.map((x) => (
                  <tr key={`${x.file}:${x.qualname}`} className="border-b border-line align-top last:border-0">
                    <td className="py-2 pr-3">
                      <p className="font-mono text-xs text-ink">{x.qualname}</p>
                      <p className="font-mono text-xs text-ink-3">
                        {x.file}
                        {x.line ? `:${x.line}` : ""}
                      </p>
                    </td>
                    <td className="px-3 py-2 text-ink-2">{x.kind}</td>
                    <td className="px-3 py-2 font-mono text-xs text-ink-2">
                      {x.signature_changed ? (
                        <>
                          <span className="block line-through decoration-ink-3">{x.old_signature}</span>
                          <span className="block text-ink">{x.new_signature}</span>
                        </>
                      ) : (
                        <span className="text-ink-3">unchanged</span>
                      )}
                    </td>
                    <td className="tabular px-3 py-2 text-right text-ink-2">{x.callers}</td>
                    <td className="tabular py-2 pl-3 text-right">
                      {x.callers_not_updated > 0 ? (
                        <span className="inline-flex items-center gap-1 font-medium text-ink">
                          <StatusIcon kind="warning" />
                          {x.callers_not_updated}
                        </span>
                      ) : (
                        <span className="text-ink-3">0</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card title="Review these hunks first">
        <p className="mb-3 text-xs text-ink-3">
          Every changed hunk, ranked by the estimated chance that a reviewer would comment on it (callers it breaks,
          security-sensitive code, error handling, signature changes, size). Severe findings are never ranked low.
        </p>
        {change.hunks.length === 0 ? (
          <p className="text-sm text-ink-3">No reviewable Python hunks in this change.</p>
        ) : (
          <ol className="space-y-2">
            {hunks.map((h, i) => (
              <HunkItem key={`${h.file}:${h.start_line}`} hunk={h} rank={i + 1} defaultOpen={i < 3} />
            ))}
          </ol>
        )}
        {change.hunks.length > 8 && (
          <button
            type="button"
            onClick={() => setShowAll(!showAll)}
            className="mt-3 text-sm text-accent-ink underline underline-offset-2"
          >
            {showAll ? "Show the top 8 only" : `Show all ${change.hunks.length} hunks`}
          </button>
        )}
      </Card>
    </div>
  );
}
