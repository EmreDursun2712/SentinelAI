import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import { EmptyState } from "@/components/ui/EmptyState";

import { CHART_TEXT_COLOR, CHART_TOOLTIP_STYLE, SEVERITY_COLOR } from "./chartTheme";

interface Props {
  bySeverity: Record<string, number>;
}

const ORDER: ReadonlyArray<keyof typeof SEVERITY_COLOR> = [
  "CRITICAL",
  "HIGH",
  "MEDIUM",
  "LOW",
  "UNRATED",
] as const;

export function SeverityDistributionChart({ bySeverity }: Props) {
  const data = ORDER.map((label) => ({
    name: label,
    value: bySeverity[label] ?? 0,
  })).filter((d) => d.value > 0);

  const total = data.reduce((acc, d) => acc + d.value, 0);

  if (total === 0) {
    return (
      <EmptyState
        title="No alerts yet"
        description="Severity distribution will appear once detection has produced alerts."
      />
    );
  }

  const summary = `Severity distribution of ${total} alert(s): ${data
    .map((d) => `${d.name} ${d.value} (${((d.value / total) * 100).toFixed(0)}%)`)
    .join(", ")}.`;

  return (
    <figure className="m-0" aria-label={summary}>
      <figcaption className="sr-only">{summary}</figcaption>
      <div aria-hidden="true">
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              innerRadius={55}
              outerRadius={90}
              paddingAngle={2}
              isAnimationActive={false}
              labelLine={false}
              stroke="#0f172a"
              strokeWidth={2}
            >
              {data.map((d) => (
                <Cell
                  key={d.name}
                  fill={SEVERITY_COLOR[d.name as keyof typeof SEVERITY_COLOR] ?? "#64748b"}
                />
              ))}
            </Pie>
            <Tooltip
              contentStyle={CHART_TOOLTIP_STYLE}
              labelStyle={{ color: "#94a3b8" }}
              formatter={(value: number, name: string) => [
                `${value} (${((value / total) * 100).toFixed(1)}%)`,
                name,
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: CHART_TEXT_COLOR }}
              iconType="circle"
              verticalAlign="bottom"
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
