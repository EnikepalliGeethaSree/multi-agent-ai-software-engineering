// Mirrors the backend models (marl_agents.core.schemas, api.jobs, reports.summary).

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

export type Category =
  | "bug"
  | "security"
  | "quality"
  | "maintainability"
  | "error_handling"
  | "edge_case"
  | "performance"
  | "testing"
  | "standards"
  | "documentation";

export type Source = "llm" | "ruff" | "radon" | "ast" | "mypy";

export interface SuggestedFix {
  file: string;
  start_line: number;
  end_line: number;
  replacement: string;
  diff: string;
  source: string; // "ruff" | "llm"
  verified: boolean;
  checks: string[];
}

export interface Finding {
  id: string;
  file: string;
  start_line: number;
  end_line: number;
  category: Category;
  severity: Severity;
  title: string;
  description: string;
  evidence: string[];
  recommendation: string | null;
  test_recommendation: string | null;
  confidence: number;
  sources: Source[];
  rule_id: string | null;
  cwe: string | null;
  symbol: string | null;
  proposed_severity: Severity | null;
  notes: string[];
  related?: string[];
  suggested_fix?: SuggestedFix | null;
}

export interface RunMetadata {
  agent: string;
  provider: string;
  model: string | null;
  temperature: number | null;
  prompt_versions: Record<string, string>;
  rag_enabled: boolean;
  started_at: string;
  finished_at: string | null;
}

export interface ReviewResult {
  agent: string;
  findings: Finding[];
  rejected_findings: number;
  errors: string[];
  metadata: RunMetadata;
  files_analyzed: number;
  lines_analyzed: number;
  stats: Record<string, unknown>;
  change?: ChangeReview | null;
}

export interface ReviewSummary {
  files_analyzed: number;
  lines_analyzed: number;
  total_findings: number;
  by_severity: Record<Severity, number>;
  by_category: Partial<Record<Category, number>>;
  by_source: Record<string, number>;
  potential_bugs: number;
  security_issues: number;
  error_handling_issues: number;
  maintainability_issues: number;
  testing_gaps: number;
  documentation_issues: number;
  weighted_density_per_kloc: number;
  top_files: [string, number][];
  llm_rejection_rate: number | null;
}

export type Mode = "full" | "static_only" | "llm_only";
export type JobStatus = "queued" | "running" | "done" | "failed";

export interface ReviewOptions {
  mode: Mode;
  rag_enabled: boolean;
  structural_context: boolean;
  model: string | null;
  min_confidence: number;
  include_tests: boolean;
  suggest_fixes?: boolean;
}

export interface JobInfo {
  id: string;
  name: string;
  source_type: "zip" | "file" | "snippet" | "change";
  status: JobStatus;
  options: ReviewOptions;
  change?: ChangeSpec | null;
  provider: string | null;
  model: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: string[];
  error: string | null;
  summary: ReviewSummary | null;
  performance?: PerformanceRecord | null;
  resumable?: boolean;
  failed_units?: string[];
}

export interface LLMCallTiming {
  label: string | null;
  latency_s: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  ok: boolean;
  retry: boolean;
  error_kind: string | null;
}

/** Null always means "not measured". It is never a stand-in for zero. */
export interface PerformanceRecord {
  review_id: string;
  file_name: string;
  created_at: string;
  status: "complete" | "partial" | "failed";
  run_type: "cold" | "warm";
  provider: string | null;
  model: string | null;
  file_size_kb: number | null;
  lines_of_code: number | null;
  files_reviewed: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  thinking_tokens: number | null;
  review_units: number | null;
  llm_calls: number | null;
  llm_failed_calls: number | null;
  llm_calls_detail?: LLMCallTiming[];
  file_ingestion_sec: number | null;
  parsing_sec: number | null;
  ast_call_graph_sec: number | null;
  static_analysis_sec: number | null;
  rag_retrieval_sec: number | null;
  rag_index_sec: number | null;
  prompt_construction_sec: number | null;
  llm_inference_sec: number | null;
  llm_quota_wait_sec: number | null;
  evidence_validation_sec: number | null;
  dedup_severity_sec: number | null;
  validation_sec: number | null;
  fix_generation_sec: number | null;
  classifier_sec: number | null;
  report_generation_sec: number | null;
  total_sec: number | null;
  failed_stages: string[];
  findings: number | null;
  failed_units: number | null;
  skipped_units: number | null;
  units_from_cache: number | null;
  units_deduplicated: number | null;
  classifier_skipped_units: number | null;
  message: string | null;
  resets_at: string | null;
}

export interface BenchmarkStat {
  category: string;
  run_type: string;
  runs: number;
  complete: number;
  partial: number;
  failed: number;
  skipped: number;
  mean_sec: number | null;
  median_sec: number | null;
  p95_sec: number | null;
  min_sec: number | null;
  max_sec: number | null;
  mean_llm_inference_sec: number | null;
  mean_rag_retrieval_sec: number | null;
  mean_static_analysis_sec: number | null;
  mean_input_tokens: number | null;
  mean_output_tokens: number | null;
  mean_findings: number | null;
  mean_review_chunks: number | null;
  skipped_chunks: number;
}

