import { cn } from "@/lib/cn";

interface ConnectionPillProps {
  ok: boolean;
  label: string;
  value?: string;
}

/** A compact "Backend: ok" / "Stream: offline" indicator for the topbar. */
export function ConnectionPill({ ok, label, value }: ConnectionPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ring-1 ring-inset",
        ok
          ? "bg-emerald-500/5 text-emerald-300 ring-emerald-500/30"
          : "bg-rose-500/5 text-rose-300 ring-rose-500/30",
      )}
    >
      <span
        className={cn(
          "inline-block h-1.5 w-1.5 rounded-full",
          ok ? "bg-emerald-400" : "bg-rose-400",
        )}
      />
      <span className="font-medium">{label}</span>
      <span className="text-slate-500">·</span>
      <span className="text-slate-400">{value ?? (ok ? "online" : "offline")}</span>
    </span>
  );
}
