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
    renderAt("/evaluation");
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
