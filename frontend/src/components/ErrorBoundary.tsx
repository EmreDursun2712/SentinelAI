import { Component, type ErrorInfo, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { reportClientError } from "@/lib/api/telemetry";

interface Props {
  children: ReactNode;
  /** Render a compact, inline fallback (page-level) instead of the full screen. */
  inline?: boolean;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time errors in its subtree, logs them to the console, and
 * best-effort reports them to the backend. Shows a recovery UI with "Reload"
 * and "Go to dashboard" actions so a single broken view never bricks the app.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always visible in the console for local debugging.
    console.error("ErrorBoundary caught an error:", error, info.componentStack);
    reportClientError({
      message: error.message,
      stack: error.stack,
      component_stack: info.componentStack ?? undefined,
    });
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    const body = (
      <div
        role="alert"
        className="mx-auto flex max-w-md flex-col items-center gap-4 rounded-lg border border-rose-900/50 bg-rose-950/30 p-6 text-center"
      >
        <h2 className="text-lg font-semibold text-rose-200">Something went wrong</h2>
        <p className="text-sm text-slate-400">
          This view hit an unexpected error. You can reload, or head back to the dashboard.
        </p>
        {import.meta.env.DEV && (
          <pre className="max-h-32 w-full overflow-auto rounded bg-slate-950/60 p-2 text-left text-[11px] text-rose-300">
            {error.message}
          </pre>
        )}
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => window.location.reload()}>
            Reload
          </Button>
          <Button variant="secondary" onClick={() => window.location.assign("/")}>
            Go to dashboard
          </Button>
        </div>
      </div>
    );

    if (this.props.inline) {
      return <div className="py-10">{body}</div>;
    }
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
        {body}
      </div>
    );
  }
}

/**
 * Page-level boundary that resets automatically on navigation (keyed by path),
 * so leaving the broken route clears the error without a full reload.
 */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <ErrorBoundary key={location.pathname} inline>
      {children}
    </ErrorBoundary>
  );
}
