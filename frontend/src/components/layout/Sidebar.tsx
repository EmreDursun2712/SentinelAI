import { NavLink } from "react-router-dom";
import type { ComponentType, SVGProps } from "react";

import {
  AlertIcon,
  DashboardIcon,
  IngestionIcon,
  ReportIcon,
  ResponseIcon,
  ShieldIcon,
} from "@/components/icons";
import { cn } from "@/lib/cn";

interface NavItem {
  to: string;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  end?: boolean;
}

const NAV: readonly NavItem[] = [
  { to: "/", label: "Dashboard", icon: DashboardIcon, end: true },
  { to: "/alerts", label: "Alerts", icon: AlertIcon },
  { to: "/response", label: "Response Center", icon: ResponseIcon },
  { to: "/reports", label: "Reports", icon: ReportIcon },
  { to: "/ingestion", label: "Ingestion", icon: IngestionIcon },
];

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-900/60">
      <div className="border-b border-slate-800 p-5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-400 ring-1 ring-emerald-500/30">
            <ShieldIcon className="h-5 w-5" />
          </span>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-slate-500">
              SentinelAI
            </p>
            <h1 className="text-sm font-semibold text-slate-100">IDS Console</h1>
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 p-3">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition",
                isActive
                  ? "bg-slate-800 text-white shadow-inner"
                  : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100",
              )
            }
          >
            <item.icon className="h-4 w-4" />
            <span>{item.label}</span>
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
