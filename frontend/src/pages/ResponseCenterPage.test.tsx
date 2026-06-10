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
        total_events: 0,
        suspicious_events: 0,
        open_alerts: 0,
        critical_alerts: 0,
        high_alerts: 0,
        pending_actions: 0,
        alerts: { total: 0, by_status: {}, by_severity: {}, by_disposition: {}, by_prediction: {} },
      }),
    },
    responseApi: {
      listResponseActions: vi.fn().mockResolvedValue([]),
      listResponseActionsPage: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    },
  };
});

import ResponseCenterPage from "./ResponseCenterPage";
import { renderWithProviders } from "@/test/utils";

describe("ResponseCenterPage", () => {
  beforeEach(() => vi.clearAllMocks());

  test("renders the queue and the empty state when there is nothing pending", async () => {
    renderWithProviders(<ResponseCenterPage />);

    expect(screen.getByRole("heading", { name: /response center/i })).toBeInTheDocument();
    expect(screen.getByText(/pending queue/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/no pending actions/i)).toBeInTheDocument());
  });
});
