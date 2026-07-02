import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "@/App";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { shouldRetry } from "@/lib/api/errors";
import { AuthProvider } from "@/lib/auth/AuthContext";
import { ConfirmProvider } from "@/lib/confirm/ConfirmProvider";
import "@/lib/i18n";
import { StreamProvider } from "@/lib/stream/StreamProvider";
import { ToastProvider } from "@/lib/toast/ToastContext";
import "@/styles/globals.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Don't retry client errors (401/403/429/…); a 429 retry would only make
      // the rate limit worse. Other failures get a single retry.
      retry: shouldRetry,
      staleTime: 30_000,
    },
  },
});

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ToastProvider>
            <ConfirmProvider>
              <AuthProvider>
                <StreamProvider>
                  <App />
                </StreamProvider>
              </AuthProvider>
            </ConfirmProvider>
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
