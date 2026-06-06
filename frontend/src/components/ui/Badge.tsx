import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type BadgeTone =
  | "default"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "neutral"
  | "indigo";

interface BadgeProps {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}

const TONE_CLASS: Record<BadgeTone, string> = {
  default: "bg-slate-800 text-slate-200 ring-slate-700",
  info: "bg-blue-500/10 text-blue-300 ring-blue-500/30",
  success: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  warning: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  danger: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
  neutral: "bg-slate-700/40 text-slate-400 ring-slate-700",
  indigo: "bg-indigo-500/10 text-indigo-300 ring-indigo-500/30",
};

export function Badge({ children, tone = "default", className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
