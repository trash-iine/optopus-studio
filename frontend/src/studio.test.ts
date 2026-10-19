import { describe, expect, it } from "vitest";
import type { RunFinished, RunSummary } from "./generated/server-event";
import { initialState, reduce, type StudioState } from "./studio";
import { CATEGORICAL, CHROME, groupColors } from "./theme";
import { curve, runColor } from "./views/Convergence";

function run(index: number, overrides: Partial<RunFinished> = {}): RunFinished {
  return {
    type: "run_finished",
    run: index,
    variant: 0,
    seed: index,
    best_objective: 10,
    initial_objective: 20,
    solution: [] as unknown as RunFinished["solution"],
    trajectory: [
      [0.1, 5, 15],
      [0.2, 9, 10],
    ] as unknown as RunFinished["trajectory"],
    iterations: 100,
    best_iteration: 9,
    time_to_best_secs: 0.2,
    total_time_secs: 1,
    proven_optimal: null,
    dual_bound: null,
    ...overrides,
  };
}

function summary(runs: number, best = 0): RunSummary {
  return {
    rev: 1,
    worker: "python",
    heuristics: [],
    seed: null,
    native: true,
    live: null,
    problem: "Tsp",
    higher_is_better: false,
    variants: ["SA"],
    runs: Array.from({ length: runs }, (_, i) => run(i)),
    best_run: best,
    error: null,
  };
}

const event = (state: StudioState, e: Parameters<typeof reduce>[1]) => reduce(state, e);

describe("reduce", () => {
  it("streams assistant text and replaces it with the final message", () => {
    let state = event(initialState, { type: "sent", text: "hi" });
    expect(state.busy).toBe(true);
    state = event(state, { type: "event", event: { type: "assistant_delta", text: "Hel" } });
    state = event(state, { type: "event", event: { type: "assistant_delta", text: "lo" } });
    expect(state.streaming).toBe("Hello");
    state = event(state, { type: "event", event: { type: "assistant_text", text: "Hello" } });
    expect(state.streaming).toBe("");
    expect(state.chat.map((c) => c.role)).toEqual(["user", "assistant"]);
    state = event(state, { type: "event", event: { type: "turn_end", error: null } });
    expect(state.busy).toBe(false);
  });

  it("opens a revision when a solve starts and keeps only its own progress", () => {
    let state = event(initialState, {
      type: "event",
      event: { type: "solve_started", rev: 3, runs: 2 },
    });
    expect(state.revisions).toEqual([3]);
    expect(state.solving).toEqual({ rev: 3, runs: 2 });
    const other = { ...summary(1), rev: 2 };
    state = event(state, { type: "event", event: { type: "solve_progress", rev: 2, summary: other } });
    expect(state.summary?.runs).toEqual([]);
    const mine = { ...summary(1), rev: 3 };
    state = event(state, { type: "event", event: { type: "solve_progress", rev: 3, summary: mine } });
    expect(state.summary?.runs).toHaveLength(1);
    state = event(state, {
      type: "event",
      event: { type: "view", rev: 3, view: { views: [] }, error: null },
    });
    expect(state.solving).toBeNull();
    expect(state.view).toEqual({ views: [] });
  });
});

describe("convergence", () => {
  it("runs the step curve from the start to the end of the run", () => {
    expect(curve(run(0), "time")).toEqual([
      [0, 20],
      [0.1, 15],
      [0.2, 10],
      [1, 10],
    ]);
    expect(curve(run(0), "iteration").map(([x]) => x)).toEqual([0, 5, 9, 100]);
  });

  it("colors runs by slot, and only the best one past eight", () => {
    expect(runColor("light", summary(3), 2)).toBe(CATEGORICAL.light[2]);
    const many = summary(12, 7);
    expect(runColor("light", many, 7)).toBe(CATEGORICAL.light[0]);
    expect(runColor("light", many, 3)).toBe(CHROME.light.axis);
  });
});

describe("groupColors", () => {
  it("keeps first-seen order and never cycles past the palette", () => {
    const groups = Array.from({ length: 10 }, (_, i) => `g${i}`);
    const colors = groupColors([null, ...groups, "g0"], "dark");
    expect(colors.get("g0")).toBe(CATEGORICAL.dark[0]);
    expect(colors.get("g7")).toBe(CATEGORICAL.dark[7]);
    expect(colors.get("g8")).toBe(CHROME.dark.muted);
  });
});

describe("live progress", () => {
  it("draws the run under way on the time axis only", async () => {
    const { liveSeries } = await import("./views/Convergence");
    const live = {
      ...summary(1),
      live: { run: 1, variant: 0, points: [[0.1, 9]] as unknown as [number, number][] },
    } as unknown as RunSummary;
    expect(liveSeries("light", live, "time")).toEqual([
      { name: "run 1 (running)", color: CATEGORICAL.light[1], data: [[0.1, 9]], live: true },
    ]);
    expect(liveSeries("light", live, "iteration")).toEqual([]);
  });
});
