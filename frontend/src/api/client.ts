import type {
  BeforeAfterTable,
  BenchmarkDetail,
  BenchmarkRun,
  EvaluationSummary,
  ExperimentDetail,
  ExperimentRun,
  JobInfo,
  LLMProviderName,
  LLMStatus,
  PerformanceRecord,
  ReviewDetail,
  ReviewOptions,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

// The server only reads a local git repository when this header is present: a custom header
// cannot be sent cross-site without a CORS preflight, so other websites cannot trigger it.
const CLIENT_HEADER = { "X-Marl-Client": "dashboard" };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { ...CLIENT_HEADER, ...(init?.headers ?? {}) } });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Is `python -m marl_agents.cli serve` running?");
  }
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (Array.isArray(body?.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** "?a=1&b=2" from the non-empty values, or "" when there are none. */
function query(params: Record<string, string | null | undefined>): string {
  const pairs = Object.entries(params).filter((e): e is [string, string] => !!e[1]);
  return pairs.length ? `?${new URLSearchParams(pairs).toString()}` : "";
}

export type ReviewInput =
  | { kind: "file"; file: File }
  | { kind: "snippet"; code: string; filename: string };

export type ChangeInput =
  | { kind: "git"; repoPath: string; target: "working" | "staged" | "refs"; base: string; head: string }
  | { kind: "zips"; before: File; after: File };

export type ReportFormat = "json" | "md" | "pdf" | "sarif";

export const api = {
  health: () =>
    request<{ status: string; jobs: number; running: number; local_git?: boolean }>("/api/health"),
  llmStatus: (probe = false, provider?: LLMProviderName | null) =>
    request<LLMStatus>(`/api/llm/status${query({ probe: probe ? "true" : null, provider })}`),
  llmModels: (provider?: LLMProviderName | null) =>
    request<{ models: string[]; default: string | null }>(`/api/llm/models${query({ provider })}`),
  listReviews: () => request<JobInfo[]>("/api/reviews"),
  getReview: (id: string) => request<ReviewDetail>(`/api/reviews/${encodeURIComponent(id)}`),
  deleteReview: (id: string) =>
    request<void>(`/api/reviews/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createReview: (input: ReviewInput, options: ReviewOptions) => {
    const form = new FormData();
    if (input.kind === "file") form.append("file", input.file);
    else {
      form.append("snippet", input.code);
      form.append("snippet_name", input.filename);
    }
    form.append("options", JSON.stringify(options));
    return request<JobInfo>("/api/reviews", { method: "POST", body: form });
  },
  createChangeReview: (input: ChangeInput, options: ReviewOptions) => {
    const form = new FormData();
    if (input.kind === "zips") {
      form.append("before", input.before);
      form.append("after", input.after);
    } else {
      form.append("repo_path", input.repoPath.trim());
      if (input.target === "staged") form.append("staged", "true");
      if (input.target === "refs") {
        if (input.base.trim()) form.append("base", input.base.trim());
        form.append("head", input.head.trim() || "HEAD");
      } else if (input.base.trim()) form.append("base", input.base.trim());
    }
    form.append("options", JSON.stringify(options));
    return request<JobInfo>("/api/changes", { method: "POST", body: form });
  },
  reportUrl: (id: string, fmt: ReportFormat) =>
    `/api/reviews/${encodeURIComponent(id)}/report/${fmt}`,
  listExperiments: () => request<ExperimentRun[]>("/api/experiments"),
  getExperiment: (name: string) =>
    request<ExperimentDetail>(`/api/experiments/${encodeURIComponent(name)}`),
  evaluationSummary: () => request<EvaluationSummary>("/api/evaluation/summary"),
  performanceReviews: () => request<PerformanceRecord[]>("/api/performance/reviews"),
  performanceReview: (id: string) =>
    request<{ record: PerformanceRecord; spans: unknown[] }>(`/api/performance/reviews/${encodeURIComponent(id)}`),
  benchmarks: () => request<BenchmarkRun[]>("/api/performance/benchmarks"),
  benchmark: (name: string) => request<BenchmarkDetail>(`/api/performance/benchmarks/${encodeURIComponent(name)}`),
  beforeAfter: () => request<BeforeAfterTable>("/api/evaluation/before-after"),
  resumeReview: (id: string) => request<JobInfo>(`/api/reviews/${encodeURIComponent(id)}/resume`, { method: "POST" }),
};
