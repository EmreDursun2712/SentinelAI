import type { ReactElement, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "@/lib/auth/AuthContext";
import { ConfirmProvider } from "@/lib/confirm/ConfirmProvider";
import { ToastProvider } from "@/lib/toast/ToastContext";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

interface Options {
  /** Initial router location. */
  route?: string;
  /** When set, render `ui` under a `<Route path>` so useParams works. */
  path?: string;
  client?: QueryClient;
}

/**
 * Render a component tree wrapped in the app's providers (Query, Router, Toast,
 * Confirm, Auth) for component/page tests. Mock `@/lib/api` and
 * `@/lib/stream/StreamProvider` in the test file as needed.
 */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/", path, client = makeQueryClient() }: Options = {},
): RenderResult & { client: QueryClient } {
  const tree: ReactNode = path ? (
    <Routes>
      <Route path={path} element={ui} />
    </Routes>
  ) : (
    ui
  );

  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <ConfirmProvider>
            <AuthProvider>{tree}</AuthProvider>
          </ConfirmProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, client };
}
