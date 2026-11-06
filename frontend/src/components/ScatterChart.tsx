import { useId, useMemo, useState } from "react";

export interface ScatterPoint {
  key: string;
  x: number;
  y: number;
  label: string;
  detail?: string;
}

interface Props {
  title: string;
  subtitle?: string;
  xLabel: string;
  yLabel: string;
  points: ScatterPoint[];
  /** Runs left out because a value was not measured. Stated, never plotted as zero. */
  excluded?: number;
  emptyText?: string;
}

const W = 520;
const H = 260;
const PAD = { left: 52, right: 16, top: 12, bottom: 40 };
const HIT_RADIUS = 12; // 24px target: the 8px dot alone is too small to land on

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const rough = max / count;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? rough;
  const out: number[] = [];
  for (let v = 0; v <= max + step * 0.999; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

const tick = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 2 });

/** One-series scatter: 8px dots with a 2px surface ring, recessive grid, hover and table view. */
export function ScatterChart({ title, subtitle, xLabel, yLabel, points, excluded = 0, emptyText }: Props) {
  const [showTable, setShowTable] = useState(false);
  const [hover, setHover] = useState<ScatterPoint | null>(null);
  const titleId = useId();
  const { xTicks, yTicks, sx, sy } = useMemo(() => {
    const xTicks = niceTicks(Math.max(0, ...points.map((p) => p.x)));
    const yTicks = niceTicks(Math.max(0, ...points.map((p) => p.y)));
    const xMax = xTicks[xTicks.length - 1] || 1;
    const yMax = yTicks[yTicks.length - 1] || 1;
    return {
      xTicks,
      yTicks,
      sx: (v: number) => PAD.left + (v / xMax) * (W - PAD.left - PAD.right),
      sy: (v: number) => H - PAD.bottom - (v / yMax) * (H - PAD.top - PAD.bottom),
    };
  }, [points]);

  return (
    <section className="rounded-xl border border-line bg-surface p-4" aria-labelledby={titleId}>
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-sm font-semibold text-ink">
            {title}
          </h3>
          {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
        </div>
        {points.length > 0 && (
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

      {points.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-3">{emptyText ?? "No measured runs yet."}</p>
      ) : showTable ? (
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs text-ink-3">
                <th className="py-1.5 font-medium">Run</th>
                <th className="py-1.5 text-right font-medium">{xLabel}</th>
                <th className="py-1.5 text-right font-medium">{yLabel}</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.key} className="border-b border-line last:border-0">
                  <td className="py-1.5 text-ink-2">{p.label}</td>
                  <td className="tabular py-1.5 text-right text-ink">{tick(p.x)}</td>
                  <td className="tabular py-1.5 text-right text-ink">{tick(p.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="relative">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${title}: ${points.length} runs`}>
            {yTicks.map((v) => (
              <g key={`y${v}`}>
                <line x1={PAD.left} x2={W - PAD.right} y1={sy(v)} y2={sy(v)} stroke="var(--grid)" strokeWidth={1} />
                <text x={PAD.left - 6} y={sy(v) + 3} textAnchor="end" fontSize={10} fill="var(--ink-3)">
                  {tick(v)}
                </text>
              </g>
            ))}
            {xTicks.map((v) => (
              <text key={`x${v}`} x={sx(v)} y={H - PAD.bottom + 14} textAnchor="middle" fontSize={10} fill="var(--ink-3)">
                {tick(v)}
              </text>
            ))}
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={H - PAD.bottom}
              y2={H - PAD.bottom}
              stroke="var(--baseline)"
              strokeWidth={1}
            />
            <text x={(PAD.left + W - PAD.right) / 2} y={H - 6} textAnchor="middle" fontSize={11} fill="var(--ink-2)">
              {xLabel}
            </text>
            <text
              transform={`translate(12 ${(PAD.top + H - PAD.bottom) / 2}) rotate(-90)`}
              textAnchor="middle"
              fontSize={11}
              fill="var(--ink-2)"
            >
              {yLabel}
            </text>
            {points.map((p) => (
              <circle key={p.key} cx={sx(p.x)} cy={sy(p.y)} r={4} fill="var(--bar)" stroke="var(--surface-1)" strokeWidth={2} />
            ))}
            {points.map((p) => (
              <circle
                key={`hit-${p.key}`}
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={HIT_RADIUS}
                fill="transparent"
                tabIndex={0}
                aria-label={`${p.label}: ${xLabel} ${tick(p.x)}, ${yLabel} ${tick(p.y)}`}
                onMouseEnter={() => setHover(p)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(p)}
                onBlur={() => setHover(null)}
              />
            ))}
          </svg>
          {hover && (
            <div
              role="tooltip"
              className="pointer-events-none absolute z-10 min-w-36 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg"
              style={{
                left: `${Math.min((sx(hover.x) / W) * 100, 62)}%`,
                top: `${Math.max((sy(hover.y) / H) * 100 - 26, 0)}%`,
              }}
            >
              <div className="font-medium text-ink">{hover.label}</div>
              <div className="tabular mt-1 text-ink-2">
                {xLabel}: <span className="text-ink">{tick(hover.x)}</span>
              </div>
              <div className="tabular text-ink-2">
                {yLabel}: <span className="text-ink">{tick(hover.y)}</span>
              </div>
              {hover.detail && <div className="mt-0.5 text-ink-3">{hover.detail}</div>}
            </div>
          )}
        </div>
      )}
      {excluded > 0 && (
        <p className="mt-2 text-xs text-ink-3">
          {excluded} run{excluded === 1 ? "" : "s"} not shown: the value was not measured.
        </p>
      )}
    </section>
  );
}
