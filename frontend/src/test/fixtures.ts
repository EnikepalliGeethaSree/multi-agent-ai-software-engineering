import type { Finding, JobInfo, LLMStatus, ReviewDetail, ReviewSummary } from "../api/types";

export const finding = (over: Partial<Finding> = {}): Finding => ({
  id: "CR-001",
  file: "shop/db.py",
  start_line: 15,
  end_line: 15,
  category: "security",
  severity: "high",
  title: "SQL injection via f-string",
  description: "User input is formatted into the query.",
  evidence: ["query = f\"SELECT * FROM users WHERE name = '{username}'\""],
  recommendation: "Use parameterised queries.",
  test_recommendation: "Pass ' OR '1'='1 and assert it is treated as data.",
  confidence: 0.9,
  sources: ["ruff", "llm"],
  rule_id: "S608",
  cwe: "CWE-89",
  symbol: "find_user",
  proposed_severity: "critical",
  notes: ["rule:S608", "llm: confirmed"],
  ...over,
});

export const FINDINGS: Finding[] = [
  finding(),
  finding({
    id: "CR-002",
    file: "shop/pricing.py",
    start_line: 42,
    end_line: 42,
    category: "edge_case",
    severity: "medium",
    title: "ZeroDivisionError on empty list",
    sources: ["llm"],
    rule_id: null,
    cwe: null,
    confidence: 0.72,
    proposed_severity: null,
    notes: [],
  }),
  finding({
    id: "CR-003",
    file: "shop/db.py",
    start_line: 3,
    end_line: 3,
    category: "quality",
    severity: "low",
    title: "F401: `os` imported but unused",
    sources: ["ruff"],
    rule_id: "F401",
    cwe: null,
    confidence: 0.9,
    proposed_severity: null,
    notes: [],
  }),
];

export const SUMMARY: ReviewSummary = {
  files_analyzed: 5,
  lines_analyzed: 146,
  total_findings: 3,
  by_severity: { critical: 0, high: 1, medium: 1, low: 1, info: 0 },
  by_category: { security: 1, edge_case: 1, quality: 1 },
  by_source: { ruff: 2, llm: 2 },
  potential_bugs: 1,
  security_issues: 1,
  error_handling_issues: 0,
  maintainability_issues: 1,
  testing_gaps: 0,
  documentation_issues: 0,
  weighted_density_per_kloc: 51.4,
  top_files: [
    ["shop/db.py", 5.5],
    ["shop/pricing.py", 2],
  ],
  llm_rejection_rate: 0.1,
};

export const job = (over: Partial<JobInfo> = {}): JobInfo => ({
  id: "abc123def456",
  name: "planted.zip",
  source_type: "zip",
  status: "done",
  options: { mode: "full", rag_enabled: true, structural_context: true, model: null, min_confidence: 0.3, include_tests: false },
  provider: "groq",
  model: "openai/gpt-oss-120b",
  created_at: "2026-09-29T19:00:00Z",
  started_at: "2026-09-29T19:00:01Z",
  finished_at: "2026-09-29T19:01:10Z",
  progress: ["19:00:01 review started", "19:01:10 done: 3 findings"],
  error: null,
  summary: SUMMARY,
  ...over,
});

export const DETAIL: ReviewDetail = {
  job: job(),
  result: {
    agent: "code_review",
    findings: FINDINGS,
    rejected_findings: 1,
    errors: [],
    metadata: {
      agent: "code_review",
      provider: "groq",
      model: "openai/gpt-oss-120b",
      temperature: 0,
      prompt_versions: { system: "1.0", review: "1.0" },
      rag_enabled: true,
      started_at: "2026-09-29T19:00:01Z",
      finished_at: "2026-09-29T19:01:10Z",
    },
    files_analyzed: 5,
    lines_analyzed: 146,
    stats: {
      mode: "full",
      files_reviewed: 5,
      lines_reviewed: 146,
      static_findings_raw: { ruff: 14, radon: 1 },
      units_total: 4,
      units_failed: 0,
      llm_findings_raw: 10,
      llm_findings_valid: 9,
      llm_rejected_by_reason: { evidence_not_found: 1 },
      llm_rejection_rate: 0.1,
      llm_repaired: 0,
      static_assessments: { confirm: 15 },
      context_items_by_reason: { similar: 20, readme: 4 },
      avg_context_items_per_unit: 6,
      llm_usage: { calls: 4, input_tokens: 8305, output_tokens: 6934, parse_retries: 0 },
      dedup_merged: 12,
      filtered_low_confidence: 0,
      timings_s: { static_analysis: 0.1, llm_review: 65.1 },
    },
  },
};

export const LLM_READY: LLMStatus = {
  provider: "groq",
  model: "openai/gpt-oss-120b",
  requests_per_minute: 30,
  tokens_per_minute: 6000,
  ready: true,
  error: null,
};

export const LLM_MISSING: LLMStatus = {
  provider: "mock",
  model: null,
  requests_per_minute: null,
  tokens_per_minute: null,
  ready: false,
  error: "No LLM configured (mock provider): only static analysis is useful.",
};

/** Route-based fetch mock: { "GET /api/x": body | (init) => body }. */
export function mockFetch(routes: Record<string, unknown>) {
  const calls: { method: string; url: string; body?: BodyInit | null }[] = [];
  const fn = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    calls.push({ method, url, body: init?.body });
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.split(" ");
      return m === method && (url === p || url.startsWith(p + "?"));
    });
    if (!key) return new Response(JSON.stringify({ detail: `no mock for ${method} ${url}` }), { status: 404 });
    const value = routes[key];
    const body = typeof value === "function" ? (value as (i?: RequestInit) => unknown)(init) : value;
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { fn, calls };
}
