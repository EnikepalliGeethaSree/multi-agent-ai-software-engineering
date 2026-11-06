import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { DETAIL, LLM_MISSING, LLM_READY, job, mockFetch } from "./fixtures";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("layout", () => {
  it("shows the LLM status and navigation", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/llm/models": { models: [], default: null } }).fn);
    renderAt("/");
    expect(await screen.findByText("groq · openai/gpt-oss-120b")).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute("href", "/reviews");
  });

  it("reports an offline server", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("network down");
    });
    renderAt("/reviews");
    expect(await screen.findByText("Server offline")).toBeInTheDocument();
    expect(await screen.findByText(/Cannot reach the server/)).toBeInTheDocument();
  });

  it("renders a not-found page", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY }).fn);
    renderAt("/nope");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
  });
});

describe("new review", () => {
  it("forces static mode and explains why when no LLM is configured", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_MISSING }).fn);
    renderAt("/");
    await waitFor(() => expect(screen.getByRole("radio", { name: /Static only/ })).toBeChecked());
    expect(screen.getByRole("radio", { name: /Static \+ LLM/ })).toBeDisabled();
    expect(screen.getByText(/Add GEMINI_API_KEY to .env/)).toBeInTheDocument();
  });

  it("validates input before submitting", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/llm/models": { models: [], default: null } }).fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: "Start review" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a .zip or .py file");
    await userEvent.click(screen.getByRole("tab", { name: "Paste code" }));
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Paste some Python code");
  });

  it("rejects an unsupported file type on upload", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/llm/models": { models: [], default: null } }).fn);
    renderAt("/");
    const input = await screen.findByLabelText("Choose file to review");
    await userEvent.upload(input, new File(["hello"], "notes.txt"), { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent(".zip archive");
  });

  it("submits pasted code with the chosen options and opens the review", async () => {
    const mock = mockFetch({
      "GET /api/llm/status": LLM_READY,
      "GET /api/llm/models": { models: ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"], default: "openai/gpt-oss-120b" },
      "POST /api/reviews": job({ id: "fedcba654321", status: "queued", summary: null }),
      "GET /api/reviews/fedcba654321": { job: job({ id: "fedcba654321", status: "running", summary: null, progress: ["19:00:01 review started"] }), result: null },
    });
    vi.stubGlobal("fetch", mock.fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Paste code" }));
    await userEvent.type(screen.getByLabelText("Python code"), "x = 1");
    await userEvent.selectOptions(await screen.findByLabelText("Model"), "qwen/qwen3.8-27b");
    await userEvent.click(screen.getByRole("switch", { name: /Project context/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));

    expect(await screen.findByText(/Reviewing/)).toBeInTheDocument();
    const post = mock.calls.find((c) => c.method === "POST")!;
    const form = post.body as FormData;
    expect(form.get("snippet")).toBe("x = 1");
    expect(form.get("snippet_name")).toBe("snippet.py");
    const options = JSON.parse(String(form.get("options")));
    expect(options).toMatchObject({ mode: "full", rag_enabled: false, model: "qwen/qwen3.8-27b", min_confidence: 0.3, suggest_fixes: true });
  });

  it("shows server-side rejections", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/llm/models": { models: [], default: null },
        "POST /api/reviews": new Response(JSON.stringify({ detail: "File is larger than the 100 MB limit." }), { status: 413 }),
      }).fn,
    );
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Paste code" }));
    await userEvent.type(screen.getByLabelText("Python code"), "x = 1");
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("100 MB limit");
  });
});

