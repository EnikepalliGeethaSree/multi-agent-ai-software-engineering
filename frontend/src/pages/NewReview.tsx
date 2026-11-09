import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api, type ReviewInput } from "../api/client";
import type { AgentName, LLMProviderName, LLMStatus, Mode, ReviewOptions } from "../api/types";
import { ChangeForm, EMPTY_CHANGE, toChangeInput, type ChangeFormState } from "../components/ChangeForm";
import { Button, Card, ErrorBanner, Spinner, StatusIcon, Toggle } from "../components/ui";

export const MAX_ZIP_BYTES = 100 * 1024 * 1024;
export const MAX_PY_BYTES = 2 * 1024 * 1024;

export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!name.endsWith(".zip") && !name.endsWith(".py")) {
    return "Choose a .zip archive of a repository or a single .py file.";
  }
  if (file.size === 0) return "The file is empty.";
  const limit = name.endsWith(".zip") ? MAX_ZIP_BYTES : MAX_PY_BYTES;
  if (file.size > limit) return `The file is larger than the ${limit / (1024 * 1024)} MB limit.`;
  return null;
}

const MODES: { value: Mode; title: string; text: string; needsLLM: boolean }[] = [
  { value: "full", title: "Static + LLM", text: "Rule-based tools plus LLM reasoning (recommended).", needsLLM: true },
  { value: "static_only", title: "Static only", text: "Ruff, Radon, AST checks, secrets. Free and fast.", needsLLM: false },
  { value: "llm_only", title: "LLM only", text: "LLM without static tools (ablation).", needsLLM: true },
];

export const PROVIDERS: Record<LLMProviderName, { title: string; text: string }> = {
  gemini: { title: "Gemini (free tier)", text: "Hosted by Google; the code is sent to Google. Official evaluation provider." },
  ollama: { title: "Ollama (local)", text: "Runs on this machine; no code leaves it. About a minute per request." },
};

const AGENTS: { value: AgentName; title: string; text: string }[] = [
  { value: "code_review", title: "Code review", text: "Quality, maintainability, security and bugs." },
  { value: "bug_detection", title: "Bug detection", text: "Runtime and logic defects, with what triggers them." },
];

