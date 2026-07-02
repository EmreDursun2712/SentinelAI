import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import type { ComponentType, SVGProps } from "react";

import {
  AlertIcon,
  DashboardIcon,
  DocumentIcon,
  IngestionIcon,
  ReportIcon,
  ResponseIcon,
  ServerIcon,
  ShieldIcon,
} from "@/components/icons";
import { useAuth } from "@/lib/auth/AuthContext";
import { cn } from "@/lib/cn";

interface NavItem {
  to: string;
  /** i18n key under `nav.*`. */
  labelKey: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  end?: boolean;
}

const NAV: readonly NavItem[] = [
  { to: "/", labelKey: "nav.dashboard", icon: DashboardIcon, end: true },
  { to: "/alerts", labelKey: "nav.alerts", icon: AlertIcon },
  { to: "/response", labelKey: "nav.response", icon: ResponseIcon },
  { to: "/reports", labelKey: "nav.reports", icon: ReportIcon },
  { to: "/ingestion", labelKey: "nav.ingestion", icon: IngestionIcon },
  { to: "/system", labelKey: "nav.system", icon: ServerIcon },
];

// Shown only to admins.
const ADMIN_NAV: readonly NavItem[] = [
  { to: "/audit", labelKey: "nav.audit", icon: DocumentIcon },
  { to: "/admin/users", labelKey: "nav.users", icon: ShieldIcon },
];

export function Sidebar() {
  const { hasRole } = useAuth();
  const { t } = useTranslation();
  const items = hasRole("ADMIN") ? [...NAV, ...ADMIN_NAV] : NAV;
  return (
    <aside
      aria-label="Sidebar"
      className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60"
    >
      <div className="border-b border-slate-800 p-5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/30">
            <ShieldIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-slate-500">
              {t("app.name")}
            </p>
            <h1 className="text-sm font-semibold text-slate-100">{t("app.subtitle")}</h1>
          </div>
        </div>
      </div>

      <nav aria-label="Primary" className="flex-1 space-y-0.5 p-3">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950",
                isActive
                  ? "bg-slate-800 text-white shadow-inner"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100",
              )
            }
          >
            <item.icon className="h-4 w-4" aria-hidden="true" />
            <span>{t(item.labelKey)}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-800 p-4 text-[11px] leading-relaxed text-slate-600">
        <p className="text-slate-500">
          <span className="font-semibold text-slate-400">Ethics:</span>{" "}
          Simulated response only.
        </p>
        <p className="mt-1">No external systems are contacted.</p>
      </div>
    </aside>
  );
}