describe("review detail", () => {
  it("renders the full dashboard for a finished review", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": DETAIL }).fn);
    renderAt("/reviews/abc123def456");
    expect(await screen.findByRole("heading", { name: /planted.zip/ })).toBeInTheDocument();
    expect(screen.queryByText(/Quality index/i)).not.toBeInTheDocument();
    expect(screen.getByText("Security issues").nextSibling).toHaveTextContent("1");
    for (const title of ["Findings by severity", "Findings by category", "Most affected files"]) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("shop/db.py: 5.5")).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 findings")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/reviews/abc123def456/report/pdf");
    expect(screen.getByText("How this review was produced")).toBeInTheDocument();
    expect(screen.getByText("10 proposed, 9 verified")).toBeInTheDocument();
    expect(screen.getByText(/10\.0% \(evidence not found 1\)/)).toBeInTheDocument();
    expect(screen.getByText("8,305 + 6,934")).toBeInTheDocument();
  });

  it("polls while running and shows the live log", async () => {
    let n = 0;
    const running = { job: job({ status: "running", summary: null, progress: ["19:00:01 review started", "19:00:05 reviewed unit 1/4"] }), result: null };
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/reviews/abc123def456": () => (++n < 2 ? running : DETAIL),
      }).fn,
    );
    renderAt("/reviews/abc123def456");
    expect(await screen.findByText(/reviewed unit 1\/4/)).toBeInTheDocument();
    expect(await screen.findByText("Showing 3 of 3 findings", {}, { timeout: 4000 })).toBeInTheDocument();
  });

  it("shows the error and log of a failed review", async () => {
    const failed = { job: job({ status: "failed", summary: null, error: "LLM error: Invalid API Key" }), result: null };
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": failed }).fn);
    renderAt("/reviews/abc123def456");
    expect(await screen.findByText("The review failed")).toBeInTheDocument();
    expect(screen.getByText("LLM error: Invalid API Key")).toBeInTheDocument();
  });

  it("handles an unknown review id", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY }).fn);
    renderAt("/reviews/000000000000");
    expect(await screen.findByText("Review not available")).toBeInTheDocument();
  });
});

