import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/ui/EmptyState";
import type { AlertTimeseriesPoint } from "@/lib/types";

import {
  CHART_AXIS_COLOR,
  CHART_GRID_COLOR,
  CHART_TEXT_COLOR,
  CHART_TOOLTIP_STYLE,
  SEVERITY_COLOR,
} from "./chartTheme";

interface Props {
  points: AlertTimeseriesPoint[];
}

const STACK_ORDER: ReadonlyArray<keyof typeof SEVERITY_COLOR> = [
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
  "UNRATED",
] as const;

function fmtHour(bucket: string): string {
  const d = new Date(bucket);
  if (isNaN(d.getTime())) return bucket;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  return `${hh}:00`;
}

export function AlertsOverTimeChart({ points }: Props) {
  const totalAcrossWindow = points.reduce((acc, p) => acc + p.total, 0);

  if (totalAcrossWindow === 0) {
    return (
      <EmptyState
        title="No alerts in the selected window"
        description="Ingest a CSV and run detection to populate this chart."
      />
    );
  }

  const data = points.map((p) => ({ ...p, _label: fmtHour(p.bucket) }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <AreaChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
        <defs>
          {STACK_ORDER.map((sev) => (
            <linearGradient
              key={sev}
              id={`grad-${sev}`}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop
                offset="0%"
                stopColor={SEVERITY_COLOR[sev]}
                stopOpacity={0.55}
              />
              <stop
                offset="100%"
                stopColor={SEVERITY_COLOR[sev]}
                stopOpacity={0.05}
              />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="2 4" />
        <XAxis
          dataKey="_label"
          stroke={CHART_AXIS_COLOR}
          tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID_COLOR }}
          interval="preserveStartEnd"
          minTickGap={20}
        />
        <YAxis
          stroke={CHART_AXIS_COLOR}
          tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID_COLOR }}
          allowDecimals={false}
          width={32}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={{ color: "#94a3b8" }}
          cursor={{ stroke: CHART_GRID_COLOR, strokeWidth: 1 }}
        />
        <Legend
          wrapperStyle={{ fontSize: 11, color: CHART_TEXT_COLOR }}
          iconType="circle"
        />
        {STACK_ORDER.map((sev) => (
          <Area
            key={sev}
            type="monotone"
            dataKey={sev}
            stackId="severity"
            stroke={SEVERITY_COLOR[sev]}
            strokeWidth={1.5}
            fill={`url(#grad-${sev})`}
            isAnimationActive={false}
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}
