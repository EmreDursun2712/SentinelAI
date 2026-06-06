import type { GenericReportOut, IncidentKind, IncidentReportListItem } from "@/lib/types";
import { API_BASE, qs, request } from "./client";

export interface ListReportsParams {
  kind?: IncidentKind;
  alert_id?: number;
  limit?: number;
  offset?: number;
}

export function listReports(
  params: ListReportsParams = {},
): Promise<IncidentReportListItem[]> {
  return request<IncidentReportListItem[]>(`/reports${qs(params)}`);
}

export function getReport(id: number): Promise<GenericReportOut> {
  return request<GenericReportOut>(`/reports/${id}`);
}

/** Returns the raw markdown text. */
export async function getReportMarkdown(id: number): Promise<string> {
  const response = await fetch(`${API_BASE}/reports/${id}/markdown`);
  if (!response.ok) {
    throw new Error(`Markdown fetch failed: ${response.status}`);
  }
  return response.text();
}

export function runDailySummary(date?: string): Promise<{
  report_id: number;
  packet: Record<string, unknown>;
}> {
  return request<{ report_id: number; packet: Record<string, unknown> }>(
    "/reports/daily/run",
    { method: "POST", body: date ? { date } : {} },
  );
}