describe("history and evaluation", () => {
  it("lists reviews with their summary numbers", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews": [job()] }).fn);
    renderAt("/reviews");
    const row = (await screen.findByText("planted.zip")).closest("tr")!;
    expect(within(row).getByText("3")).toBeInTheDocument(); // total findings
    expect(screen.queryByRole("columnheader", { name: "Quality index" })).not.toBeInTheDocument();
    expect(within(row).getByText("0 / 1")).toBeInTheDocument();
    expect(within(row).getByText("Static + LLM")).toBeInTheDocument();
  });

  it("shows an empty history", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews": [] }).fn);
    renderAt("/reviews");
    expect(await screen.findByText("No reviews yet")).toBeInTheDocument();
  });

  it("shows the baseline comparison with configurations, N/A and how to run", async () => {
    const cfg = (key: string, label: string, s: boolean, l: boolean, r: boolean) => ({
      key, letter: null, label, static: s, llm: l, rag: r, mode: "full",
    });
    const row = (c: ReturnType<typeof cfg>, values: Record<string, number | null>, extra: object = {}) => ({
      label: c.label, configuration: c, status: "ok", values, sd: {}, spread: {}, na: {}, n: 17, n_failed: 0,
      n_runs: 1, model: c.llm ? "openai/gpt-oss-120b" : null, run_ids: [`run_${c.key}`], notes: [], how_to_run: null, ...extra,
    });
    const A = cfg("static_only", "Static Only", true, false, false);
    const B = cfg("llm_only", "LLM Only", false, true, false);
    const table = {
      id: "planted", section: "1. Planted issues", title: "Planted-issue benchmark: detection by configuration",
      about: "", supplementary: false, show_counts: true, notes: [], observations: ["Static Only and LLM Only have the same recall (0.941)."],
      conditions: { "answer key": "17 issues" },
      fairness: [{ name: "Same samples (answer key)", ok: true, detail: "one fixture" }],
      columns: [
        { key: "precision", label: "Precision", metric: "precision", group: null, digits: 3 },
        { key: "roc_auc", label: "ROC-AUC", metric: "roc_auc", group: null, digits: 3 },
      ],
      rows: [
        row(A, { precision: 1, roc_auc: null }, { na: { roc_auc: "not applicable: positives only" } }),
        row(B, {}, { status: "not_run", na: { "*": "no saved run" }, how_to_run: "python -m marl_agents.cli eval planted --configuration llm_only", run_ids: [] }),
      ],
    };
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [],
        "GET /api/evaluation/summary": {
          generated_at: "2026-10-12T00:00:00Z", master: null, tables: [table], scope: ["Agent-level benchmark evaluation."],
          definitions: [{ key: "precision", name: "Precision", definition: "TP / (TP + FP)", scale: "0-1", higher_is_better: true }],
        },
      }).fn,
    );
    renderAt("/evaluation");
    expect(await screen.findByText("Planted-issue benchmark: detection by configuration")).toBeInTheDocument();
    const rowA = screen.getByRole("row", { name: /Static Only/ });
    expect(within(rowA).getByText("1.000")).toBeInTheDocument();
    expect(within(rowA).getByLabelText("Static on")).toBeInTheDocument();
    expect(within(rowA).getByLabelText("RAG off")).toBeInTheDocument();
    expect(within(rowA).getByText("N/A")).toHaveAttribute("title", "not applicable: positives only");
    expect(screen.getByText("python -m marl_agents.cli eval planted --configuration llm_only")).toBeInTheDocument();
    expect(screen.getByText("Same samples (answer key)")).toBeInTheDocument();
    expect(screen.getByText("Static Only and LLM Only have the same recall (0.941).")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Precision" })).toHaveAttribute("title", expect.stringContaining("TP / (TP + FP)"));
  });

  it("shows the evaluation status, table warnings and stopped runs", async () => {
    const table = {
      id: "cls", section: "2. CodeReviewer classification", title: "Paired classification", about: "",
      columns: [{ key: "roc_auc", label: "ROC-AUC", metric: null, group: null, digits: 3 }],
      rows: [], conditions: { "paired samples": "3 of 10 requested" }, fairness: [], observations: [], notes: [],
      supplementary: false, show_counts: false, badges: ["Preliminary", "Historical: Groq (m)"],
      warning: "Preliminary: only 3 of 10 requested samples are paired.",
    };
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [],
        "GET /api/evaluation/summary": {
          generated_at: "2026-11-06T00:00:00Z", master: null, tables: [table], scope: [], definitions: [],
          status: {
            items: [
              { name: "Risk ranking", status: "complete", detail: "Size-only is the better ranker.", run_ids: ["r1"], command: null },
              { name: "Paired classification", status: "preliminary", detail: "3 of 10 requested samples paired.", run_ids: [], command: null },
              { name: "File-size benchmark", status: "incomplete", detail: "8 of 90 planned runs complete.", run_ids: ["r2"], command: "python -m bench" },
              { name: "Planted issues on Gemini", status: "pending", detail: "All four configurations.", run_ids: [], command: "python -m planted" },
            ],
            limitations: ["17 issues is a small benchmark."],
            findings: ["Risk model v2 does not beat the size baseline."],
            unfinished_runs: ["20261012T084016Z_timing_r2: stopped before metrics were saved"],
          },
        },
      }).fn,
    );
    renderAt("/evaluation");
    expect(await screen.findByText("Evaluation status")).toBeInTheDocument();
    expect(screen.getByText("Completed:")).toBeInTheDocument();
    expect(screen.getByText("Pending Gemini:")).toBeInTheDocument();
    expect(screen.getAllByText("8 of 90 planned runs complete.")[0]).toBeVisible();
    expect(screen.getByText("python -m planted")).toBeInTheDocument();
    expect(screen.getByText("Risk model v2 does not beat the size baseline.")).toBeVisible();
    expect(screen.getByText("17 issues is a small benchmark.")).toBeInTheDocument();
    expect(screen.getByText(/stopped before metrics were saved/)).toBeInTheDocument();
    expect(screen.getByText("Stopped runs not in the tables")).toBeVisible();
    expect(screen.getByRole("note")).toHaveTextContent("only 3 of 10 requested samples");
    expect(screen.getByText("Historical: Groq (m)")).toBeInTheDocument();
  });

  it("states what finished in a benchmark, not only what was planned", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [
          { name: "r3_runtime_full_r5", started_at: "2026-11-06T16:20:14Z", model: "gemini-3.6-flash", provider: "gemini", errors: 0,
            headline: { kind: "runtime", mode: "full", repeats: 5, inputs: 9, complete: 8, partial: 3, failed: 0, skipped: 79 } },
        ],
        "GET /api/evaluation/summary": { generated_at: "2026-11-06T00:00:00Z", master: null, tables: [], scope: [], definitions: [] },
      }).fn,
    );
    renderAt("/evaluation/runs");
    expect(await screen.findByRole("columnheader", { name: "Rounds planned" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Runs complete" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Skipped" })).toBeInTheDocument();
  });

  const emptySummary = { generated_at: "2026-11-06T00:00:00Z", master: null, tables: [], scope: [], definitions: [] };
  const cardTable = (over: object) => ({
    id: "t", section: "2. CodeReviewer classification", title: "Paired table", about: "",
    columns: [{ key: "precision", label: "Precision", metric: null, group: null, digits: 3 }],
    rows: [], conditions: {}, fairness: [], observations: [], notes: [], supplementary: false, show_counts: true, ...over,
  });
  const cardRow = (label: string, over: object) => ({
    label, configuration: null, status: "ok", values: {}, sd: {}, spread: {}, na: {}, n: 3, n_failed: 0, n_runs: 1, model: null,
    run_ids: [], notes: [], how_to_run: null, ...over,
  });
  const summaryWith = (tables: object[]) =>
    mockFetch({
      "GET /api/llm/status": LLM_READY,
      "GET /api/experiments": [],
      "GET /api/evaluation/summary": { ...emptySummary, tables },
    }).fn;

  it("keeps failures on screen while their details sit in a panel", async () => {
    vi.stubGlobal("fetch", summaryWith([cardTable({
      rows: [
        cardRow("Static + LLM", { n_failed: 7, run_ids: ["run_c"] }),
        cardRow("Static + LLM + RAG", { status: "incomplete", n_failed: 10, na: { "*": "every sample failed" } }),
        cardRow("LLM Only", { status: "not_run", how_to_run: "python -m run-b" }),
      ],
      notes: ["Explains the table.", "Static + LLM: 7 of 10 samples failed (llm: 7).", "Run all four: python -m run-all"],
      fairness: [{ name: "Same samples", ok: false, detail: "3 of 10" }],
    })]));
    renderAt("/evaluation");
    const line = await screen.findByText(/^Failed or missing:/);
    expect(line).toBeVisible();
    expect(line).toHaveTextContent("Static + LLM: 7 failed");
    expect(line).toHaveTextContent("Static + LLM + RAG: incomplete, 10 failed");
    expect(line).toHaveTextContent("LLM Only: not run");
    expect(screen.getByText("Explains the table.")).toBeVisible();
    const panel = (name: RegExp) => screen.getByText(name).closest("details")!;
    expect(panel(/Failed and skipped details/)).not.toHaveAttribute("open");
    expect(within(panel(/Failed and skipped details/)).getByText(/7 of 10 samples failed/)).toBeInTheDocument();
    expect(within(panel(/Failed and skipped details/)).getByText(/every sample failed/)).toBeInTheDocument();
    expect(within(panel(/Reproduction commands/)).getByText("python -m run-b")).toBeInTheDocument();
    expect(within(panel(/Reproduction commands/)).getByText(/python -m run-all/)).toBeInTheDocument();
    expect(within(panel(/Fairness checks/)).getByText("Same samples")).toBeInTheDocument();
    const source = within(panel(/Source runs/)).getByRole("link", { name: "run_c" });
    expect(source).toHaveAttribute("href", "/evaluation/run_c");
  });

  it("shows Unavailable for unmeasured values and keeps N/A for not applicable", async () => {
    vi.stubGlobal("fetch", summaryWith([cardTable({
      columns: [
        { key: "a", label: "Measured later", metric: null, group: null, digits: 3 },
        { key: "b", label: "Undefined", metric: null, group: null, digits: 3 },
      ],
      rows: [cardRow("Row", { values: { a: null, b: null }, na: { a: "no complete run", b: "not applicable: positives only" } })],
    })]));
    renderAt("/evaluation");
    expect(await screen.findByTitle("no complete run")).toHaveTextContent("Unavailable");
    expect(screen.getByTitle("not applicable: positives only")).toHaveTextContent("N/A");
  });

  it("never leaves an instability warning inside a closed panel", async () => {
    const plain = ["One.", "Two.", "Three.", "Four."];
    vi.stubGlobal("fetch", summaryWith([cardTable({ observations: [...plain, "Recall varies between complete runs."] })]));
    renderAt("/evaluation");
    const unstable = await screen.findByText("Recall varies between complete runs.");
    expect(unstable.closest("details")).toBeNull();
    expect(screen.getByText("Four.").closest("details")).not.toBeNull();
  });

  it("puts the supplementary judge last, labelled, and historical timing in a panel", async () => {
    vi.stubGlobal("fetch", summaryWith([
      cardTable({ id: "judge", section: "Supplementary", title: "Judge table", supplementary: true }),
      cardTable({ id: "hist", section: "6c. Efficiency: historical timing (not Gemini)", title: "Groq timing" }),
      cardTable({ id: "gem", section: "6a. Efficiency: Gemini", title: "Gemini timing" }),
      cardTable({ id: "new", section: "Something new", title: "Unplaced table" }),
    ]));
    renderAt("/evaluation");
    const judge = await screen.findByText("Judge table");
    expect(screen.getByRole("heading", { name: "Supplementary evaluation" })).toBeInTheDocument();
    expect(screen.getByText("Not a primary result. It has not been checked against human ratings.")).toBeVisible();
    expect(screen.getByText("Supplementary", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Groq timing").closest("details")).not.toBeNull();
    expect(screen.getByText("Gemini timing").closest("details")).toBeNull();
    expect(screen.getByText("Unplaced table")).toBeInTheDocument();
    const gemini = screen.getByText("Gemini timing");
    expect(gemini.compareDocumentPosition(judge) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("builds the overview from verified values and never from a small paired set", async () => {
    const status = { items: [], limitations: [], findings: [], unfinished_runs: [] };
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [
          { name: "c", started_at: null, model: null, provider: null, errors: 0, headline: { kind: "classifier", n: 1771, roc_auc: 0.723 } },
        ],
        "GET /api/evaluation/summary": {
          ...emptySummary, status,
          tables: [
            cardTable({ id: "planted", section: "1. Planted issues", observations: ["D varies between complete runs."],
              rows: [cardRow("Static + LLM + RAG", { n: 17, values: { issues_found: 17 } })] }),
            cardTable({ id: "codereviewer_cls", rows: [cardRow("LLM Only", { n: 3, values: { precision: 0.667 } })] }),
            cardTable({ id: "runtime_x", section: "6a. Efficiency: Gemini", show_counts: false,
              rows: [cardRow("Small, cold", { n_runs: 80, values: { complete: 5 } }), cardRow("Small, warm", { n_runs: 10, values: { complete: 3 } })] }),
          ],
        },
      }).fn,
    );
    renderAt("/evaluation");
    const tile = async (label: string) => (await screen.findByText(label)).parentElement!;
    expect(within(await tile("Planted issues found")).getByText("17 of 17")).toBeInTheDocument();
    expect(within(await tile("Planted issues found")).getByText(/Small benchmark, Groq. Varies between runs/)).toBeInTheDocument();
    expect(within(await tile("Classifier ROC-AUC")).getByText("0.723")).toBeInTheDocument();
    expect(within(await tile("Gemini benchmark runs")).getByText("8 of 90")).toBeInTheDocument();
    expect(within(await tile("Gemini benchmark runs")).getByText("Incomplete, preliminary")).toBeInTheDocument();
    expect(within(await tile("Retrieval Recall@10")).getByText("Unavailable")).toBeInTheDocument();
    const overview = (await tile("Classifier ROC-AUC")).parentElement!;
    expect(within(overview).queryByText("0.667")).toBeNull();
  });

  it("lists stopped runs on the saved-runs page and switches tabs", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [
          { name: "r9_mystery", started_at: null, model: null, provider: null, errors: 0, headline: { kind: "other" } },
        ],
        "GET /api/evaluation/summary": {
          ...emptySummary,
          status: { items: [], limitations: [], findings: [], unfinished_runs: ["r1_timing_r2: stopped before metrics were saved"] },
        },
      }).fn,
    );
    renderAt("/evaluation");
    await userEvent.click(await screen.findByRole("link", { name: "Saved runs" }));
    expect(await screen.findByText("r1_timing_r2: stopped before metrics were saved")).toBeVisible();
    expect(screen.getByRole("link", { name: "r9_mystery" })).toHaveAttribute("href", "/evaluation/r9_mystery");
    expect(screen.getByRole("link", { name: "Saved runs" })).toHaveAttribute("aria-current", "page");
  });

  it("shows no metrics for a run that scored nothing and no ROC-AUC for a tiny one", async () => {
    const run = (name: string, n: number, errors: number) => ({
      name, started_at: "2026-10-12T16:00:00Z", model: "m", provider: "groq", errors,
      headline: { kind: "codereviewer_cls", n, accuracy: n ? 0.667 : 0, precision: n ? 0.667 : 0, roc_auc: n ? 1 : null, adj_accuracy: 0, adj_precision: 0, adj_roc_auc: null },
    });
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [run("failed_run", 0, 10), run("tiny_run", 3, 7)],
        "GET /api/evaluation/summary": emptySummary,
      }).fn,
    );
    renderAt("/evaluation/runs");
    expect(await screen.findByText("no samples evaluated")).toBeInTheDocument();
    expect(screen.getByText("preliminary, n = 3")).toBeInTheDocument();
    const [, tiny] = screen.getAllByRole("row").filter((r) => within(r).queryByRole("link"));
    const empty = screen.getAllByRole("row").filter((r) => within(r).queryByRole("link"))[0];
    expect(within(empty).queryByText("0.000")).toBeNull();
    expect(within(tiny).getAllByTitle("not reported: 3 samples are too few for ROC-AUC")).toHaveLength(1);
    expect(within(tiny).getAllByText("0.667")).toHaveLength(2);
  });

  it("groups evaluation runs and opens a run summary", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({
        "GET /api/llm/status": LLM_READY,
        "GET /api/experiments": [
          { name: "r1_planted_full", started_at: "2026-09-29T19:42:03Z", model: "openai/gpt-oss-120b", provider: "groq", errors: 0,
            headline: { kind: "planted", recall: 1, recall_llm: 1, defect_precision: 1, negative_fp: 0, mean_line_error: 0.294 } },
          { name: "r2_codereviewer_cls", started_at: "2026-09-29T19:22:59Z", model: null, provider: null, errors: 1,
            headline: { kind: "codereviewer_cls", n: 4195, accuracy: 0.437, precision: 0.384, roc_auc: 0.417, adj_accuracy: 0.541, adj_precision: 0.592, adj_roc_auc: 0.539 } },
        ],
        "GET /api/experiments/r1_planted_full": {
          name: "r1_planted_full",
          metrics: { detection: { recall: 1 } },
          meta: { llm_model: "openai/gpt-oss-120b", git_commit: "uncommitted", errors: 0 },
          summary_md: "# Planted\n\n| Metric | Value |\n|---|---:|\n| Recall | 1.000 |\n",
        },
      }).fn,
    );
    renderAt("/evaluation/runs");
    expect(await screen.findByText("Planted-issue benchmark")).toBeInTheDocument();
    expect(screen.getByText("0.294")).toBeInTheDocument();
    expect(screen.getByText("0.539")).toBeInTheDocument();
    expect(screen.getByText("(1 failed samples)")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("link", { name: /2026/ })[0]);
    expect(await screen.findByRole("heading", { name: "Planted" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1.000" })).toBeInTheDocument();
    expect(screen.getByText("openai/gpt-oss-120b")).toBeInTheDocument();
  });
});
