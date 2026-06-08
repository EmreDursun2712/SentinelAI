// Hand-written DTO aliases used across the app. The **source of truth** is the
// backend OpenAPI schema, generated into ./api/schema.d.ts via
// `npm run generate:api-types` (CI verifies it's up to date). Prefer the
// generated `Schemas[...]` types for new code; these aliases are kept for
// ergonomics and are migrated to the generated types over time.

import type { components } from "@/lib/api/schema";

/** All response/request schemas generated from the backend OpenAPI spec. */
export type Schemas = components["schemas"];

// ----- Auth ---------------------------------------------------------------

export type Role = "VIEWER" | "ANALYST" | "ADMIN";

export interface AuthUser {
  username: string;
  role: Role;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: AuthUser;
}

// ----- Drift monitoring ---------------------------------------------------

export type DriftStatus = "OK" | "WATCH" | "DRIFT";

export interface DriftFeature {
  psi: number;
  sample_count: number;
}

export interface DriftConfidenceStats {
  count: number;
  mean: number | null;
  min: number | null;
  max: number | null;
  p95: number | null;
}

export interface DriftSnapshot {
  id: number;
  model_version_id: number | null;
  window_start: string;
  window_end: string;
  sample_count: number;
  feature_drift: Record<string, DriftFeature>;
  prediction_distribution: Record<string, unknown>;
  confidence_stats: DriftConfidenceStats;
  drift_score: number | null;
  status: DriftStatus;
  created_at: string;
}

export interface DriftReport {
  available: boolean;
  reason: string | null;
  model_name: string | null;
  model_version: string | null;
  snapshot: DriftSnapshot | null;
}

export interface DriftHistory {
  items: DriftSnapshot[];
}

// ----- Live sensor --------------------------------------------------------

export interface SensorStatus {
  live: boolean;
  last_event_at: string | null;
  events_recent: number;
  total_events: number;
  live_window_seconds: number;
}

// ----- Enums --------------------------------------------------------------

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export type AlertStatus =
  | "NEW"
  | "TRIAGED"
  | "AUTO_RESPONDED"
  | "AWAITING_ANALYST"
  | "INVESTIGATED"
  | "REPORTED"
  | "CLOSED";

export type AlertDisposition =
  | "OPEN"
  | "UNDER_REVIEW"
  | "CONFIRMED"
  | "FALSE_POSITIVE"
  | "RESOLVED";

export type AgentName =
  | "DETECTION"
  | "TRIAGE"
  | "RESPONSE"
  | "INVESTIGATION"
  | "REPORTING"
  | "ANALYST";

export type ResponseActionType =
  | "BLOCK_IP"
  | "RATE_LIMIT"
  | "ISOLATE_HOST"
  | "NOTIFY_ANALYST"
  | "NO_ACTION"
  | "ESCALATE"
  | "ISOLATE_ALERT"
  | "SUPPRESS_ALERT"
  | "CREATE_TICKET";

export type ResponseStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXECUTED";

export type ExecutionMode = "SIMULATED" | "LAB";
export type RollbackStatus =
  | "NOT_REQUIRED"
  | "AVAILABLE"
  | "ROLLED_BACK"
  | "FAILED";

export type IngestionKind = "REPLAY" | "STREAM";
export type IngestionStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";

export type IncidentKind = "PER_ALERT" | "DAILY_SUMMARY";

// ----- Alerts -------------------------------------------------------------

