import type { Category, Severity } from "../api/types";

export function compact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return n.toLocaleString("en-US");
}

export function pct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

export function num(x: unknown, digits = 3): string {
  if (typeof x !== "number" || Number.isNaN(x)) return "–";
  return Number.isInteger(x) ? x.toLocaleString("en-US") : x.toFixed(digits);
}

export const UNAVAILABLE = "Unavailable";

/** A measurement with its unit. Missing is never shown as 0: zero means measured to be zero. */
export function value(x: number | null | undefined, unit = "", digits = 2): string {
  if (x === null || x === undefined || Number.isNaN(x)) return UNAVAILABLE;
  return `${x.toFixed(digits)}${unit}`;
}

export function duration(startIso: string | null, endIso: string | null, now = Date.now()): string {
  if (!startIso) return "–";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : now;
  const s = Math.max(0, Math.round((end - start) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(s % 60).padStart(2, "0")}s`;
}

export function dateTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export const CATEGORY_LABEL: Record<Category, string> = {
  bug: "Bug",
  security: "Security",
  quality: "Code quality",
  maintainability: "Maintainability",
  error_handling: "Error handling",
  edge_case: "Edge case",
  performance: "Performance",
  testing: "Testing",
  standards: "Standards",
  documentation: "Documentation",
};

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

export const SOURCE_LABEL: Record<string, string> = {
  llm: "LLM",
  ruff: "Ruff",
  radon: "Radon",
  ast: "AST checks",
  mypy: "mypy",
};

export const MODE_LABEL: Record<string, string> = {
  full: "Static + LLM",
  static_only: "Static only",
  llm_only: "LLM only",
};

export function location(file: string, start: number, end: number): string {
  return end > start ? `${file}:${start}-${end}` : `${file}:${start}`;
}

export const SOURCE_TYPE_LABEL: Record<string, string> = {
  zip: "Repository archive",
  file: "Python file",
  snippet: "Pasted code",
  change: "Code change",
};
