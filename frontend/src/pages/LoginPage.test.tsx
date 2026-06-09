import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    authApi: {
      me: vi.fn().mockRejectedValue(new Error("401")),
      login: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    },
  };
});

import LoginPage from "./LoginPage";
import { renderWithProviders } from "@/test/utils";

describe("LoginPage", () => {
  beforeEach(() => vi.clearAllMocks());

  test("renders the sign-in form with labelled fields", async () => {
    renderWithProviders(<LoginPage />, { route: "/login" });

    // Wait for the initial /me probe to settle (loading → unauthenticated).
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument(),
    );

    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /sentinelai/i })).toBeInTheDocument();
  });
});
