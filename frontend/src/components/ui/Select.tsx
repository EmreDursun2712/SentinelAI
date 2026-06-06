import type { SelectHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
}

export function Select({ label, className, children, ...rest }: SelectProps) {
  return (
    <label className="inline-flex flex-col gap-1 text-xs text-slate-400">
      {label && <span className="font-medium uppercase tracking-wider">{label}</span>}
      <select
        className={cn(
          "rounded-md border border-slate-700 bg-slate-900/60 px-2.5 py-1.5 text-sm text-slate-200",
          "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
    </label>
  );
}
