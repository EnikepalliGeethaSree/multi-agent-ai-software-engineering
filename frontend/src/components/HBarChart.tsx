import { useId, useRef, useState } from "react";

export interface BarDatum {
  key: string;
  label: string;
  value: number;
  /** CSS color for the mark only (text always uses ink tokens). Defaults to the single-series blue. */
  color?: string;
  /** Extra line in the tooltip, e.g. "severity-weighted score". */
  detail?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  data: BarDatum[];
  valueLabel?: string;
  format?: (v: number) => string;
  emptyText?: string;
  labelWidth?: number;
}

/**
 * Horizontal bar chart (dataviz mark spec): bars <= 20px thick, 4px rounded data-end, square at the
 * baseline, value at the tip, recessive hairline baseline, hover/focus tooltip, table view toggle.
 */
export function HBarChart({
  title,
  subtitle,
  data,
  valueLabel = "Count",
  format = (v) => v.toLocaleString("en-US"),
  emptyText = "Nothing to show.",
  labelWidth = 128,
}: Props) {
  const [showTable, setShowTable] = useState(false);
  const [hover, setHover] = useState<{ d: BarDatum; x: number; y: number } | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const max = Math.max(0, ...data.map((d) => d.value));
  const total = data.reduce((s, d) => s + d.value, 0);
  const nonEmpty = data.some((d) => d.value > 0);

  const place = (d: BarDatum, clientX: number, clientY: number) => {
    const box = boxRef.current?.getBoundingClientRect();
    if (!box) return;
    setHover({ d, x: clientX - box.left, y: clientY - box.top });
  };

  return (
    <section
      className="rounded-xl border border-line bg-surface p-4"
      aria-labelledby={titleId}
    >
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-sm font-semibold text-ink">
            {title}
          </h3>
          {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
        </div>
        {nonEmpty && (
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            className="shrink-0 rounded-md px-2 py-1 text-xs text-ink-2 hover:bg-surface-2"
            aria-pressed={showTable}
          >
            {showTable ? "Chart" : "Table"}
          </button>
        )}
      </header>

      {!nonEmpty ? (
        <p className="py-6 text-center text-sm text-ink-3">{emptyText}</p>
      ) : showTable ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              <th className="py-1.5 font-medium">Item</th>
              <th className="py-1.5 text-right font-medium">{valueLabel}</th>
              <th className="py-1.5 text-right font-medium">Share</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.key} className="border-b border-line last:border-0">
                <td className="py-1.5 text-ink-2">{d.label}</td>
                <td className="tabular py-1.5 text-right text-ink">{format(d.value)}</td>
                <td className="tabular py-1.5 text-right text-ink-3">
                  {total ? `${Math.round((100 * d.value) / total)}%` : "–"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div ref={boxRef} className="relative" onMouseLeave={() => setHover(null)}>
          <ul className="space-y-2" role="list">
            {data.map((d) => {
              const width = max > 0 ? (d.value / max) * 100 : 0;
              return (
                <li
                  key={d.key}
                  className="group flex items-center gap-3 rounded-md outline-none"
                  tabIndex={0}
                  aria-label={`${d.label}: ${format(d.value)}`}
                  onMouseMove={(e) => place(d, e.clientX, e.clientY)}
                  onFocus={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    place(d, r.left + labelWidth + 40, r.top + r.height / 2);
                  }}
                  onBlur={() => setHover(null)}
                >
                  <span
                    className="shrink-0 truncate text-xs text-ink-2"
                    style={{ width: labelWidth }}
                    title={d.label}
                  >
                    {d.label}
                  </span>
                  <span className="relative flex h-6 flex-1 items-center border-l border-[var(--baseline)]">
                    {d.value > 0 && (
                      <span
                        className="bar-fill block h-5 rounded-r-[4px] transition-[width] duration-300 group-hover:opacity-85"
                        style={{
                          width: `${Math.max(width, 1.5)}%`, // tiny values stay visible
                          background: d.color ?? "var(--bar)",
                        }}
                      />
                    )}
                    <span className="tabular ml-2 text-xs font-medium text-ink">
                      {format(d.value)}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
          {hover && (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 min-w-36 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg"
              style={{
                left: Math.min(hover.x + 14, (boxRef.current?.clientWidth ?? 400) - 160),
                top: hover.y + 12,
              }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="inline-block size-2.5 rounded-sm"
                  style={{ background: hover.d.color ?? "var(--bar)" }}
                />
                <span className="font-medium text-ink">{hover.d.label}</span>
              </div>
              <div className="tabular mt-1 text-ink-2">
                {valueLabel}: <span className="text-ink">{format(hover.d.value)}</span>
                {total > 0 && (
                  <span className="text-ink-3"> ({Math.round((100 * hover.d.value) / total)}%)</span>
                )}
              </div>
              {hover.d.detail && <div className="mt-0.5 text-ink-3">{hover.d.detail}</div>}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
