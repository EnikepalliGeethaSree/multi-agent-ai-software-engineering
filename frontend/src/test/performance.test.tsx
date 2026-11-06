import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { BenchmarkRun, PerformanceRecord } from "../api/types";
import { comparedBars, stageBars } from "../components/PerformancePanels";
import { ScatterChart } from "../components/ScatterChart";
import { value } from "../lib/format";
import { pointsFor } from "../pages/Performance";
import { DETAIL, job, LLM_READY, mockFetch } from "./fixtures";

const RECORD: PerformanceRecord = {
  review_id: "abc123abc123",
  file_name: "service.py",
  created_at: "2026-11-06T10:00:00Z",
  status: "complete",
  run_type: "cold",
  provider: null,
  model: null,
  file_size_kb: 12.5,
  lines_of_code: 300,
  files_reviewed: 1,
  input_tokens: null,
  output_tokens: null,
  thinking_tokens: null,
  review_units: 2,
  llm_calls: null,
  llm_failed_calls: null,
  llm_calls_detail: [],
  file_ingestion_sec: 0.01,
  parsing_sec: 0.02,
  ast_call_graph_sec: 0.03,
  static_analysis_sec: 1.5,
  rag_retrieval_sec: null,
  rag_index_sec: null,
  prompt_construction_sec: null,
  llm_inference_sec: null,
  llm_quota_wait_sec: null,
  evidence_validation_sec: 0.04,
  dedup_severity_sec: 0.05,
  validation_sec: 0.1,
  fix_generation_sec: null,
  classifier_sec: null,
  report_generation_sec: 0.2,
  total_sec: 2.0,
  failed_stages: [],
  findings: 4,
  failed_units: 0,
  skipped_units: 0,
  units_from_cache: 0,
  units_deduplicated: 0,
  classifier_skipped_units: null,
  message: null,
  resets_at: null,
};

const RUN: BenchmarkRun = {
  name: "20261106T120000Z_runtime_static_only_r5",
  started_at: "2026-11-06T12:00:00Z",
  git_commit: "uncommitted",
  mode: "static_only",
  rag: false,
  repeats: 5,
  pipeline_check_only: false,
  conditions: { provider: null, model: null, date: "2026-11-06", api_conditions: "no API used" },
  results: [
    {
      category: "small",
      run_type: "cold",
      runs: 15,
      complete: 15,
      partial: 0,
      failed: 0,
      skipped: 0,
      mean_sec: 2.5,
      median_sec: 2.4,
      p95_sec: 3.1,
      min_sec: 2.2,
      max_sec: 3.3,
      mean_llm_inference_sec: null,
      mean_rag_retrieval_sec: null,
      mean_static_analysis_sec: 2.3,
      mean_input_tokens: null,
      mean_output_tokens: null,
      mean_findings: 12,
      mean_review_chunks: null,
      skipped_chunks: 0,
    },
  ],
};

