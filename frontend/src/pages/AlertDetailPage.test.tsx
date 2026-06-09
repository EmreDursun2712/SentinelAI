import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import type { AlertDetail } from "@/lib/types";

const { ALERT } = vi.hoisted(() => ({
  ALERT: {
    id: 1,
    src_ip: "10.0.0.5",
    dst_ip: "10.0.0.9",
    src_port: 54321,
    dst_port: 443,
    protocol: "TCP",
    prediction: "DDoS",
    confidence: 0.97,
    severity: "HIGH",
    priority: 88.5,
    status: "TRIAGED",
    disposition: "OPEN",
    event_id: 10,
    model_version_id: 2,
    notes: null,
    triaged_at: "2026-01-01T00:00:00Z",
    responded_at: null,
    investigated_at: null,
    reported_at: null,
    closed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    decisions: [
      {
        id: 1,
        agent: "DETECTION",
        decision: { predicted_label: "DDoS", confidence: 0.97 },
        reasoning: { class_probabilities: { BENIGN: 0.03, DDoS: 0.97 } },
        latency_ms: 5,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    actions: [],
  } as AlertDetail,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    authApi: { me: vi.fn().mockRejectedValue(new Error("401")) },
    alertsApi: {
      getAlert: vi.fn().mockResolvedValue(ALERT),
    },
    investigationApi: {
      getAlertInvestigation: vi.fn().mockRejectedValue(new Error("404")),
    },
  };
});

import AlertDetailPage from "./AlertDetailPage";
import { renderWithProviders } from "@/test/utils";

describe("AlertDetailPage", () => {
  beforeEach(() => vi.clearAllMocks());

  test("renders alert detail from mocked data", async () => {
    renderWithProviders(<AlertDetailPage />, { route: "/alerts/1", path: "/alerts/:id" });

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /Alert #1/ })).toBeInTheDocument(),
    );
    // Network identity + analyst action bar are present.
    expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
    expect(screen.getByText(/analyst disposition/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm threat/i })).toBeInTheDocument();
  });
});
