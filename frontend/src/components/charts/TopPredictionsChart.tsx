import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/ui/EmptyState";

import {
  CHART_AXIS_COLOR,
  CHART_GRID_COLOR,
  CHART_TEXT_COLOR,
  CHART_TOOLTIP_STYLE,
} from "./chartTheme";

interface Props {
  byPrediction: Record<string, number>;
  /** How many families to show — the rest are bucketed into "Other". */
  topN?: number;
}

// A deterministic palette per category — order in the bar chart maps to color
// rotation, but the actual color per category stays stable across renders.
const PALETTE = [
  "#f97316", // orange
  "#ef4444", // rose
  "#eab308", // amber
  "#3b82f6", // blue
  "#10b981", // emerald
  "#8b5cf6", // violet
  "#ec4899", // pink
] as const;

function colorFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return PALETTE[hash % PALETTE.length];
}

export function TopPredictionsChart({ byPrediction, topN = 6 }: Props) {
  const entries = Object.entries(byPrediction)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) {
    return (
      <EmptyState
        title="No attack categories yet"
        description="Categories appear once detection labels its first alerts."
      />
    );
  }

  const head = entries.slice(0, topN);
  const tail = entries.slice(topN);
  const data = [
    ...head.map(([name, value]) => ({ name, value })),
    ...(tail.length > 0
      ? [{ name: "Other", value: tail.reduce((acc, [, v]) => acc + v, 0) }]
      : []),
  ];

  const summary = `Top attack categories by alert count: ${data
    .map((d) => `${d.name} ${d.value}`)
    .join(", ")}.`;

  return (
    <figure className="m-0" aria-label={summary}>
      <figcaption className="sr-only">{summary}</figcaption>
      <div aria-hidden="true">
    <ResponsiveContainer width="100%" height={260}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 5, right: 16, left: 0, bottom: 0 }}
        barCategoryGap={6}
      >
        <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="2 4" horizontal={false} />
        <XAxis
          type="number"
          stroke={CHART_AXIS_COLOR}
          tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID_COLOR }}
          allowDecimals={false}
        />
        <YAxis
          type="category"
          dataKey="name"
          stroke={CHART_AXIS_COLOR}
          tick={{ fill: CHART_TEXT_COLOR, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: CHART_GRID_COLOR }}
          width={110}
        />
        <Tooltip
          contentStyle={CHART_TOOLTIP_STYLE}
          labelStyle={{ color: "#94a3b8" }}
          cursor={{ fill: "rgba(148, 163, 184, 0.07)" }}
        />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} isAnimationActive={false}>
          {data.map((d) => (
            <Cell
              key={d.name}
              fill={d.name === "Other" ? "#475569" : colorFor(d.name)}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
      </div>
    </figure>
  );
}
