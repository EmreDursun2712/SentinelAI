import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  CHART_AXIS_COLOR,
  CHART_GRID_COLOR,
  CHART_TOOLTIP_STYLE,
} from "@/components/charts/chartTheme";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Spinner } from "@/components/ui/Spinner";
import { detectionApi } from "@/lib/api";
import { formatNumber } from "@/lib/format";

/**
 * Reliability diagram for the active model: binned mean confidence vs. empirical
 * accuracy. A well-calibrated model hugs the dashed diagonal — points below it
 * are over-confident, above are under-confident. Sourced from the calibration
 * block written at train time (`--calibrate sigmoid`) and the multiclass Brier
 * score. Only meaningful once a calibrated model is active.
 */
export function CalibrationCard() {
  const modelQ = useQuery({
    queryKey: ["detection", "model"],
    queryFn: detectionApi.getModelInfo,
    refetchInterval: 60_000,
  });

  const cal = modelQ.data?.calibration ?? null;
  const curve = cal?.reliability_curve;
  const globalThreshold = modelQ.data?.threshold ?? null;
  const classThresholds = Object.entries(modelQ.data?.class_thresholds ?? {});

  const data =
    curve && curve.mean_confidence.length
      ? curve.mean_confidence
          .map((c, i) => ({
            confidence: Number(c.toFixed(3)),
            accuracy: curve.accuracy[i],
            count: curve.count[i],
          }))
          .sort((a, b) => a.confidence - b.confidence)
      : [];

  return (
    <Card padding="none">
      <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">Calibration</h3>
          {cal && (
            <Badge tone={cal.calibrated ? "success" : "neutral"}>
              {cal.calibrated ? cal.method : "uncalibrated"}
            </Badge>
          )}
        </div>
        {cal && (
          <span className="text-xs text-slate-400">
            Brier <span className="font-mono text-slate-200">{formatNumber(cal.brier_score, 4)}</span>
          </span>
        )}
      </div>

      <div className="p-5">
        {modelQ.isLoading ? (
          <div className="flex justify-center py-6 text-slate-400">
            <Spinner />
          </div>
        ) : data.length === 0 ? (
          <EmptyState
            title="No calibration data"
            description="Train the active model with --calibrate sigmoid to get a reliability curve."
          />
        ) : (
          <>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
                  <CartesianGrid stroke={CHART_GRID_COLOR} strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    dataKey="confidence"
                    domain={[0, 1]}
                    ticks={[0, 0.25, 0.5, 0.75, 1]}
                    stroke={CHART_AXIS_COLOR}
                    tick={{ fontSize: 11, fill: CHART_AXIS_COLOR }}
                    label={{
                      value: "confidence",
                      position: "insideBottom",
                      offset: -2,
                      fontSize: 10,
                      fill: CHART_AXIS_COLOR,
                    }}
                  />
                  <YAxis
                    type="number"
                    domain={[0, 1]}
                    ticks={[0, 0.25, 0.5, 0.75, 1]}
                    stroke={CHART_AXIS_COLOR}
                    tick={{ fontSize: 11, fill: CHART_AXIS_COLOR }}
                  />
                  <Tooltip
                    contentStyle={CHART_TOOLTIP_STYLE}
                    formatter={(v: number, name: string) => [formatNumber(v, 3), name]}
                    labelFormatter={(l) => `confidence ${formatNumber(Number(l), 3)}`}
                  />
                  {/* Perfect-calibration diagonal (accuracy == confidence). */}
                  <Line
                    type="linear"
                    dataKey="confidence"
                    name="perfect"
                    stroke="#475569"
                    strokeDasharray="4 4"
                    dot={false}
                    isAnimationActive={false}
                  />
                  {/* The model's actual reliability curve. */}
                  <Line
                    type="monotone"
                    dataKey="accuracy"
                    name="model"
                    stroke="#22c55e"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-2 text-[11px] text-slate-500">
              Green = observed accuracy per confidence bin; dashed = perfect calibration.
              Closer to the diagonal is better.
            </p>
          </>
        )}

        {globalThreshold != null && (
          <div className="mt-3 border-t border-slate-800 pt-2 text-[11px] text-slate-500">
            <span className="uppercase tracking-widest">Alert thresholds</span>{" "}
            <span className="font-mono text-slate-300">global {globalThreshold.toFixed(2)}</span>
            {classThresholds.length > 0 && (
              <span>
                {" · "}
                {classThresholds.map(([cls, t]) => (
                  <span key={cls} className="ml-1">
                    <span className="text-slate-400">{cls}</span>{" "}
                    <span className="font-mono text-amber-300">{t.toFixed(2)}</span>
                  </span>
                ))}
              </span>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