export default function NewReview() {
  const { llm } = useOutletContext<{ llm: LLMStatus | null }>();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<"upload" | "paste" | "change">("upload");
  const [change, setChange] = useState<ChangeFormState>(EMPTY_CHANGE);
  const [localGit, setLocalGit] = useState(true);
  const [file, setFile] = useState<File | null>(null);
  const [code, setCode] = useState("");
  const [filename, setFilename] = useState("snippet.py");
  const [dragging, setDragging] = useState(false);
  const [options, setOptions] = useState<ReviewOptions>({
    agent: "code_review",
    failing_test: null,
    mode: "full",
    provider: null,
    rag_enabled: true,
    structural_context: true,
    model: null,
    min_confidence: 0.3,
    include_tests: false,
    suggest_fixes: true,
  });
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [probe, setProbe] = useState<{ state: "idle" | "running" | "ok" | "fail"; text?: string }>({ state: "idle" });

  // The status of the provider this review will use: the server's, or the one picked below.
  const [chosen, setChosen] = useState<LLMStatus | null>(null);
  const active = options.provider ? chosen : llm;
  useEffect(() => {
    setChosen(null);
    const provider = options.provider;
    if (!provider) return;
    let live = true;
    api
      .llmStatus(false, provider)
      .then((s) => live && setChosen(s))
      .catch(
        (e) =>
          live &&
          setChosen({
            provider,
            model: null,
            requests_per_minute: null,
            tokens_per_minute: null,
            ready: false,
            error: e instanceof Error ? e.message : String(e),
          }),
      );
    return () => {
      live = false;
    };
  }, [options.provider]);
  const llmReady = active?.ready ?? false;
  useEffect(() => {
    if (active && !active.ready) setOptions((o) => (o.mode === "static_only" ? o : { ...o, mode: "static_only" }));
  }, [active]);
  useEffect(() => {
    api
      .health()
      .then((h) => setLocalGit(h.local_git ?? false))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!llmReady) return;
    api
      .llmModels(options.provider)
      .then((r) => setModels(r.models))
      .catch(() => setModels([]));
  }, [llmReady, options.provider]);

  const pickFile = (f: File | null) => {
    setError(null);
    if (!f) return setFile(null);
    const problem = validateFile(f);
    if (problem) {
      setFile(null);
      setError(problem);
      return;
    }
    setFile(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    pickFile(e.dataTransfer.files?.[0] ?? null);
  };

  const testConnection = async () => {
    setProbe({ state: "running" });
    try {
      const s = await api.llmStatus(true, options.provider);
      if (s.probe?.ok) setProbe({ state: "ok", text: `Reachable (${s.probe.latency_ms} ms)` });
      else setProbe({ state: "fail", text: s.probe?.error ?? s.error ?? "Not reachable" });
    } catch (e) {
      setProbe({ state: "fail", text: e instanceof Error ? e.message : String(e) });
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (options.mode !== "static_only" && !llmReady) {
      return setError(`${active?.error ?? "The selected LLM is not available."} Choose “Static only” or another provider.`);
    }
    if (tab === "change") {
      const changeInput = toChangeInput(change, localGit);
      if (typeof changeInput === "string") return setError(changeInput);
      setSubmitting(true);
      try {
        const job = await api.createChangeReview(changeInput, options);
        navigate(`/reviews/${job.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setSubmitting(false);
      }
      return;
    }
    let input: ReviewInput;
    if (tab === "upload") {
      if (!file) return setError("Choose a .zip or .py file to review.");
      input = { kind: "file", file };
    } else {
      if (!code.trim()) return setError("Paste some Python code to review.");
      input = { kind: "snippet", code, filename: filename.trim() || "snippet.py" };
    }
    setSubmitting(true);
    try {
      const job = await api.createReview(input, options);
      navigate(`/reviews/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  const set = <K extends keyof ReviewOptions>(k: K, v: ReviewOptions[K]) => setOptions((o) => ({ ...o, [k]: v }));
  const tabCls = (on: boolean) =>
    `rounded-lg px-3 py-1.5 text-sm ${on ? "bg-accent-wash font-medium text-ink" : "text-ink-2 hover:bg-surface-2"}`;

  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_360px]" noValidate>
      <div className="space-y-4">
        <div>
          <h1 className="text-xl font-semibold text-ink">New code review</h1>
          <p className="mt-1 text-sm text-ink-2">
            Upload a repository (.zip) or a Python file, paste code, or review a change (branch, commit, uncommitted
            work or two versions). The agent combines static analysis, project
            context (RAG) and an LLM, validates every finding against the code, and produces a report.
          </p>
        </div>

        <Card>
          <div className="mb-4 flex gap-1" role="tablist" aria-label="Input type">
            <button type="button" role="tab" aria-selected={tab === "upload"} className={tabCls(tab === "upload")} onClick={() => setTab("upload")}>
              Upload file
            </button>
            <button type="button" role="tab" aria-selected={tab === "paste"} className={tabCls(tab === "paste")} onClick={() => setTab("paste")}>
              Paste code
            </button>
            <button type="button" role="tab" aria-selected={tab === "change"} className={tabCls(tab === "change")} onClick={() => setTab("change")}>
              Review a change
            </button>
          </div>

          {tab === "change" ? (
            <ChangeForm value={change} onChange={setChange} localGit={localGit} />
          ) : tab === "upload" ? (
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 text-center transition ${
                dragging ? "border-accent bg-accent-wash" : "border-line"
              }`}
            >
              <svg viewBox="0 0 24 24" className="mb-3 size-8 text-ink-3" aria-hidden="true">
                <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {file ? (
                <p className="text-sm text-ink">
                  <span className="font-medium">{file.name}</span>{" "}
                  <span className="text-ink-3">({(file.size / 1024).toFixed(1)} KB)</span>
                </p>
              ) : (
                <p className="text-sm text-ink-2">Drag a .zip or .py file here</p>
              )}
              <div className="mt-3 flex gap-2">
                <Button onClick={() => fileInput.current?.click()}>{file ? "Choose another" : "Browse files"}</Button>
                {file && (
                  <Button variant="ghost" onClick={() => pickFile(null)}>
                    Remove
                  </Button>
                )}
              </div>
              <input
                ref={fileInput}
                type="file"
                accept=".zip,.py"
                className="sr-only"
                aria-label="Choose file to review"
                onChange={(e) => {
                  pickFile(e.target.files?.[0] ?? null);
                  e.target.value = "";
                }}
              />
              <p className="mt-3 text-xs text-ink-3">ZIP up to 100 MB · .py up to 2 MB · code is analyzed, never executed</p>
            </div>
          ) : (
            <div className="space-y-2">
              <label className="block text-xs text-ink-3" htmlFor="filename">
                File name (used in the report)
              </label>
              <input
                id="filename"
                value={filename}
                onChange={(e) => setFilename(e.target.value)}
                className="w-64 rounded-lg border border-line bg-surface px-3 py-1.5 font-mono text-sm text-ink"
              />
              <textarea
                aria-label="Python code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                spellCheck={false}
                placeholder={"def average(xs):\n    return sum(xs) / len(xs)"}
                className="h-72 w-full resize-y rounded-lg border border-line bg-code p-3 font-mono text-sm leading-relaxed text-ink placeholder:text-ink-3"
              />
            </div>
          )}
        </Card>

        {error && <ErrorBanner title="Cannot start the review" message={error} />}

        <div className="flex items-center gap-3">
          <Button type="submit" variant="primary" disabled={submitting} className="px-5 py-2">
            {submitting ? <Spinner /> : null}
            {submitting ? "Starting…" : "Start review"}
          </Button>
          <span className="text-xs text-ink-3">
            {options.mode === "static_only" ? "Usually a few seconds." : "With the LLM this takes about a minute per ~500 lines."}
          </span>
        </div>
      </div>

      <aside className="space-y-4">
        <Card title="Agent">
          <div className="space-y-2" role="radiogroup" aria-label="Agent">
            {AGENTS.map((a) => {
              const on = (options.agent ?? "code_review") === a.value;
              return (
                <label
                  key={a.value}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${on ? "border-accent bg-accent-wash" : "border-line"}`}
                >
                  <input
                    type="radio"
                    name="agent"
                    value={a.value}
                    checked={on}
                    onChange={() => set("agent", a.value)}
                    className="mt-1 accent-[var(--accent)]"
                  />
                  <span>
                    <span className="block text-sm font-medium text-ink">{a.title}</span>
                    <span className="block text-xs text-ink-3">{a.text}</span>
                  </span>
                </label>
              );
            })}
          </div>
          {options.agent === "bug_detection" && (
            <div className="mt-3">
              <label className="block text-xs text-ink-3" htmlFor="failing-test">
                Failing test (optional)
              </label>
              <input
                id="failing-test"
                value={options.failing_test ?? ""}
                onChange={(e) => set("failing_test", e.target.value || null)}
                placeholder="tests/test_x.py::test_y"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 font-mono text-xs text-ink"
              />
              <p className="mt-1 text-xs text-ink-3">The test is read, never run. The agent ranks where the failure comes from.</p>
            </div>
          )}
        </Card>

        <Card title="Review mode">
          <div className="space-y-2" role="radiogroup" aria-label="Review mode">
            {MODES.map((m) => {
              const disabled = m.needsLLM && !llmReady;
              const on = options.mode === m.value;
              return (
                <label
                  key={m.value}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-3 ${on ? "border-accent bg-accent-wash" : "border-line"} ${
                    disabled ? "cursor-not-allowed opacity-50" : ""
                  }`}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={m.value}
                    checked={on}
                    disabled={disabled}
                    onChange={() => set("mode", m.value)}
                    className="mt-1 accent-[var(--accent)]"
                  />
                  <span>
                    <span className="block text-sm font-medium text-ink">{m.title}</span>
                    <span className="block text-xs text-ink-3">{m.text}</span>
                  </span>
                </label>
              );
            })}
          </div>
          {!llmReady && active && (
            <p className="mt-3 flex gap-2 text-xs text-ink-2">
              <StatusIcon kind="warning" />
              <span>
                {active.error ?? "LLM not configured."}{" "}
                {active.provider === "ollama"
                  ? "Start Ollama and pull the model, or pick another provider."
                  : "Add GEMINI_API_KEY to .env and restart the server, or pick Ollama."}
              </span>
            </p>
          )}
        </Card>

        <Card title="LLM">
          <label className="block text-xs text-ink-3" htmlFor="provider">
            Provider
          </label>
          <select
            id="provider"
            value={options.provider ?? ""}
            onChange={(e) => {
              const value = (e.target.value || null) as LLMProviderName | null;
              setProbe({ state: "idle" });
              setModels([]);
              setOptions((o) => ({ ...o, provider: value, model: null, mode: "full" }));
            }}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink disabled:opacity-50"
          >
            <option value="">Server default ({llm?.provider ?? "none"})</option>
            {(llm?.selectable_providers ?? (["gemini", "ollama"] as LLMProviderName[])).map((p) => (
              <option key={p} value={p}>
                {PROVIDERS[p]?.title ?? p}
              </option>
            ))}
          </select>
          {options.provider && (
            <p className="mt-1 text-xs text-ink-3">
              {chosen ? PROVIDERS[options.provider]?.text : "Checking the provider…"}
            </p>
          )}
          <label className="mt-3 block text-xs text-ink-3" htmlFor="model">
            Model
          </label>
          <select
            id="model"
            value={options.model ?? ""}
            disabled={!llmReady || options.mode === "static_only"}
            onChange={(e) => set("model", e.target.value || null)}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink disabled:opacity-50"
          >
            <option value="">Default ({active?.model ?? "none"})</option>
            {models
              .filter((m) => m !== active?.model)
              .map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
          </select>
          <div className="mt-3 flex items-center gap-2">
            <Button onClick={testConnection} disabled={!llmReady || probe.state === "running"}>
              {probe.state === "running" && <Spinner />}
              Test connection
            </Button>
            {probe.state === "ok" && (
              <span className="flex items-center gap-1 text-xs text-ink-2">
                <StatusIcon kind="good" /> {probe.text}
              </span>
            )}
            {probe.state === "fail" && (
              <span className="flex items-center gap-1 text-xs text-ink-2" title={probe.text}>
                <StatusIcon kind="critical" /> Failed
              </span>
            )}
          </div>
          {active?.data_notice && (
            <p className="text-xs text-ink-3">{active.data_notice}</p>
          )}
          {active?.tokens_per_minute ? (
            <p className="mt-2 text-xs text-ink-3">
              Rate limit: {active.requests_per_minute ?? "∞"} requests / {active.tokens_per_minute.toLocaleString()} tokens per minute
            </p>
          ) : null}
        </Card>

        <Card title="Context & filtering">
          <div className="space-y-3">
            <Toggle
              checked={options.rag_enabled}
              disabled={options.mode === "static_only"}
              onChange={(v) => set("rag_enabled", v)}
              label="Project context (RAG)"
              description="Similar code, README and OWASP/standards guidance in the prompt."
            />
            <Toggle
              checked={options.structural_context}
              disabled={options.mode === "static_only" || !options.rag_enabled}
              onChange={(v) => set("structural_context", v)}
              label="Call-graph context"
              description="Callers, callees and tests of the code under review."
            />
            <Toggle
              checked={options.suggest_fixes ?? true}
              disabled={options.mode === "static_only"}
              onChange={(v) => set("suggest_fixes", v)}
              label="Suggest fixes"
              description="LLM patches for the top findings, each re-checked by static analysis. Extra LLM calls (slower on free quotas)."
            />
            <Toggle
              checked={options.include_tests}
              onChange={(v) => set("include_tests", v)}
              label="Review test files too"
            />
            <div>
              <label htmlFor="conf" className="flex justify-between text-sm text-ink">
                Minimum confidence <span className="tabular text-ink-2">{options.min_confidence.toFixed(2)}</span>
              </label>
              <input
                id="conf"
                type="range"
                min={0}
                max={0.9}
                step={0.05}
                value={options.min_confidence}
                onChange={(e) => set("min_confidence", Number(e.target.value))}
                className="mt-1 w-full accent-[var(--accent)]"
              />
              <p className="text-xs text-ink-3">Critical findings are always kept.</p>
            </div>
          </div>
        </Card>
      </aside>
    </form>
  );
}
