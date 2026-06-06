import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { ConnectionPill } from "@/components/ConnectionPill";
import { healthApi } from "@/lib/api";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/alerts": "Alerts",
  "/response": "Response Center",
  "/reports": "Reports",
  "/ingestion": "Ingestion",
};

function activeTitle(pathname: string): string {
  if (pathname.startsWith("/alerts/")) return "Alert detail";
  return TITLES[pathname] ?? "SentinelAI";
}

export function Topbar() {
  const { pathname } = useLocation();
  const path = pathname;
  const title = activeTitle(path);

  const healthQ = useQuery({
    queryKey: ["topbar", "health"],
    queryFn: healthApi.health,
    refetchInterval: 30_000,
  });
  const readyQ = useQuery({
    queryKey: ["topbar", "readyz"],
    queryFn: healthApi.readyz,
    refetchInterval: 30_000,
  });

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-800 bg-slate-950/60 px-6">
      <div>
        <p className="text-[10px] uppercase tracking-widest text-slate-600">
          Section
        </p>
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
      </div>

      <div className="flex items-center gap-2">
        <ConnectionPill
          ok={!healthQ.isError && healthQ.data?.status === "ok"}
          label="Backend"
          value={healthQ.data?.status ?? (healthQ.isError ? "down" : "…")}
        />
        <ConnectionPill
          ok={!readyQ.isError && readyQ.data?.db === "ok"}
          label="Database"
          value={readyQ.data?.db ?? (readyQ.isError ? "down" : "…")}
        />
      </div>
    </header>
  );
}
