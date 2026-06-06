import type { IngestionJob, IngestionSummary, SensorStatus } from "@/lib/types";
import { qs, request } from "./client";

export function getSensorStatus(): Promise<SensorStatus> {
  return request<SensorStatus>("/ingest/sensor/status");
}

export function listIngestionJobs(limit = 50): Promise<IngestionJob[]> {
  return request<IngestionJob[]>(`/ingest/jobs${qs({ limit })}`);
}

export function getIngestionJob(id: number): Promise<IngestionJob> {
  return request<IngestionJob>(`/ingest/jobs/${id}`);
}

export function uploadCsv(file: File): Promise<IngestionSummary> {
  const form = new FormData();
  form.append("file", file);
  return request<IngestionSummary>("/ingest/upload", {
    method: "POST",
    body: form,
  });
}

export function replayCsv(file: string, rate = 50): Promise<IngestionSummary> {
  return request<IngestionSummary>("/ingest/replay", {
    method: "POST",
    body: { file, rate },
  });
}
