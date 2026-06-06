import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Card } from "./ui/Card";

interface StatCardProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "danger" | "warning" | "success" | "info";
  className?: string;
}

const TONE: Record<NonNullable<StatCardProps["tone"]>, string> = {
  default: "text-slate-100",
  danger: "text-rose-300",
  warning: "text-amber-300",
  success: "text-emerald-300",
  info: "text-blue-300",
};

export function StatCard({ label, value, hint, tone = "default", className }: StatCardProps) {
  return (
    <Card className={className} padding="md">
      <p className="text-xs uppercase tracking-widest text-slate-500">{label}</p>
      <p className={cn("mt-2 text-2xl font-semibold", TONE[tone])}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </Card>
  );
}
