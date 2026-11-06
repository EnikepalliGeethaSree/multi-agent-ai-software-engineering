import { NavLink, Outlet } from "react-router-dom";
import { api } from "../api/client";
import type { LLMStatus } from "../api/types";
import { useApi, useTheme, type Theme } from "../lib/hooks";
import { StatusIcon } from "./ui";

export function LLMStatusPill({ status, error }: { status: LLMStatus | null; error: string | null }) {
  if (error) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-ink-2" title={error}>
        <StatusIcon kind="critical" /> Server offline
      </span>
    );
  }
  if (!status) return <span className="text-xs text-ink-3">Checking LLM…</span>;
  const label = status.ready
    ? `${status.provider} · ${status.model ?? "no model"}`
    : "LLM not configured (static analysis only)";
  return (
    <span
      className="inline-flex max-w-72 items-center gap-1.5 truncate text-xs text-ink-2"
      title={status.error ?? `LLM ready: ${label}`}
    >
      <StatusIcon kind={status.ready ? "good" : "warning"} />
      <span className="truncate">{label}</span>
    </span>
  );
}

function ThemeSelect() {
  const [theme, setTheme] = useTheme();
  return (
    <select
      aria-label="Color theme"
      value={theme}
      onChange={(e) => setTheme(e.target.value as Theme)}
      className="rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink-2"
    >
      <option value="system">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}

const NAV = [
  { to: "/", label: "New review", end: true },
  { to: "/reviews", label: "History", end: false },
  { to: "/performance", label: "Performance", end: false },
  { to: "/evaluation", label: "Evaluation", end: false },
];

export function Layout() {
  const { data: llm, error } = useApi(() => api.llmStatus(), []);
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-surface/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <NavLink to="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-accent text-white" aria-hidden="true">
              <svg viewBox="0 0 32 32" className="size-5">
                <path d="M10 11l-5 5 5 5M22 11l5 5-5 5M18 8l-4 16" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="text-sm font-semibold text-ink">Code Review Agent</span>
          </NavLink>
          <nav aria-label="Main" className="flex max-w-full gap-1 overflow-x-auto">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm ${isActive ? "bg-accent-wash font-medium text-ink" : "text-ink-2 hover:bg-surface-2"}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <LLMStatusPill status={llm} error={error} />
            <ThemeSelect />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet context={{ llm }} />
      </main>
      <footer className="mx-auto max-w-7xl px-4 pb-8 text-xs text-ink-3">
        Multi-Agent AI Assistant for Software Engineering · Code Review Agent · static analysis + RAG + LLM
      </footer>
    </div>
  );
}
