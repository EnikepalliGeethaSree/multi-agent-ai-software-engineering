import type { EvaluationState, EvaluationStatus, EvaluationStatusItem } from "../api/types";
import { Card, Expandable, StatusIcon } from "./ui";

const GROUPS: { state: EvaluationState; title: string; icon: "good" | "warning" | "serious" | "info" }[] = [
  { state: "complete", title: "Completed", icon: "good" },
  { state: "preliminary", title: "Preliminary", icon: "warning" },
  { state: "incomplete", title: "Incomplete", icon: "serious" },
  { state: "pending", title: "Pending Gemini", icon: "info" },
];

function Item({ item }: { item: EvaluationStatusItem }) {
  return (
    <li>
      <p className="font-medium text-ink">{item.name}</p>
      {item.detail && <p className="text-ink-2">{item.detail}</p>}
      {item.command && <code className="mt-0.5 block break-all font-mono text-ink-3">{item.command}</code>}
      {item.run_ids.length > 0 && (
        <p className="mt-0.5 break-all font-mono text-ink-3">{item.run_ids.join(", ")}</p>
      )}
    </li>
  );
}

/** Counts stay on screen, and so does anything that needs care. Full lists open on request. */
export function EvaluationStatusCard({ status }: { status: EvaluationStatus }) {
  const count = (s: EvaluationState) => status.items.filter((i) => i.status === s).length;
  const attention = status.items.filter((i) => i.status === "preliminary" || i.status === "incomplete");
  return (
    <Card title="Evaluation status">
      <ul className="mb-3 flex flex-wrap gap-x-5 gap-y-1">
        {GROUPS.map(({ state, title, icon }) => (
          <li key={state} className="flex items-center gap-1.5 text-sm text-ink">
            <StatusIcon kind={icon} />
            {title}: <span className="tabular font-semibold">{count(state)}</span>
          </li>
        ))}
      </ul>
      <div className="grid gap-4 lg:grid-cols-2">
        <section>
          <h4 className="mb-1.5 text-sm font-semibold text-ink">Preliminary or incomplete</h4>
          {attention.length === 0 ? (
            <p className="text-xs text-ink-3">None.</p>
          ) : (
            <ul className="space-y-1.5 text-xs">
              {attention.map((i) => (
                <li key={i.name}>
                  <span className="font-medium text-ink">{i.name}: </span>
                  <span className="text-ink-2">{i.detail}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h4 className="mb-1.5 text-sm font-semibold text-ink">Best-supported findings</h4>
          {status.findings.length === 0 ? (
            <p className="text-xs text-ink-3">None yet.</p>
          ) : (
            <ul className="ml-4 list-disc space-y-1 text-xs text-ink-2">
              {status.findings.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <div className="mt-3 grid items-start gap-2 lg:grid-cols-3">
        <Expandable title="All experiments" count={status.items.length}>
          <div className="space-y-3">
            {GROUPS.map(({ state, title }) => {
              const items = status.items.filter((i) => i.status === state);
              return (
                items.length > 0 && (
                  <section key={state}>
                    <h5 className="mb-1 font-semibold text-ink">{title}</h5>
                    <ul className="space-y-2">
                      {items.map((item) => (
                        <Item key={item.name} item={item} />
                      ))}
                    </ul>
                  </section>
                )
              );
            })}
          </div>
        </Expandable>
        <Expandable title="Important limitations" count={status.limitations.length}>
          <ul className="ml-4 list-disc space-y-1 text-ink-2">
            {status.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Expandable>
        <Expandable title="Stopped runs not in the tables" count={status.unfinished_runs.length}>
          {status.unfinished_runs.length === 0 ? (
            <p className="text-ink-3">None.</p>
          ) : (
            <ul className="ml-4 list-disc space-y-0.5 break-all font-mono text-ink-2">
              {status.unfinished_runs.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          )}
        </Expandable>
      </div>
    </Card>
  );
}
