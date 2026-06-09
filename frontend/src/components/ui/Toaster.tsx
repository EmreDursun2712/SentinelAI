import { CloseIcon } from "@/components/icons";
import { cn } from "@/lib/cn";
import type { Toast, ToastKind } from "@/lib/toast/ToastContext";

const KIND_STYLES: Record<ToastKind, string> = {
  success: "border-emerald-500/40 bg-emerald-950/80 text-emerald-100",
  error: "border-rose-500/40 bg-rose-950/80 text-rose-100",
  warning: "border-amber-500/40 bg-amber-950/80 text-amber-100",
  info: "border-sky-500/40 bg-sky-950/80 text-sky-100",
};

const KIND_GLYPH: Record<ToastKind, string> = {
  success: "✓",
  error: "✕",
  warning: "!",
  info: "i",
};

const KIND_LABEL: Record<ToastKind, string> = {
  success: "Success",
  error: "Error",
  warning: "Warning",
  info: "Information",
};

interface ToasterProps {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}

/**
 * Fixed top-right toast stack. The container is an aria-live region so screen
 * readers announce new toasts; errors/warnings use role="alert" (assertive) and
 * success/info use role="status" (polite).
 */
export function Toaster({ toasts, onDismiss }: ToasterProps) {
  return (
    <div
      aria-live="polite"
      aria-relevant="additions"
      className="pointer-events-none fixed right-4 top-4 z-[100] flex w-full max-w-sm flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.kind === "error" || t.kind === "warning" ? "alert" : "status"}
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-md border px-4 py-3 shadow-lg backdrop-blur",
            KIND_STYLES[t.kind],
          )}
        >
          <span
            aria-hidden="true"
            className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-xs font-bold"
          >
            {KIND_GLYPH[t.kind]}
          </span>
          <div className="min-w-0 flex-1">
            <span className="sr-only">{KIND_LABEL[t.kind]}: </span>
            {t.title && <p className="text-sm font-semibold">{t.title}</p>}
            <p className="text-sm leading-snug break-words">{t.message}</p>
          </div>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss notification"
            className="shrink-0 rounded text-current/70 transition hover:text-current focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
