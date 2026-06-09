import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/stream/StreamProvider", () => ({
  StreamProvider: ({ children }: { children: React.ReactNode }) => children,
  useLiveInterval: () => false as const,
  useStreamStatus: () => ({ connected: false }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    authApi: { me: vi.fn().mockRejectedValue(new Error("401")) },
    dashboardApi: {
      getOverview: vi.fn().mockResolvedValue({
        total_events: 120,
        suspicious_events: 12,
        open_alerts: 5,
        critical_alerts: 1,
        high_alerts: 2,
        pending_actions: 3,
        alerts: { total: 12, by_status: {}, by_severity: {}, by_disposition: {}, by_prediction: {} },
      }),
    },
    alertsApi: {
      getAlertTimeseries: vi
        .fn()
        .mockResolvedValue({ bucket: "hour", period_hours: 24, points: [] }),
      listAlerts: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    },
    detectionApi: {
      getModelInfo: vi.fn().mockResolvedValue({
        loaded: false,
        classes: [],
        feature_order: [],
        metrics_summary: {},
      }),
      getLatestDrift: vi.fn().mockResolvedValue({
        available: false,
        reason: "no_snapshot",
        model_name: null,
        model_version: null,
        snapshot: null,
      }),
    },
  };
});

import DashboardPage from "./DashboardPage";
import { renderWithProviders } from "@/test/utils";

describe("DashboardPage", () => {
  beforeEach(() => vi.clearAllMocks());

  test("renders KPI cards from the overview", async () => {
    renderWithProviders(<DashboardPage />);

    expect(screen.getByRole("heading", { name: /^Dashboard$/ })).toBeInTheDocument();

    // KPI values resolve from the mocked overview.
    await waitFor(() => expect(screen.getByText("120")).toBeInTheDocument());
    expect(screen.getByText("Total events")).toBeInTheDocument();
    expect(screen.getByText("Open alerts")).toBeInTheDocument();
  });
});
