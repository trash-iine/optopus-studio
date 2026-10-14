// How each run's best objective improved, from the trajectory the worker reports.
import { useMemo, useState } from "react";
import { axis, GRID, tooltip, useEChart } from "../charts";
import type { RunFinished, RunSummary } from "../generated/server-event";
import { CHROME, compact, type Mode, slotColor } from "../theme";
import { Legend } from "./Legend";

type Axis = "time" | "iteration";

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

export function runColor(mode: Mode, summary: RunSummary, run: number): string {
  // Up to eight runs keep their own color; past that only the best run stands out.
  if (summary.runs.length <= 8) return slotColor(mode, run);
  return run === summary.best_run ? slotColor(mode, 0) : CHROME[mode].axis;
}

export function Convergence({ summary, mode }: { summary: RunSummary; mode: Mode }) {
  const [by, setBy] = useState<Axis>("time");
  const option = useMemo(() => {
    const direction = summary.higher_is_better ? "higher is better" : "lower is better";
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
      series: summary.runs.map((run) => ({
        type: "line",
        name: `run ${run.run}`,
        step: "end",
        data: curve(run, by),
        showSymbol: false,
        symbolSize: 8,
        lineStyle: { width: 2, color: runColor(mode, summary, run.run) },
        itemStyle: { color: runColor(mode, summary, run.run) },
        z: run.run === summary.best_run ? 3 : 2,
        emphasis: { focus: "series" },
      })),
    };
  }, [summary, by, mode]);
  const ref = useEChart(option);
  const entries: [string, string][] =
    summary.runs.length <= 8
      ? summary.runs.map((r) => [`run ${r.run}`, runColor(mode, summary, r.run)])
      : [];
  return (
    <div>
      <div className="chart-controls">
        <Legend entries={entries} line />
        <div className="segmented" role="group" aria-label="x axis">
          {(["time", "iteration"] as const).map((a) => (
            <button key={a} className={a === by ? "on" : ""} onClick={() => setBy(a)}>
              {a}
            </button>
          ))}
        </div>
      </div>
      <div ref={ref} style={{ height: 260 }} />
    </div>
  );
}
