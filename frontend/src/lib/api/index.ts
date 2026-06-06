// Barrel: one import path for the whole service layer.
//
//     import { alertsApi, detectionApi } from "@/lib/api";
//     await alertsApi.listAlerts({ severity: "HIGH" });
//
// Also re-exports `health`/`readyz` and `ApiError` for legacy callers.

export { ApiError, API_BASE, API_ROOT } from "./client";

import * as alertsApi from "./alerts";
import * as authApi from "./auth";
import * as dashboardApi from "./dashboard";
import * as detectionApi from "./detection";
import * as healthApi from "./health";
import * as ingestionApi from "./ingestion";
import * as investigationApi from "./investigation";
import * as reportsApi from "./reports";
import * as responseApi from "./response";

export { alertsApi, authApi, dashboardApi, detectionApi, healthApi, ingestionApi, investigationApi, reportsApi, responseApi };

// Convenience re-exports.
export { health, readyz } from "./health";