export interface BenchmarkRun {
  name: string;
  started_at: string | null;
  git_commit: string | null;
  mode: string;
  rag: boolean;
  repeats: number;
  pipeline_check_only: boolean;
  conditions: { provider: string | null; model: string | null; date: string; api_conditions: string };
  results: BenchmarkStat[];
}

export interface BenchmarkRow {
  file_name: string;
  category: string;
  repeat: number;
  run_type: string;
  status: string;
  total_sec: number | null;
  file_size_kb: number | null;
  lines_of_code: number | null;
  input_tokens: number | null;
}

export interface BenchmarkDetail {
  name: string;
  metrics: unknown;
  runs: BenchmarkRow[];
}

export interface BeforeAfterRow {
  benchmark: string;
  metric: string;
  original: number | null;
  improved: number | null;
  original_run: string | null;
  improved_run: string | null;
  n: number | null;
  note: string | null;
  higher_is_better: boolean | null;
}

export interface BeforeAfterTable {
  rows: BeforeAfterRow[];
  notes: string[];
}

export interface ReviewDetail {
  job: JobInfo;
  result: ReviewResult | null;
}

export interface LLMStatus {
  provider: string;
  model: string | null;
  requests_per_minute: number | null;
  tokens_per_minute: number | null;
  requests_per_day?: number | null;
  tokens_per_day?: number | null;
  free_tier?: boolean;
  data_notice?: string | null;
  quota?: {
    requests_used: number;
    requests_limit: number | null;
    tokens_used: number;
    tokens_limit: number | null;
    resets_at: string;
  } | null;
  classifier?: { enabled: boolean; mode: string; model_dir: string | null } | null;
  ready: boolean;
  error: string | null;
  probe?: { ok: boolean; latency_ms?: number; error?: string };
}

export interface ExperimentConfiguration {
  key: string;
  letter: string | null;
  label: string;
  static: boolean;
  llm: boolean;
  rag: boolean;
  mode: string;
}

/** Configuration of a saved run, derived from its meta.json / config.yaml by the API. */
export interface ExperimentInfo {
  configuration: ExperimentConfiguration | null;
  model: string | null;
  samples: number | null;
  evaluated: number | null;
  failed: number | null;
  group_id: string | null;
  repeat: number | null;
  recorded: boolean;
}

export interface ExperimentRun {
  name: string;
  started_at: string | null;
  model: string | null;
  provider: string | null;
  errors: number;
  headline: Record<string, string | number | null> & { kind: string };
  experiment?: ExperimentInfo | null;
}

// ---- baseline comparison (GET /api/evaluation/summary) ---------------------------------------

export interface MetricDefinition {
  key: string;
  name: string;
  definition: string;
  scale: string;
  higher_is_better: boolean | null;
}

export interface ComparisonColumn {
  key: string;
  label: string;
  metric: string | null;
  group: string | null;
  digits: number;
}

export interface ComparisonRow {
  label: string;
  configuration: ExperimentConfiguration | null;
  status: "ok" | "not_run" | "incomplete";
  values: Record<string, number | null>;
  sd: Record<string, number | null>;
  spread: Record<string, (number | null)[]>;
  na: Record<string, string>;
  n: number | null;
  n_failed: number | null;
  n_runs: number;
  model: string | null;
  run_ids: string[];
  notes: string[];
  how_to_run: string | null;
}

export interface FairnessCheck {
  name: string;
  ok: boolean | null;
  detail: string;
}

export interface ComparisonTable {
  id: string;
  section: string;
  title: string;
  about: string;
  columns: ComparisonColumn[];
  rows: ComparisonRow[];
  conditions: Record<string, unknown>;
  fairness: FairnessCheck[];
  observations: string[];
  notes: string[];
  supplementary: boolean;
  show_counts: boolean;
}

export interface EvaluationSummary {
  generated_at: string;
  master: ComparisonTable | null;
  tables: ComparisonTable[];
  definitions: MetricDefinition[];
  scope: string[];
}

export interface ExperimentDetail {
  name: string;
  metrics: Record<string, unknown>;
  meta: Record<string, unknown>;
  summary_md: string;
}

// ---- change (pull request / diff) review ----------------------------------------------------

export interface ChangedFile {
  path: string;
  status: "added" | "modified" | "deleted" | "renamed";
  old_path: string | null;
  added: number;
  deleted: number;
  changed_ranges: [number, number][];
  patch: string;
}

export interface ChangedSymbol {
  file: string;
  qualname: string;
  kind: "added" | "modified" | "removed";
  line: number | null;
  end_line: number | null;
  signature_changed: boolean;
  old_signature: string | null;
  new_signature: string | null;
  callers: number;
  callers_not_updated: number;
}

export interface HunkRisk {
  file: string;
  start_line: number;
  end_line: number;
  score: number;
  level: "high" | "medium" | "low";
  reasons: string[];
  patch: string;
  finding_ids: string[];
}

export interface ChangeSummary {
  base: string;
  head: string;
  files_changed: number;
  lines_added: number;
  lines_deleted: number;
  symbols: ChangedSymbol[];
  salient: string | null;
  impacted_files: string[];
  narrative: string | null;
}

export interface ChangeReview {
  summary: ChangeSummary;
  files: ChangedFile[];
  hunks: HunkRisk[];
}

export interface ChangeSpec {
  kind: "git" | "zips";
  base: string;
  head: string;
  repo_path: string | null;
}
