import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    authApi: { me: vi.fn().mockRejectedValue(new Error("401")) },
    reportsApi: {
      listReports: vi.fn().mockResolvedValue([]),
      getReport: vi.fn(),
      runDailySummary: vi.fn(),
    },
    alertsApi: {
      listAlerts: vi.fn().mockResolvedValue({ items: [], total: 0 }),
      generateAlertReport: vi.fn(),
    },
  };
});

import ReportsPage from "./ReportsPage";
import { renderWithProviders } from "@/test/utils";

describe("ReportsPage", () => {
  beforeEach(() => vi.clearAllMocks());

  test("renders the reports page with the daily-summary action", async () => {
    renderWithProviders(<ReportsPage />);

    expect(screen.getByRole("heading", { name: /^Reports$/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /generate daily summary/i }),
    ).toBeInTheDocument();
    // The report list resolves (empty) without crashing.
    await waitFor(() => expect(screen.getByText(/daily summary/i)).toBeInTheDocument());
  });
});
