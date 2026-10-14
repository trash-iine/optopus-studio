// How each run's best objective improved, from the trajectory the worker reports.
import { useMemo, useState } from "react";
import { axis, GRID, tooltip, useEChart } from "../charts";
import type { RunFinished, RunSummary } from "../generated/server-event";
import { CHROME, compact, type Mode, slotColor } from "../theme";
import { Legend } from "./Legend";

export type Axis = "time" | "iteration";

/** The run's incumbent as a step curve, from its start to its end. */
export function curve(run: RunFinished, by: Axis): [number, number][] {
  const points = run.trajectory as unknown as [number, number, number][];
  const x = (t: number, i: number) => (by === "time" ? t : i);
  return [
    [0, run.initial_objective],
    ...points.map(([t, i, objective]): [number, number] => [x(t, i), objective]),
    [x(run.total_time_secs, run.iterations), run.best_objective],
  ];
}

/** What a run is called: its heuristic and its number within it when there are several. */
export function runLabel(summary: RunSummary, run: RunFinished): string {
  if (summary.variants.length <= 1) return `run ${run.run}`;
  const within = summary.runs.filter((r) => r.variant === run.variant).indexOf(run);
  return `${summary.variants[run.variant] ?? "?"} #${within + 1}`;
}

export function runColor(mode: Mode, summary: RunSummary, run: number): string {
  // Several heuristics: a run takes its heuristic's color, so the legend reads by heuristic.
  if (summary.variants.length > 1) return slotColor(mode, summary.runs[run]?.variant ?? 0);
  // Up to eight runs keep their own color; past that only the best run stands out.
  if (summary.runs.length <= 8) return slotColor(mode, run);
  return run === summary.best_run ? slotColor(mode, 0) : CHROME[mode].axis;
}

export function legendEntries(mode: Mode, summary: RunSummary): [string, string][] {
  if (summary.variants.length > 1) return summary.variants.map((v, i) => [v, slotColor(mode, i)]);
  if (summary.runs.length > 8) return [];
  return summary.runs.map((r) => [runLabel(summary, r), runColor(mode, summary, r.run)]);
}

export interface Series {
  name: string;
  color: string;
  data: [number, number][];
  emphasized?: boolean;
  /** The run under way, drawn dashed until it finishes. */
  live?: boolean;
}

/** The run under way as a series, on the time axis only: progress carries no iteration. */
export function liveSeries(mode: Mode, summary: RunSummary, by: Axis): Series[] {
  const live = summary.live;
  if (!live || by !== "time" || live.points.length === 0) return [];
  const points = live.points as unknown as [number, number][];
  const label = summary.variants.length > 1 ? summary.variants[live.variant] : `run ${live.run}`;
  const color =
    summary.variants.length > 1 ? slotColor(mode, live.variant) : runColor(mode, summary, live.run);
  return [{ name: `${label} (running)`, color, data: points, live: true }];
}

export function ConvergenceChart({
  series,
  by,
  higherIsBetter,
  mode,
}: {
  series: Series[];
  by: Axis;
  higherIsBetter: boolean | null;
  mode: Mode;
}) {
  const option = useMemo(() => {
    const direction = higherIsBetter ? "higher is better" : "lower is better";
    return {
      grid: { ...GRID, left: 64 },
      tooltip: tooltip(mode, {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: CHROME[mode].axis } },
        valueFormatter: (v: number) => compact(v),
      }),
      xAxis: axis(mode, {
        type: "value",
        name: by === "time" ? "seconds" : "iteration",
        nameLocation: "middle",
        nameGap: 26,
        splitLine: { show: false },
        axisLabel: { color: CHROME[mode].muted, formatter: (v: number) => compact(v) },
      }),
      yAxis: axis(mode, {
        type: "value",
        scale: true,
        name: `objective (${direction})`,
        nameLocation: "end",
        axisLabel: { color: CHROME[mode].muted, formatter: (v: number) => compact(v) },
      }),
      series: series.map((s) => ({
        type: "line",
        name: s.name,
        step: "end",
        data: s.data,
        showSymbol: false,
        symbolSize: 8,
        lineStyle: { width: 2, color: s.color, type: s.live ? "dashed" : "solid" },
        itemStyle: { color: s.color },
        z: s.emphasized ? 3 : 2,
        emphasis: { focus: "series" },
      })),
    };
  }, [series, by, higherIsBetter, mode]);
  const ref = useEChart(option);
  return <div ref={ref} style={{ height: 260 }} />;
}

export function AxisToggle({ by, onChange }: { by: Axis; onChange: (a: Axis) => void }) {
  return (
    <div className="segmented" role="group" aria-label="x axis">
      {(["time", "iteration"] as const).map((a) => (
        <button key={a} className={a === by ? "on" : ""} onClick={() => onChange(a)}>
          {a}
        </button>
      ))}
    </div>
  );
}

export function Convergence({ summary, mode }: { summary: RunSummary; mode: Mode }) {
  const [by, setBy] = useState<Axis>("time");
  const series = useMemo(
    () => [
      ...summary.runs.map((run) => ({
        name: runLabel(summary, run),
        color: runColor(mode, summary, run.run),
        data: curve(run, by),
        emphasized: run.run === summary.best_run,
      })),
      ...liveSeries(mode, summary, by),
    ],
    [summary, by, mode],
  );
  return (
    <div>
      <div className="chart-controls">
        <Legend entries={legendEntries(mode, summary)} line />
        <AxisToggle by={by} onChange={setBy} />
      </div>
      <ConvergenceChart series={series} by={by} higherIsBetter={summary.higher_is_better} mode={mode} />
    </div>
  );
}

export interface VariantStats {
  label: string;
  runs: number;
  best: number;
  mean: number;
  worst: number;
  meanTimeToBest: number;
  meanTotalTime: number;
}

/** Per-heuristic statistics, in the order the heuristics ran. */
export function variantStats(summary: RunSummary): VariantStats[] {
  const labels = summary.variants.length ? summary.variants : ["heuristic"];
  const better = (a: number, b: number) => (summary.higher_is_better ? a > b : a < b);
  return labels.flatMap((label, index) => {
    const runs = summary.runs.filter((r) => r.variant === index);
    if (runs.length === 0) return [];
    const values = runs.map((r) => r.best_objective);
    const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
    return [
      {
        label,
        runs: runs.length,
        best: values.reduce((a, b) => (better(a, b) ? a : b)),
        worst: values.reduce((a, b) => (better(a, b) ? b : a)),
        mean: mean(values),
        meanTimeToBest: mean(runs.map((r) => r.time_to_best_secs)),
        meanTotalTime: mean(runs.map((r) => r.total_time_secs)),
      },
    ];
  });
}
