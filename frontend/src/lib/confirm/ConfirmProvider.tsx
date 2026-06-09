import {
  createContext,
  useCallback,
  useContext,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";

export interface ConfirmOptions {
  title: string;
  message?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  /** Require a free-text reason; the result carries it back. */
  requireReason?: boolean;
  reasonLabel?: string;
  reasonPlaceholder?: string;
  /** Require the user to type this exact phrase before confirming (e.g. "CONFIRM"). */
  typedConfirmation?: string;
}

export interface ConfirmResult {
  confirmed: boolean;
  reason?: string;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<ConfirmResult>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface PendingState {
  opts: ConfirmOptions;
  resolve: (r: ConfirmResult) => void;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingState | null>(null);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const reasonId = useId();
  const typedId = useId();
  const resolverRef = useRef<((r: ConfirmResult) => void) | null>(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    setReason("");
    setTyped("");
    return new Promise<ConfirmResult>((resolve) => {
      resolverRef.current = resolve;
      setPending({ opts, resolve });
    });
  }, []);

  const settle = useCallback((result: ConfirmResult) => {
    resolverRef.current?.(result);
    resolverRef.current = null;
    setPending(null);
  }, []);

  const cancel = useCallback(() => settle({ confirmed: false }), [settle]);

  const opts = pending?.opts;
  const needsReason = Boolean(opts?.requireReason);
  const needsTyped = Boolean(opts?.typedConfirmation);
  const reasonOk = !needsReason || reason.trim().length > 0;
  const typedOk = !needsTyped || typed.trim() === opts?.typedConfirmation;
  const canConfirm = reasonOk && typedOk;

  const onConfirm = () => {
    if (!canConfirm) return;
    settle({ confirmed: true, reason: needsReason ? reason.trim() : undefined });
  };

  const value = useMemo(() => confirm, [confirm]);

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      <Modal
        open={pending !== null}
        onClose={cancel}
        title={opts?.title ?? ""}
        footer={
          <>
            <Button variant="ghost" onClick={cancel}>
              {opts?.cancelLabel ?? "Cancel"}
            </Button>
            <Button
              variant={opts?.tone === "danger" ? "danger" : "primary"}
              onClick={onConfirm}
              disabled={!canConfirm}
            >
              {opts?.confirmLabel ?? "Confirm"}
            </Button>
          </>
        }
      >
        {opts?.message && (
          <div className="text-sm text-slate-300">{opts.message}</div>
        )}

        {needsTyped && (
          <div className="mt-4 space-y-1.5">
            <label htmlFor={typedId} className="block text-xs font-medium text-slate-400">
              Type <span className="font-mono text-slate-200">{opts?.typedConfirmation}</span> to
              confirm
            </label>
            <input
              id={typedId}
              type="text"
              value={typed}
              autoComplete="off"
              onChange={(e) => setTyped(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              placeholder={opts?.typedConfirmation}
            />
          </div>
        )}

        {needsReason && (
          <div className="mt-4 space-y-1.5">
            <label htmlFor={reasonId} className="block text-xs font-medium text-slate-400">
              {opts?.reasonLabel ?? "Reason"} <span className="text-rose-400">*</span>
            </label>
            <textarea
              id={reasonId}
              value={reason}
              required
              aria-required="true"
              aria-invalid={!reasonOk}
              rows={3}
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
              placeholder={opts?.reasonPlaceholder ?? "Why are you taking this action?"}
            />
          </div>
        )}
      </Modal>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (ctx === null) {
    throw new Error("useConfirm must be used within a <ConfirmProvider>.");
  }
  return ctx;
}
