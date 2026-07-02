import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import { ConnectionPill } from "@/components/ConnectionPill";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/Button";
import { healthApi } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthContext";
import { useToast } from "@/lib/toast/ToastContext";
import { checkLabel, isCheckHealthy } from "@/lib/readiness";
import { useStreamStatus } from "@/lib/stream/StreamProvider";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/alerts": "Alerts",
  "/response": "Response Center",
  "/reports": "Reports",
  "/ingestion": "Ingestion",
  "/system": "System",
  "/admin/users": "Users",
};

function activeTitle(pathname: string): string {
  if (pathname.startsWith("/alerts/")) return "Alert detail";
  return TITLES[pathname] ?? "SentinelAI";
}

export function Topbar() {
  const { pathname } = useLocation();
  const path = pathname;
  const title = activeTitle(path);
  const { user, logout } = useAuth();
  const { connected: live } = useStreamStatus();
  const navigate = useNavigate();
  const toast = useToast();
  const { t } = useTranslation();

  async function handleLogout() {
    await logout();
    toast.info("Signed out.");
    navigate("/login", { replace: true });
  }

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
  const checks = readyQ.data?.checks;

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
          ok={!readyQ.isError && isCheckHealthy(checks?.database)}
          label="Database"
          value={checkLabel(checks?.database, readyQ.isError ? "down" : "…")}
        />
        <ConnectionPill
          ok={!readyQ.isError && isCheckHealthy(checks?.redis)}
          label="Redis"
          value={checkLabel(checks?.redis, readyQ.isError ? "down" : "…")}
        />
        <ConnectionPill
          ok={!readyQ.isError && isCheckHealthy(checks?.model)}
          label="Model"
          value={checkLabel(checks?.model, readyQ.isError ? "down" : "…")}
        />
        <ConnectionPill
          ok={live}
          label="Live"
          value={live ? "on" : "off"}
        />

        <LanguageSwitcher />

        {user && (
          <div className="ml-2 flex items-center gap-2 border-l border-slate-800 pl-3">
            <div className="text-right leading-tight">
              <p className="text-xs font-medium text-slate-200">{user.username}</p>
              <p className="text-[10px] uppercase tracking-wider text-slate-500">
                {user.role}
              </p>
            </div>
            <Button size="sm" variant="ghost" onClick={handleLogout}>
              {t("topbar.signOut")}
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}
