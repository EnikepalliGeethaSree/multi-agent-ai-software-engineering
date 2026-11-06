import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { JobStatus, Severity } from "../api/types";
import { SEVERITY_LABEL } from "../lib/format";

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface p-4 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h3 className="text-sm font-semibold text-ink">{title}</h3>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-white hover:brightness-110 disabled:opacity-50",
  secondary: "border border-line bg-surface text-ink hover:bg-surface-2 disabled:opacity-50",
  ghost: "text-ink-2 hover:bg-surface-2 disabled:opacity-50",
  danger: "border border-line bg-surface text-critical hover:bg-surface-2 disabled:opacity-50",
};

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    />
  );
}

export function Spinner({ className = "size-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ErrorBanner({ title = "Something went wrong", message }: { title?: string; message: string }) {
  return (
    <div role="alert" className="flex gap-3 rounded-xl border border-line bg-surface p-4">
      <StatusIcon kind="critical" />
      <div className="min-w-0">
        <p className="text-sm font-semibold text-ink">{title}</p>
        <p className="mt-1 break-words text-sm text-ink-2">{message}</p>
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface p-10 text-center">
      <p className="text-sm font-semibold text-ink">{title}</p>
      {children && <div className="mt-2 text-sm text-ink-2">{children}</div>}
    </div>
  );
}

/** Status icons carry the reserved status colors; the text beside them stays in ink. */
export function StatusIcon({ kind }: { kind: "critical" | "serious" | "warning" | "good" | "info" }) {
  const color = {
    critical: "var(--status-critical)",
    serious: "var(--status-serious)",
    warning: "var(--status-warning)",
    good: "var(--status-good)",
    info: "var(--ink-3)",
  }[kind];
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0" aria-hidden="true">
      {kind === "critical" && (
        <path d="M5 1h6l4 4v6l-4 4H5l-4-4V5z" fill={color} />
      )}
      {kind === "serious" && <path d="M8 1l7.5 13.5H.5z" fill={color} />}
      {kind === "warning" && <circle cx="8" cy="8" r="7" fill={color} />}
      {kind === "good" && <circle cx="8" cy="8" r="7" fill={color} />}
      {kind === "info" && <circle cx="8" cy="8" r="6.25" fill="none" stroke={color} strokeWidth="1.5" />}
      {kind === "good" ? (
        <path d="M4.5 8.2l2.2 2.2 4.8-4.8" stroke="white" strokeWidth="1.8" fill="none" strokeLinecap="round" />
      ) : kind === "info" ? (
        <path d="M8 7v4.2M8 4.6v.1" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
      ) : (
        <path d="M8 4.4v4.6M8 11.3v.1" stroke={kind === "warning" ? "#0b0b0b" : "white"} strokeWidth="1.8" strokeLinecap="round" />
      )}
    </svg>
  );
}

const SEVERITY_ICON: Record<Severity, "critical" | "serious" | "warning" | "info"> = {
  critical: "critical",
  high: "serious",
  medium: "warning",
  low: "info",
  info: "info",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-ink">
      <StatusIcon kind={SEVERITY_ICON[severity]} />
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

const JOB_STATUS: Record<JobStatus, { label: string; icon: "good" | "critical" | "info" }> = {
  queued: { label: "Queued", icon: "info" },
  running: { label: "Running", icon: "info" },
  done: { label: "Done", icon: "good" },
  failed: { label: "Failed", icon: "critical" },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const s = JOB_STATUS[status];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-xs font-medium text-ink">
      {status === "running" || status === "queued" ? (
        <Spinner className="size-3.5 text-accent" />
      ) : (
        <StatusIcon kind={s.icon} />
      )}
      {s.label}
    </span>
  );
}

export function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2">
      {children}
    </span>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
}) {
  return (
    <label className={`flex cursor-pointer items-start gap-3 ${disabled ? "opacity-50" : ""}`}>
      <input
        type="checkbox"
        role="switch"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden="true"
        className={`mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition peer-focus-visible:outline-2 peer-focus-visible:outline-accent ${
          checked ? "bg-accent" : "bg-[var(--baseline)]"
        }`}
      >
        <span className={`size-4 rounded-full bg-white shadow transition ${checked ? "translate-x-4" : ""}`} />
      </span>
      <span>
        <span className="block text-sm text-ink">{label}</span>
        {description && <span className="block text-xs text-ink-3">{description}</span>}
      </span>
    </label>
  );
}
