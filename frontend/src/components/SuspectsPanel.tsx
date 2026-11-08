import type { LocalizationResult } from "../api/types";
import { Card } from "./ui";

/** Where a failing test most likely fails. Ranked by reading the code; nothing was run. */
export function SuspectsPanel({ found }: { found: LocalizationResult }) {
  const top = found.suspects.slice(0, 10);
  return (
    <Card title="Most likely locations of the failure">
      {found.hypothesis && <p className="mb-3 text-sm leading-relaxed text-ink-2">{found.hypothesis}</p>}
      {found.llm_failed && <p className="mb-3 text-sm text-ink-2">The LLM could not rank these, so this is the static order.</p>}
      {top.length === 0 ? (
        <p className="text-sm text-ink-3">No function in this repository matches what the test uses.</p>
      ) : (
        <ol className="space-y-2">
          {top.map((s) => (
            <li key={`${s.file}:${s.symbol}`} className="text-sm">
              <span className="tabular mr-2 text-ink-3">{s.rank}</span>
              <span className="font-mono text-ink">{s.symbol}</span>
              <span className="ml-2 font-mono text-xs text-ink-3">
                {s.file}:{s.start_line}
              </span>
              {s.reasons[0] && <p className="ml-5 text-xs text-ink-3">{s.reasons[0]}</p>}
            </li>
          ))}
        </ol>
      )}
      <p className="mt-3 text-xs text-ink-3">
        Ranked by {found.ranked_by === "llm" ? "the LLM" : "static signals"} from {found.candidates_considered} candidates.
      </p>
    </Card>
  );
}
