// Maps a WebSocket event type to the TanStack Query keys that should be
// invalidated. Pure and prefix-based so it's trivially unit-testable and stays
// in sync with the query keys used across the app.

export interface QueryInvalidator {
  invalidateQueries: (filters: { queryKey: readonly unknown[] }) => void;
}

/** Query-key prefixes to invalidate for a given event type. */
export function streamInvalidationKeys(type: string): string[][] {
  // Connection/heartbeat frames carry no data — nothing to refetch.
  if (!type || type.startsWith("stream.")) return [];

  // Task lifecycle updates only affect the tasks views (no dashboard impact).
  if (type.startsWith("task.")) return [["tasks"]];

  // Almost everything else affects the dashboard aggregates.
  const keys: string[][] = [["dashboard"]];

  if (type.startsWith("alert.")) {
    keys.push(["alerts"], ["alert"]);
  }
  if (type.startsWith("response.")) {
    keys.push(["response"], ["alert"]);
  }
  if (type.startsWith("report.")) {
    keys.push(["reports"]);
  }
  if (type.startsWith("ingestion.")) {
    keys.push(["ingest"]); // ingestion-job queries use the "ingest" prefix
  }
  if (type.startsWith("detection.")) {
    keys.push(["alerts"], ["detection"]);
  }
  return keys;
}

export function applyStreamInvalidation(qc: QueryInvalidator, type: string): void {
  for (const queryKey of streamInvalidationKeys(type)) {
    qc.invalidateQueries({ queryKey });
  }
}
