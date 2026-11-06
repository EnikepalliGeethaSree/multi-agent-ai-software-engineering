import type { ReactNode } from "react";
import { compact } from "../lib/format";

/** Stat tile contract: label (sentence case) · value (auto-compact) · optional hint. */
export function StatTile({ label, value, hint }: { label: string; value: number | string; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">
        {typeof value === "number" ? compact(value) : value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

