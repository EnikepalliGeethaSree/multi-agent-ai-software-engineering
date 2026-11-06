import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { ChangeReview, Finding, ReviewDetail } from "../api/types";
import { impactFindings } from "../components/ChangePanel";
import { EMPTY_CHANGE, toChangeInput } from "../components/ChangeForm";
import { DiffView } from "../components/DiffView";
import { fixStatus } from "../components/FindingsTable";
import { DETAIL, LLM_READY, finding, job, mockFetch } from "./fixtures";

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

const HEALTH = { status: "ok", jobs: 0, running: 0, local_git: true };
const zip = (name: string) => new File(["PK"], name, { type: "application/zip" });

describe("change form validation", () => {
  it("requires a repository path and valid refs", () => {
    expect(toChangeInput(EMPTY_CHANGE, true)).toMatch(/path of a git repository/);
    expect(toChangeInput({ ...EMPTY_CHANGE, repoPath: "/r", base: "--upload-pack=x" }, true)).toMatch(/not a valid/);
    expect(toChangeInput({ ...EMPTY_CHANGE, repoPath: "/r", target: "refs", head: "a b" }, true)).toMatch(/not a valid/);
    expect(toChangeInput({ ...EMPTY_CHANGE, repoPath: "/r" }, false)).toMatch(/disabled/);
    expect(toChangeInput({ ...EMPTY_CHANGE, repoPath: "/r", target: "staged" }, true)).toMatchObject({ kind: "git", target: "staged" });
  });

  it("requires two non-empty ZIPs", () => {
    const zips = { ...EMPTY_CHANGE, source: "zips" as const };
    expect(toChangeInput(zips, true)).toMatch(/before/);
    expect(toChangeInput({ ...zips, before: zip("a.zip") }, true)).toMatch(/after/);
    expect(toChangeInput({ ...zips, before: zip("a.zip"), after: new File(["x"], "b.tar") }, true)).toMatch(/\.zip/);
    expect(toChangeInput({ ...zips, before: zip("a.zip"), after: zip("b.zip") }, false)).toMatchObject({ kind: "zips" });
  });
});

