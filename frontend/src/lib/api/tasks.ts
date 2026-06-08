import type { Task, TaskList } from "@/lib/types";
import { qs, request } from "./client";

/** List background tasks (own; admins see all). */
export function listTasks(params: { limit?: number; status?: string; kind?: string } = {}): Promise<TaskList> {
  return request<TaskList>(`/tasks${qs(params)}`);
}

/** Fetch a single task by id. */
export function getTask(id: string): Promise<Task> {
  return request<Task>(`/tasks/${encodeURIComponent(id)}`);
}

/** Enqueue a background detection run; returns the created task. */
export function runDetection(limit = 1000): Promise<Task> {
  return request<Task>("/tasks/detection-run", { method: "POST", body: { limit } });
}

/** Enqueue a background drift check. */
export function runDrift(windowHours = 24): Promise<Task> {
  return request<Task>("/tasks/drift-run", { method: "POST", body: { window_hours: windowHours } });
}

/** Enqueue the daily summary report. */
export function runDailySummary(): Promise<Task> {
  return request<Task>("/tasks/daily-summary", { method: "POST" });
}
