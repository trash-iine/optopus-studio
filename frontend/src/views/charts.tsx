// The views drawn with ECharts: gantt, bar and graph.
import { useMemo } from "react";
import { axis, GRID, tooltip, useEChart } from "../charts";
import type { BarView, GanttView, GraphView } from "../generated/server-event";
import { CHROME, groupColors, type Mode, slotColor } from "../theme";
import { Legend } from "./Legend";

const BAND = 36;

export function Gantt({ view, mode }: { view: GanttView; mode: Mode }) {
  const lanes = useMemo(() => [...new Set(view.tasks.map((t) => t.lane))], [view.tasks]);
  const colors = useMemo(() => groupColors(view.tasks.map((t) => t.group), mode), [view.tasks, mode]);
  const option = useMemo(() => {
    const c = CHROME[mode];
    const data = view.tasks.map((t) => ({
      value: [lanes.indexOf(t.lane), t.start, t.end],
      name: t.label,
      itemStyle: { color: t.group ? colors.get(t.group) : slotColor(mode, 0) },
      task: t,
    }));
    return {
      grid: { ...GRID, left: 88 },
      tooltip: tooltip(mode, {
        formatter: (p: { data: { task: GanttView["tasks"][number] } }) => {
          const t = p.data.task;
          const unit = view.time_unit ? ` ${view.time_unit}` : "";
          return `<b>${t.label}</b><br/>${t.lane}: ${t.start}–${t.end}${unit}`;
        },
      }),
      xAxis: axis(mode, { type: "value", name: view.time_unit ?? "", nameLocation: "end" }),
      yAxis: axis(mode, {
        type: "category",
        data: lanes,
        inverse: true,
        splitLine: { show: false },
        axisLabel: { color: c.ink2, fontSize: 12 },
      }),
      series: [
        {
          type: "custom",
          encode: { x: [1, 2], y: 0 },
          data,
          renderItem: (
            params: { dataIndex: number },
            api: {
              value: (i: number) => number;
              coord: (v: number[]) => number[];
              size: (v: number[]) => number[];
            },
          ) => {
            const lane = api.value(0);
            const [x0, y] = api.coord([api.value(1), lane]);
            const [x1] = api.coord([api.value(2), lane]);
            const height = Math.min(24, api.size([0, 1])[1] * 0.6);
            // A 2px surface gap between touching tasks, rather than a border.
            const width = Math.max(x1 - x0 - 2, 1);
            const item = data[params.dataIndex];
            // A label is drawn only where it fits; the tooltip carries it otherwise.
            const fits = width > item.name.length * 6.5 + 8;
            return {
              type: "rect",
              shape: { x: x0 + 1, y: y - height / 2, width, height, r: 3 },
              style: { fill: item.itemStyle.color },
              textContent: fits
                ? { style: { text: item.name, fill: "#ffffff", fontSize: 11 } }
                : undefined,
              textConfig: { position: "inside" },
            };
          },
        },
      ],
    };
  }, [view, lanes, colors, mode]);
  const ref = useEChart(option);
  return (
    <div>
      <Legend entries={[...colors.entries()]} />
      <div ref={ref} style={{ height: lanes.length * BAND + 64 }} />
    </div>
  );
}

export function Bar({ view, mode }: { view: BarView; mode: Mode }) {
  const option = useMemo(() => {
    const single = view.series.length === 1;
    return {
      grid: GRID,
      tooltip: tooltip(mode, { trigger: "axis", axisPointer: { type: "shadow" } }),
      xAxis: axis(mode, { type: "category", data: view.categories, splitLine: { show: false } }),
      yAxis: axis(mode, { type: "value" }),
      series: view.series.map((s, i) => ({
        type: "bar",
        name: s.name,
        data: s.values,
        stack: view.stacked ? "total" : undefined,
        barMaxWidth: 24,
        barGap: "8%",
        itemStyle: {
          color: slotColor(mode, i),
          borderRadius: view.stacked && i < view.series.length - 1 ? 0 : [4, 4, 0, 0],
          borderColor: CHROME[mode].surface,
          borderWidth: view.stacked ? 1 : 0,
        },
        label: {
          show: single && view.categories.length <= 12,
          position: "top",
          color: CHROME[mode].ink2,
          fontSize: 11,
        },
      })),
    };
  }, [view, mode]);
  const ref = useEChart(option);
  return (
    <div>
      <Legend entries={view.series.map((s, i) => [s.name, slotColor(mode, i)])} />
      <div ref={ref} style={{ height: 280 }} />
    </div>
  );
}

const NODE_LABEL_LIMIT = 40;

export function Graph({ view, mode }: { view: GraphView; mode: Mode }) {
  const colors = useMemo(() => groupColors(view.nodes.map((n) => n.group), mode), [view.nodes, mode]);
  const option = useMemo(() => {
    const c = CHROME[mode];
    const placed = view.nodes.every((n) => n.x != null && n.y != null);
    return {
      tooltip: tooltip(mode),
      series: [
        {
          type: "graph",
          layout: placed ? "none" : "force",
          force: { repulsion: 120, edgeLength: 60 },
          roam: true,
          symbolSize: 12,
          label: {
            show: view.nodes.length <= NODE_LABEL_LIMIT,
            position: "right",
            color: c.ink2,
            fontSize: 11,
          },
          data: view.nodes.map((n) => ({
            id: String(n.id),
            name: n.label ?? String(n.id),
            x: n.x ?? undefined,
            y: n.y ?? undefined,
            itemStyle: {
              color: n.group ? colors.get(n.group) : c.ink2,
              borderColor: c.surface,
              borderWidth: 2,
            },
          })),
          links: view.edges.map((e) => ({
            source: String(e.source),
            target: String(e.target),
            value: e.weight ?? undefined,
            lineStyle: {
              color: e.highlight ? c.ink2 : c.axis,
              width: e.highlight ? 2 : 1,
              opacity: 1,
            },
          })),
        },
      ],
    };
  }, [view, colors, mode]);
  const ref = useEChart(option);
  return (
    <div>
      <Legend entries={[...colors.entries()]} />
      <div ref={ref} style={{ height: 420 }} />
    </div>
  );
}
