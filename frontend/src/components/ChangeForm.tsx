import { useRef } from "react";
import type { ChangeInput } from "../api/client";
import { Button } from "./ui";

export const MAX_CHANGE_ZIP_BYTES = 100 * 1024 * 1024;

export interface ChangeFormState {
  source: "git" | "zips";
  repoPath: string;
  target: "working" | "staged" | "refs";
  base: string;
  head: string;
  before: File | null;
  after: File | null;
}

export const EMPTY_CHANGE: ChangeFormState = {
  source: "git",
  repoPath: "",
  target: "working",
  base: "",
  head: "",
  before: null,
  after: null,
};

const REF = /^[A-Za-z0-9._/@~^{}:+-]{1,200}$/;

function checkZip(f: File | null, which: string): string | null {
  if (!f) return `Choose the ${which} ZIP.`;
  if (!f.name.toLowerCase().endsWith(".zip")) return `The ${which} version must be a .zip archive.`;
  if (f.size === 0) return `The ${which} ZIP is empty.`;
  if (f.size > MAX_CHANGE_ZIP_BYTES) return `The ${which} ZIP is larger than 100 MB.`;
  return null;
}

/** Form state -> API input, or a message explaining what is missing. */
export function toChangeInput(s: ChangeFormState, localGit: boolean): ChangeInput | string {
  if (s.source === "zips") {
    const problem = checkZip(s.before, "“before”") ?? checkZip(s.after, "“after”");
    if (problem) return problem;
    return { kind: "zips", before: s.before as File, after: s.after as File };
  }
  if (!localGit) return "Reviewing a local git repository is disabled on this server. Upload two ZIPs instead.";
  if (!s.repoPath.trim()) return "Enter the path of a git repository on this computer.";
  for (const ref of [s.base, s.target === "refs" ? s.head : ""]) {
    const r = ref.trim();
    if (r && (r.startsWith("-") || !REF.test(r))) return `“${r}” is not a valid branch, tag or commit.`;
  }
  return { kind: "git", repoPath: s.repoPath, target: s.target, base: s.base, head: s.head };
}

const TARGETS: { value: ChangeFormState["target"]; title: string; text: string }[] = [
  { value: "working", title: "Uncommitted changes", text: "Working tree compared with HEAD (or the base below)." },
  { value: "staged", title: "Staged changes", text: "What `git commit` would record now (pre-commit check)." },
  { value: "refs", title: "Two branches / commits", text: "Like a pull request: base … head." },
];

function ZipPicker({ label, file, onPick }: { label: string; file: File | null; onPick: (f: File | null) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-line p-3">
      <span className="w-14 text-sm font-medium text-ink">{label}</span>
      <Button onClick={() => input.current?.click()}>{file ? "Change" : "Choose ZIP"}</Button>
      <span className="min-w-0 truncate text-sm text-ink-2">
        {file ? `${file.name} (${(file.size / 1024).toFixed(1)} KB)` : "No file chosen"}
      </span>
      <input
        ref={input}
        type="file"
        accept=".zip"
        className="sr-only"
        aria-label={`Choose the ${label.toLowerCase()} ZIP`}
        onChange={(e) => {
          onPick(e.target.files?.[0] ?? null);
          e.target.value = "";
        }}
      />
    </div>
  );
}

export function ChangeForm({
  value,
  onChange,
  localGit,
}: {
  value: ChangeFormState;
  onChange: (v: ChangeFormState) => void;
  localGit: boolean;
}) {
  const set = <K extends keyof ChangeFormState>(k: K, v: ChangeFormState[K]) => onChange({ ...value, [k]: v });
  const inputCls = "w-full rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-sm text-ink placeholder:text-ink-3";
  const pill = (on: boolean) =>
    `rounded-lg border px-3 py-1.5 text-sm ${on ? "border-accent bg-accent-wash text-ink" : "border-line text-ink-2 hover:bg-surface-2"}`;

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">
        Reviews only what changed, plus the unchanged code that depends on it (callers whose calls no longer fit), and
        ranks the changed hunks by risk.
      </p>
      <div className="flex gap-2" role="radiogroup" aria-label="Change source">
        <button type="button" role="radio" aria-checked={value.source === "git"} className={pill(value.source === "git")} onClick={() => set("source", "git")}>
          Local git repository
        </button>
        <button type="button" role="radio" aria-checked={value.source === "zips"} className={pill(value.source === "zips")} onClick={() => set("source", "zips")}>
          Two ZIP versions
        </button>
      </div>

      {value.source === "git" ? (
        <div className="space-y-3">
          {!localGit && (
            <p className="text-sm text-ink-2">This server does not allow reading local repositories. Use two ZIPs.</p>
          )}
          <div>
            <label htmlFor="repo-path" className="block text-xs text-ink-3">
              Repository path on this computer
            </label>
            <input
              id="repo-path"
              value={value.repoPath}
              onChange={(e) => set("repoPath", e.target.value)}
              placeholder={"C:\\Users\\me\\projects\\my-app"}
              className={`mt-1 ${inputCls}`}
              disabled={!localGit}
            />
            <p className="mt-1 text-xs text-ink-3">
              Read with git only (no hooks, no checkout). Works only when the dashboard runs on this machine.
            </p>
          </div>
          <div className="space-y-2" role="radiogroup" aria-label="What to review">
            {TARGETS.map((t) => (
              <label
                key={t.value}
                className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${value.target === t.value ? "border-accent bg-accent-wash" : "border-line"}`}
              >
                <input
                  type="radio"
                  name="change-target"
                  checked={value.target === t.value}
                  onChange={() => set("target", t.value)}
                  disabled={!localGit}
                  className="mt-1 accent-[var(--accent)]"
                />
                <span>
                  <span className="block text-sm font-medium text-ink">{t.title}</span>
                  <span className="block text-xs text-ink-3">{t.text}</span>
                </span>
              </label>
            ))}
          </div>
          {value.target !== "staged" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="base-ref" className="block text-xs text-ink-3">
                  Base {value.target === "refs" ? "(default main)" : "(default HEAD)"}
                </label>
                <input
                  id="base-ref"
                  value={value.base}
                  onChange={(e) => set("base", e.target.value)}
                  placeholder={value.target === "refs" ? "main" : "HEAD"}
                  className={`mt-1 ${inputCls}`}
                  disabled={!localGit}
                />
              </div>
              {value.target === "refs" && (
                <div>
                  <label htmlFor="head-ref" className="block text-xs text-ink-3">
                    Head (default HEAD)
                  </label>
                  <input
                    id="head-ref"
                    value={value.head}
                    onChange={(e) => set("head", e.target.value)}
                    placeholder="feature/my-branch"
                    className={`mt-1 ${inputCls}`}
                    disabled={!localGit}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <ZipPicker label="Before" file={value.before} onPick={(f) => set("before", f)} />
          <ZipPicker label="After" file={value.after} onPick={(f) => set("after", f)} />
          <p className="text-xs text-ink-3">Two snapshots of the same project, e.g. GitHub “Download ZIP” of two branches.</p>
        </div>
      )}
    </div>
  );
}
