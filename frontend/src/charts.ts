// A React hook around ECharts, and the axis and tooltip styling every chart shares.
import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { CHROME, type Mode } from "./theme";

export function useEChart(option: echarts.EChartsCoreOption) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
    const resize = new ResizeObserver(() => chart.current?.resize());
    resize.observe(ref.current);
    return () => {
      resize.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    chart.current?.setOption(option, true);
  }, [option]);
  return ref;
}

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export function axis(mode: Mode, extra: Record<string, unknown> = {}) {
  const c = CHROME[mode];
  return {
    axisLine: { lineStyle: { color: c.axis } },
    axisTick: { show: false },
    axisLabel: { color: c.muted, fontFamily: FONT, fontSize: 11 },
    splitLine: { lineStyle: { color: c.grid, width: 1, type: "solid" } },
    nameTextStyle: { color: c.ink2, fontFamily: FONT, fontSize: 11 },
    ...extra,
  };
}

export function tooltip(mode: Mode, extra: Record<string, unknown> = {}) {
  const c = CHROME[mode];
  return {
    backgroundColor: c.surface,
    borderColor: c.border,
    textStyle: { color: c.ink, fontFamily: FONT, fontSize: 12 },
    ...extra,
  };
}

export const GRID = { left: 56, right: 24, top: 16, bottom: 40, containLabel: false };
