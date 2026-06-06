// Mirrors backend Pydantic schemas. Kept in sync by hand for the course project;
// can be replaced by an OpenAPI codegen step later.

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

// ----- Health -------------------------------------------------------------

export interface HealthResponse {
  status: string;
  version: string;
}

export interface ReadyzResponse {
  status: "ready" | "not_ready";
  db: "ok" | "down";
  version: string;
}