describe("new change review", () => {
  const routes = (extra: Record<string, unknown> = {}) =>
    mockFetch({
      "GET /api/llm/status": LLM_READY,
      "GET /api/llm/models": { models: [], default: null },
      "GET /api/health": HEALTH,
      "POST /api/changes": job({ id: "c0ffee000001", source_type: "change", status: "queued", summary: null }),
      "GET /api/reviews/c0ffee000001": { job: job({ id: "c0ffee000001", status: "running", summary: null }), result: null },
      ...extra,
    });

  it("submits a branch comparison of a local git repository", async () => {
    const mock = routes();
    vi.stubGlobal("fetch", mock.fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Review a change" }));
    await userEvent.type(screen.getByLabelText("Repository path on this computer"), "C:/code/shop");
    await userEvent.click(screen.getByRole("radio", { name: /Two branches/ }));
    await userEvent.type(screen.getByLabelText(/^Base/), "main");
    await userEvent.type(screen.getByLabelText(/^Head/), "feature/users");
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));

    expect(await screen.findByText(/Reviewing/)).toBeInTheDocument();
    const post = mock.calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/changes");
    const form = post.body as FormData;
    expect([form.get("repo_path"), form.get("base"), form.get("head"), form.get("staged")]).toEqual([
      "C:/code/shop",
      "main",
      "feature/users",
      null,
    ]);
  });

  it("submits staged changes without refs", async () => {
    const mock = routes();
    vi.stubGlobal("fetch", mock.fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Review a change" }));
    await userEvent.type(screen.getByLabelText("Repository path on this computer"), "/srv/app");
    await userEvent.click(screen.getByRole("radio", { name: /Staged changes/ }));
    expect(screen.queryByLabelText(/^Base/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    await screen.findByText(/Reviewing/);
    const form = mock.calls.find((c) => c.method === "POST")!.body as FormData;
    expect([form.get("staged"), form.get("base"), form.get("head")]).toEqual(["true", null, null]);
  });

  it("submits two ZIP versions", async () => {
    const mock = routes();
    vi.stubGlobal("fetch", mock.fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Review a change" }));
    await userEvent.click(screen.getByRole("radio", { name: "Two ZIP versions" }));
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose the “before” ZIP");
    await userEvent.upload(screen.getByLabelText("Choose the before ZIP"), zip("v1.zip"));
    await userEvent.upload(screen.getByLabelText("Choose the after ZIP"), zip("v2.zip"));
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    await screen.findByText(/Reviewing/);
    const form = mock.calls.find((c) => c.method === "POST")!.body as FormData;
    expect([(form.get("before") as File).name, (form.get("after") as File).name]).toEqual(["v1.zip", "v2.zip"]);
  });

  it("explains when the server does not allow local repositories", async () => {
    vi.stubGlobal("fetch", routes({ "GET /api/health": { ...HEALTH, local_git: false } }).fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Review a change" }));
    expect(await screen.findByText(/does not allow reading local repositories/)).toBeInTheDocument();
    expect(screen.getByLabelText("Repository path on this computer")).toBeDisabled();
  });

  it("shows server-side rejections such as an unknown branch", async () => {
    const rejection = new Response(JSON.stringify({ detail: "Unknown or invalid git reference: 'mian'" }), { status: 422 });
    vi.stubGlobal("fetch", routes({ "POST /api/changes": rejection }).fn);
    renderAt("/");
    await userEvent.click(await screen.findByRole("tab", { name: "Review a change" }));
    await userEvent.type(screen.getByLabelText("Repository path on this computer"), "/srv/app");
    await userEvent.click(screen.getByRole("button", { name: "Start review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("'mian'");
  });
});

const PATCH = "@@ -8,5 +8,6 @@\n def format_name(first, last):\n-    return f\"{first} {last}\"\n+    return f\"{title} {first} {last}\"\n";

const IMPACT: Finding = finding({
  id: "CR-001",
  file: "shop/orders.py",
  start_line: 12,
  end_line: 12,
  category: "bug",
  severity: "high",
  title: "Call to format_name no longer matches its new signature",
  sources: ["ast"],
  rule_id: "IMPACT-SIGNATURE",
  cwe: null,
  related: ["shop/users.py:14 format_name(first, last, title) (changed)"],
});

const FIXED: Finding = finding({
  id: "CR-002",
  file: "shop/users.py",
  start_line: 3,
  end_line: 3,
  category: "quality",
  severity: "low",
  title: "Unused import os",
  sources: ["ruff"],
  rule_id: "F401",
  cwe: null,
  suggested_fix: {
    file: "shop/users.py",
    start_line: 3,
    end_line: 3,
    replacement: "",
    diff: "--- a/shop/users.py\n+++ b/shop/users.py\n@@ -3 +2,0 @@\n-import os\n",
    source: "ruff",
    verified: true,
    checks: ["ruff safe fix"],
  },
});

const CHANGE: ChangeReview = {
  summary: {
    base: "main (132b1d42)",
    head: "feature (702aec34)",
    files_changed: 1,
    lines_added: 6,
    lines_deleted: 8,
    symbols: [
      {
        file: "shop/users.py",
        qualname: "format_name",
        kind: "modified",
        line: 14,
        end_line: 15,
        signature_changed: true,
        old_signature: "format_name(first, last)",
        new_signature: "format_name(first, last, title)",
        callers: 1,
        callers_not_updated: 1,
      },
    ],
    salient: "shop/users.py::format_name",
    impacted_files: ["shop/orders.py"],
    narrative: "format_name now requires a title; one caller was not updated.",
  },
  files: [],
  hunks: [
    { file: "shop/users.py", start_line: 8, end_line: 15, score: 68, level: "high", reasons: ["breaks 1 call site(s) in other code"], patch: PATCH, finding_ids: ["CR-001"] },
    { file: "shop/users.py", start_line: 20, end_line: 21, score: 4, level: "low", reasons: [], patch: "@@ -20 +20 @@\n-x = 1\n+x = 2\n", finding_ids: [] },
  ],
};

const CHANGE_DETAIL: ReviewDetail = {
  job: job({ name: "shop: main -> feature", source_type: "change", change: { kind: "git", base: "main", head: "feature", repo_path: "/srv/shop" } }),
  result: { ...DETAIL.result!, findings: [IMPACT, FIXED], change: CHANGE },
};

describe("change review results", () => {
  it("renders the summary, impact warnings, changed functions and ranked hunks", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": CHANGE_DETAIL }).fn);
    renderAt("/reviews/abc123def456");
    expect(await screen.findByText("git: main → feature")).toBeInTheDocument();
    expect(screen.getByText(/one caller was not updated/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "SARIF" })).toHaveAttribute("href", "/api/reviews/abc123def456/report/sarif");

    const impact = screen.getByRole("heading", { name: "Breaks outside the diff (1)" }).closest("section")!;
    expect(within(impact).getByText("shop/orders.py:12")).toBeInTheDocument();

    const fns = screen.getByRole("heading", { name: "Changed functions" }).closest("section")!;
    expect(within(fns).getByText("format_name(first, last, title)")).toBeInTheDocument();

    const hunks = screen.getByRole("heading", { name: "Review these hunks first" }).closest("section")!;
    const items = within(hunks).getAllByRole("listitem").filter((li) => li.parentElement?.tagName === "OL");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("High risk");
    expect(within(items[0]).getByLabelText(/Diff of shop\/users.py lines 8-15/)).toHaveTextContent("+ return f\"{title}");
  });

  it("shows related locations and a verified fix inside a finding", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": CHANGE_DETAIL }).fn);
    renderAt("/reviews/abc123def456");
    expect(await screen.findByText("verified fix")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Expand CR-002" }));
    expect(screen.getByText("Verified fix")).toBeInTheDocument();
    expect(screen.getByLabelText("Suggested fix for shop/users.py")).toHaveTextContent("-import os");
    await userEvent.click(screen.getByRole("button", { name: "Expand CR-001" }));
    expect(screen.getByText(/format_name\(first, last, title\) \(changed\)/)).toBeInTheDocument();
  });
});

describe("change helpers", () => {
  it("diff view marks added and removed lines", () => {
    render(<DiffView diff={"--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n c"} />);
    const lines = screen.getByLabelText("Code diff").querySelectorAll("[data-diff]");
    expect([...lines].map((l) => l.getAttribute("data-diff"))).toEqual(["header", "header", "@", "-", "+", " "]);
  });

  it("separates impact findings and explains fix status", () => {
    expect(impactFindings([IMPACT, FIXED]).map((f) => f.id)).toEqual(["CR-001"]);
    expect(fixStatus(FIXED.suggested_fix!).label).toBe("Verified fix");
    expect(fixStatus({ ...FIXED.suggested_fix!, verified: false, source: "llm" }).text).toMatch(/no tool can confirm/);
  });
});

describe("partial LLM results", () => {
  it("warns prominently when the LLM could not review some parts", async () => {
    const partial: ReviewDetail = {
      ...DETAIL,
      result: {
        ...DETAIL.result!,
        errors: ["[snippet.py:1-2] LLM review failed: groq daily quota reached for model m: try again in about 4 min"],
        stats: { ...DETAIL.result!.stats, units_failed: 1, units_total: 3 },
      },
    };
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": partial }).fn);
    renderAt("/reviews/abc123def456");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("The LLM could not review 1 of 3 part(s): results are partial");
    expect(banner).toHaveTextContent("daily quota reached");
    expect(banner).not.toHaveTextContent("[snippet.py");
  });

  it("shows no warning for a complete review", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/llm/status": LLM_READY, "GET /api/reviews/abc123def456": DETAIL }).fn);
    renderAt("/reviews/abc123def456");
    await screen.findByRole("heading", { name: /planted.zip/ });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("timing breakdown", () => {
  it("formats the review's time per component", async () => {
    const { timingRow } = await import("../pages/ReviewDetail");
    const row = timingRow({
      total_sec: 12.42, static_analysis_sec: 2.31, rag_index_sec: 0.5, rag_retrieval_sec: 0.34,
      llm_inference_sec: 7.91, llm_calls: 4, llm_rate_limit_wait_sec: 1.5, validation_sec: 0.72,
      report_generation_sec: 0.19, other_sec: 0.45,
    });
    expect(row).toEqual([
      "Time",
      "total 12.42s · static analysis 2.31s · RAG 0.84s · LLM 7.91s (4 calls) · validation 0.72s · reports 0.19s · other 0.45s · of which quota waiting 1.50s",
    ]);
    expect(timingRow(undefined)).toBeNull();
  });
});
