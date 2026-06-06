// Severity colors mirror the Tailwind palette used in SeverityPill so the
// charts and the pills speak the same visual language.

export const SEVERITY_COLOR: Record<
  "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | "UNRATED",
  string
> = {
  LOW: "#3b82f6",       // blue-500
  MEDIUM: "#eab308",    // amber-500
  HIGH: "#f97316",      // orange-500
  CRITICAL: "#ef4444",  // rose-500
  UNRATED: "#64748b",   // slate-500
};

export const CHART_AXIS_COLOR = "#475569";   // slate-600
export const CHART_GRID_COLOR = "#1e293b";   // slate-800
export const CHART_TEXT_COLOR = "#cbd5e1";   // slate-300

export const CHART_TOOLTIP_STYLE: Record<string, string | number> = {
  backgroundColor: "#0f172a",   // slate-950
  border: "1px solid #1e293b",
  borderRadius: 6,
  fontSize: 12,
  color: "#e2e8f0",
};
