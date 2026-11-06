/** Unified diff with added / removed lines tinted. The +/- markers stay in the text for screen readers. */
export function DiffView({ diff, maxLines = 400, label }: { diff: string; maxLines?: number; label?: string }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  const shown = lines.slice(0, maxLines);
  return (
    <pre
      aria-label={label ?? "Code diff"}
      className="overflow-x-auto rounded-lg bg-code py-2 font-mono text-xs leading-relaxed text-ink"
    >
      {shown.map((line, i) => {
        const header = line.startsWith("+++") || line.startsWith("---");
        const style = header
          ? "text-ink-3"
          : line.startsWith("@@")
            ? "text-accent-ink"
            : line.startsWith("+")
              ? "bg-[var(--diff-add)]"
              : line.startsWith("-")
                ? "bg-[var(--diff-del)]"
                : "text-ink-2";
        return (
          <span key={i} className={`block px-3 ${style}`} data-diff={header ? "header" : line[0] ?? " "}>
            {line || " "}
          </span>
        );
      })}
      {lines.length > maxLines && (
        <span className="block px-3 text-ink-3">… {lines.length - maxLines} more lines</span>
      )}
    </pre>
  );
}
