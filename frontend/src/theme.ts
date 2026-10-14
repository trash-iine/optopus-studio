// Colors by role, from the validated reference palette (dataviz skill, references/palette.md).
// The categorical order is the colorblind-safety mechanism: assign slots in order, never cycle.
// An entity past the eighth slot is drawn in the muted ink and carries a text label instead.
import { useEffect, useState } from "react";

export type Mode = "light" | "dark";
export type ThemePreference = Mode | "system";

export const CATEGORICAL: Record<Mode, string[]> = {
  light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
  dark: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

export const CHROME = {
  light: {
    surface: "#fcfcfb",
    plane: "#f9f9f7",
    ink: "#0b0b0b",
    ink2: "#52514e",
    muted: "#898781",
    grid: "#e1e0d9",
    axis: "#c3c2b7",
    border: "rgba(11,11,11,0.10)",
  },
  dark: {
    surface: "#1a1a19",
    plane: "#0d0d0d",
    ink: "#f0efec",
    ink2: "#c3c2b7",
    muted: "#898781",
    grid: "#2c2c2a",
    axis: "#383835",
    border: "rgba(255,255,255,0.10)",
  },
} satisfies Record<Mode, Record<string, string>>;

export const STATUS = { good: "#0ca30c", warning: "#fab219", critical: "#d03b3b" };

export function slotColor(mode: Mode, index: number): string {
  return index < CATEGORICAL[mode].length ? CATEGORICAL[mode][index] : CHROME[mode].muted;
}

/** One color per distinct group, in first-seen order, so a group keeps its color. */
export function groupColors(groups: (string | null | undefined)[], mode: Mode): Map<string, string> {
  const colors = new Map<string, string>();
  for (const group of groups) {
    if (group != null && !colors.has(group)) colors.set(group, slotColor(mode, colors.size));
  }
  return colors;
}

function systemMode(): Mode {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme(): [Mode, ThemePreference, (p: ThemePreference) => void] {
  const [preference, setPreference] = useState<ThemePreference>(
    () => (localStorage.getItem("theme") as ThemePreference | null) ?? "system",
  );
  const [system, setSystem] = useState<Mode>(systemMode);
  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: dark)");
    const update = () => setSystem(systemMode());
    query?.addEventListener("change", update);
    return () => query?.removeEventListener("change", update);
  }, []);
  const mode = preference === "system" ? system : preference;
  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    localStorage.setItem("theme", preference);
  }, [mode, preference]);
  return [mode, preference, setPreference];
}

/** Compact figures for tiles and ticks: 1,284 / 12.9K / 4.2M. */
export function compact(value: number): string {
  if (!Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toFixed(abs >= 1e7 ? 0 : 1)}M`;
  if (abs >= 1e4) return `${(value / 1e3).toFixed(abs >= 1e5 ? 0 : 1)}K`;
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return value.toLocaleString("en-US", { maximumSignificantDigits: 6 });
}
