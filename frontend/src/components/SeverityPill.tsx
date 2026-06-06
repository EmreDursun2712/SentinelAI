import type { Severity } from "@/lib/types";
import { cn } from "@/lib/cn";

const CLASS: Record<Severity, string> = {
  LOW: "bg-blue-500/10 text-blue-300 ring-blue-500/30",
  MEDIUM: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  HIGH: "bg-orange-500/10 text-orange-300 ring-orange-500/30",
  CRITICAL: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};

export function SeverityPill({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-700/40 px-2 py-0.5 text-xs font-medium text-slate-400 ring-1 ring-inset ring-slate-700">
        UNRATED
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        CLASS[severity],
      )}
    >
      {severity}
    </span>
  );
}