const API = {
  "GET /api/llm/status": LLM_READY,
  "GET /api/performance/reviews": [RECORD],
  [`GET /api/performance/reviews/${RECORD.review_id}`]: { record: RECORD, spans: [] },
  "GET /api/performance/benchmarks": [RUN],
  [`GET /api/performance/benchmarks/${RUN.name}`]: {
    name: RUN.name,
    metrics: {},
    runs: [
      { file_name: "bisect.py", category: "small", repeat: 1, run_type: "cold", status: "complete", total_sec: 2.4, file_size_kb: 3.2, lines_of_code: 90, input_tokens: null },
      { file_name: "bisect.py", category: "small", repeat: 1, run_type: "cold", status: "failed", total_sec: 9.9, file_size_kb: 3.2, lines_of_code: 90, input_tokens: null },
    ],
  },
  "GET /api/evaluation/before-after": {
    rows: [
      { benchmark: "Planted issues", metric: "Recall", original: 1, improved: null, original_run: "r", improved_run: null, n: 17, note: "improved run missing: run it", higher_is_better: true },
    ],
    notes: ["Original = the agent on Groq."],
  },
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/*" element={<App />} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("performance page", () => {
  it("is linked from the navigation and shows real measurements", async () => {
    vi.stubGlobal("fetch", mockFetch(API).fn);
    renderAt("/performance");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Performance" })).toHaveAttribute("href", "/performance");
    expect(await screen.findByText("Total time")).toBeInTheDocument();
    expect(screen.getAllByText("2.00s").length).toBeGreaterThan(0);
    expect(screen.getByText("12.5 KB")).toBeInTheDocument();
    expect(screen.getByText("Time per stage")).toBeInTheDocument();
  });

  it("shows unavailable values, never zero, for what was not measured", async () => {
    vi.stubGlobal("fetch", mockFetch(API).fn);
    renderAt("/performance");
    const tile = (await screen.findByText("LLM inference")).closest("div")!;
    expect(within(tile).getByText("Unavailable")).toBeInTheDocument();
    expect(within(tile).queryByText("0.00s")).not.toBeInTheDocument();
    expect(await screen.findByText(/Not measured in this run:.*LLM inference/)).toBeInTheDocument();
  });

  it("explains an empty token chart instead of plotting zeros", async () => {
    vi.stubGlobal("fetch", mockFetch(API).fn);
    renderAt("/performance");
    expect(await screen.findByText(/No run has token counts yet/)).toBeInTheDocument();
  });

  it("shows benchmark statistics and marks comparison gaps as N/A", async () => {
    vi.stubGlobal("fetch", mockFetch(API).fn);
    renderAt("/performance");
    expect(await screen.findByText("Small (1-100 lines)")).toBeInTheDocument();
    expect(screen.getByText("15/15")).toBeInTheDocument();
    expect(await screen.findByText("N/A")).toBeInTheDocument();
    expect(screen.getByText("improved run missing: run it")).toBeInTheDocument();
  });

  it("copes with no data at all", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch({ ...API, "GET /api/performance/reviews": [], "GET /api/performance/benchmarks": [] }).fn,
    );
    renderAt("/performance");
    expect(await screen.findByText("No reviews yet")).toBeInTheDocument();
    expect(await screen.findByText("No benchmark runs yet")).toBeInTheDocument();
  });

  it("states the free-tier data notice", async () => {
    const llm = { ...LLM_READY, provider: "gemini", model: "gemini-3.8-flash", free_tier: true, data_notice: "Code is sent to Google." };
    vi.stubGlobal("fetch", mockFetch({ ...API, "GET /api/llm/status": llm }).fn);
    renderAt("/performance");
    expect(await screen.findByText("Code is sent to Google.")).toBeInTheDocument();
  });
});

describe("resume", () => {
  it("offers to continue a partial review and calls the API", async () => {
    const partial = job({ status: "done", resumable: true, error: "gemini quota reached. Resume later." });
    const api = mockFetch({
      "GET /api/llm/status": LLM_READY,
      [`GET /api/reviews/${partial.id}`]: { ...DETAIL, job: partial },
      [`POST /api/reviews/${partial.id}/resume`]: { ...partial, status: "queued", resumable: false },
    });
    vi.stubGlobal("fetch", api.fn);
    renderAt(`/reviews/${partial.id}`);
    await userEvent.click(await screen.findByRole("button", { name: "Resume review" }));
    expect(screen.getByText(/gemini quota reached/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST" && c.url.endsWith("/resume"))).toBe(true);
  });
});

describe("chart helpers", () => {
  it("leaves unmeasured runs out and counts them", () => {
    const runs = [
      { key: "a", source: "s", file_name: "a.py", file_size_kb: 1, lines_of_code: 10, input_tokens: null, total_sec: 2, status: "complete" as const },
      { key: "b", source: "s", file_name: "b.py", file_size_kb: 2, lines_of_code: 20, input_tokens: 50, total_sec: 3, status: "complete" as const },
    ];
    const { points, excluded } = pointsFor(runs, (r) => r.input_tokens);
    expect(points.map((p) => p.x)).toEqual([50]);
    expect(excluded).toBe(1);
  });

  it("charts only measured stages", () => {
    const { bars, missing } = stageBars(RECORD);
    expect(bars.map((b) => b.label)).toContain("Static analysis");
    expect(bars.map((b) => b.label)).not.toContain("LLM inference");
    expect(missing).toContain("LLM inference");
  });

  it("compares only metrics measured on both sides", () => {
    const rows = [
      { benchmark: "b", metric: "Recall", original: 0.9, improved: 1, original_run: "a", improved_run: "b", n: 1, note: null, higher_is_better: true },
      { benchmark: "b", metric: "F1", original: 0.9, improved: null, original_run: "a", improved_run: null, n: 1, note: "x", higher_is_better: true },
    ];
    expect(comparedBars(rows).map((b) => b.label)).toEqual(["Recall: original", "Recall: improved"]);
  });

  it("formats a missing value as unavailable and a real zero as zero", () => {
    expect(value(null, "s")).toBe("Unavailable");
    expect(value(0, "s")).toBe("0.00s");
  });

  it("offers a table view of a scatter chart", async () => {
    render(<ScatterChart title="T" xLabel="X" yLabel="Y" points={[{ key: "a", x: 1, y: 2, label: "a.py" }]} excluded={2} />);
    expect(screen.getByText(/2 runs not shown/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("cell", { name: "a.py" })).toBeInTheDocument();
  });
});
