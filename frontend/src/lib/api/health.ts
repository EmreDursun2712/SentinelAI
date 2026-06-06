import type { HealthResponse, ReadyzResponse } from "@/lib/types";
import { rootRequest } from "./client";

/** Always 200 while the backend process is up. */
export function health(): Promise<HealthResponse> {
  return rootRequest<HealthResponse>("/health");
}

/** Returns 200 when ready, 503 when a dependency is down — both are valid soft states. */
export function readyz(): Promise<ReadyzResponse> {
  return rootRequest<ReadyzResponse>("/readyz", {}, [200, 503]);
}