export interface Alert {
  id: number;
  src_ip: string;
  dst_ip: string;
  src_port: number | null;
  dst_port: number | null;
  protocol: string | null;
  prediction: string;
  confidence: number;
  severity: Severity | null;
  priority: number | null;
  status: AlertStatus;
  disposition: AlertDisposition;
  event_id: number | null;
  model_version_id: number | null;
  notes: string | null;
  triaged_at: string | null;
  responded_at: string | null;
  investigated_at: string | null;
  reported_at: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AgentDecision {
  id: number;
  agent: AgentName;
  decision: Record<string, unknown>;
  reasoning: Record<string, unknown>;
  latency_ms: number | null;
  created_at: string;
}

export interface ResponseActionOut {
  id: number;
  alert_id: number;
  decision_id: number | null;
  action_type: ResponseActionType;
  simulated: boolean;
  status: ResponseStatus;
  executed: boolean;
  approval_required: boolean;
  approved_by: string | null;
  rejection_reason: string | null;
  payload: Record<string, unknown>;
  executed_at: string | null;
  execution_mode: ExecutionMode;
  executor_name: string | null;
  external_execution_id: string | null;
  expires_at: string | null;
  rollback_status: RollbackStatus;
  rollback_payload: Record<string, unknown> | null;
  execution_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertDetail extends Alert {
  decisions: AgentDecision[];
  actions: ResponseActionOut[];
}

export interface AlertStats {
  total: number;
  by_status: Record<string, number>;
  by_severity: Record<string, number>;
  by_disposition: Record<string, number>;
  by_prediction: Record<string, number>;
}

export interface AlertTimeseriesPoint {
  bucket: string;
  LOW: number;
  MEDIUM: number;
  HIGH: number;
  CRITICAL: number;
  UNRATED: number;
  total: number;
}

export interface AlertTimeseries {
  bucket: string;
  period_hours: number;
  points: AlertTimeseriesPoint[];
}

export interface DashboardOverview {
  total_events: number;
  suspicious_events: number;
  open_alerts: number;
  critical_alerts: number;
  high_alerts: number;
  pending_actions: number;
  alerts: AlertStats;
}

// ----- Triage / disposition -----------------------------------------------

export interface TriageOut {
  alert_id: number;
  severity: Severity;
  priority: number;
  recent_count: number;
  component_weights: Record<string, number>;
  factors: Record<string, unknown>;
  explanations: string[];
}

export interface UpdateDispositionBody {
  disposition: AlertDisposition;
  note?: string;
  analyst_id?: string;
}

// ----- Detection / model --------------------------------------------------

export interface ModelInfo {
  loaded: boolean;
  name?: string | null;
  version?: string | null;
  algorithm?: string | null;
  classes: string[];
  feature_order: string[];
  metrics_summary: Record<string, number>;
  artifact_dir?: string | null;
  loaded_at?: string | null;
  db_id?: number | null;
  is_active?: boolean | null;
  threshold?: number | null;
  benign_label?: string | null;
}

export interface DetectionRunSummary {
  processed: number;
  alerts_created: number;
  benign_count: number;
  by_label: Record<string, number>;
  model_name: string;
  model_version: string;
}

// ----- Ingestion ----------------------------------------------------------

export interface RowError {
  row_number: number;
  message: string;
}

export interface IngestionSummary {
  job_id: number;
  status: IngestionStatus;
  source: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  errors: RowError[];
  errors_truncated: boolean;
}

export interface IngestionJob {
  id: number;
  kind: IngestionKind;
  source: string;
  status: IngestionStatus;
  rate_limit: number | null;
  records_total: number | null;
  records_done: number;
  records_failed: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

// ----- Investigation ------------------------------------------------------

export interface RelatedAlertOut {
  id: number;
  src_ip: string;
  dst_ip: string;
  src_port: number | null;
  dst_port: number | null;
  protocol: string | null;
  prediction: string;
  severity: Severity | null;
  priority: number | null;
  confidence: number;
  created_at: string;
}

export interface RelatedEventOut {
  id: number;
  event_time: string;
  src_ip: string;
  dst_ip: string;
  src_port: number | null;
  dst_port: number | null;
  protocol: string | null;
  label: string | null;
}

export interface TimelineItem {
  timestamp: string;
  kind: "event" | "alert";
  summary: string;
  src_ip?: string | null;
  dst_ip?: string | null;
  label?: string | null;
  prediction?: string | null;
  severity?: Severity | null;
  alert_id?: number | null;
  is_current_alert?: boolean;
}

export interface InvestigationStatistics {
  related_event_count: number;
  related_alert_count: number;
  distinct_source_ips: number;
  distinct_destination_ips: number;
  same_src_ip_alert_count: number;
  same_dst_ip_alert_count: number;
  same_family_alert_count: number;
  first_seen: string | null;
  last_seen: string | null;
  activity_span_seconds: number | null;
  top_label: string | null;
  top_prediction: string | null;
}

export interface FeatureImportanceItem {
  feature: string;
  importance: number;
}

export interface InvestigationPacket {
  alert_id: number;
  generated_at: string;
  events_window_minutes: number;
  alerts_window_hours: number;
  summary: string;
  summary_bullets: string[];
  statistics: InvestigationStatistics;
  related_alerts: RelatedAlertOut[];
  related_events: RelatedEventOut[];
  timeline: TimelineItem[];
  feature_importance: FeatureImportanceItem[];
  model_name?: string | null;
  model_version?: string | null;
  truncated: boolean;
}

export interface InvestigationEnvelope {
  artifact_id: number;
  packet: InvestigationPacket;
}

// ----- Reports ------------------------------------------------------------

export interface IncidentReportListItem {
  id: number;
  kind: IncidentKind;
  alert_id: number | null;
  title: string;
  period_start: string | null;
  period_end: string | null;
  md_path: string | null;
  pdf_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReportEnvelope {
  report_id: number;
  packet: Record<string, unknown> & { markdown: string };
}

export interface GenericReportOut {
  id: number;
  kind: IncidentKind;
  alert_id: number | null;
  title: string;
  md_path: string | null;
  pdf_path: string | null;
  created_at: string;
  updated_at: string;
  packet: Record<string, unknown> & { markdown?: string };
}

// ----- Tasks (background jobs) --------------------------------------------

export type TaskKind =
  | "DETECTION_RUN"
  | "REPORT_ALERT"
  | "DAILY_SUMMARY"
  | "DRIFT_RUN"
  | "RETENTION_CLEANUP"
  | "ML_RETRAIN";

export type TaskStatus = "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface Task {
  id: string;
  kind: TaskKind;
  status: TaskStatus;
  progress: number;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface TaskList {
  items: Task[];
}

// ----- Health -------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
}

export interface DependencyCheck {
  status: string; // ok | down | skipped | loaded | unavailable
  required?: boolean;
  backend?: string;
  name?: string | null;
  version?: string | null;
}

export interface ReadyzResponse {
  status: "ready" | "not_ready";
  version: string;
  checks: {
    database: DependencyCheck;
    redis: DependencyCheck;
    model: DependencyCheck;
  };
}
