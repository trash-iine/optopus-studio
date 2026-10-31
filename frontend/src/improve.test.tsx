import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Improve } from "./components/Improve";
import type { BenchEvaluation, BenchState } from "./generated/bench-state";
import { budget, outcomes, percent, verdictClass } from "./improve";
import { initialState, reduce } from "./studio";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function evaluation(overrides: Partial<BenchEvaluation> = {}): BenchEvaluation {
  return {
    id: 1,
    split: "train",
    candidate: { where: "the work files", rev: null, variant: "SA", worker: "python" },
    baseline: { where: "revision 1", rev: 1, variant: "SA", worker: "python" },
    note: "a cooler search",
    verdict: "better",
    gain: 0.0321,
    worsening: 0,
    p_better: 0.002,
    p_worse: 0.99,
    detail: null,
    instances: [
      { name: "small", gain: 0.05, outcome: "better", baseline: 100, candidate: 95 },
      { name: "large", gain: 0, outcome: "same", baseline: 400, candidate: 400 },
    ],
    kept: 2,
    ...overrides,
  };
}

const STATE: BenchState = {
  spec: {
    instances: [
      { name: "small", split: "train", source: "instance.json", sha256: "a" },
      { name: "large", split: "train", source: "generate.py seed 1", sha256: "b" },
      { name: "held", split: "validation", source: "generate.py seed 2", sha256: "c" },
    ],
    runs: 5,
    seed: 0,
    max_duration_secs: 1,
    max_iteration: null,
  },
  evaluations: [
    evaluation(),
    evaluation({
      id: 2,
      note: "a penalty of 0",
      verdict: "rejected",
      gain: null,
      detail: "the candidate changed the objective, not only the search",
      kept: null,
    }),
    evaluation({ id: 3, note: "a longer tabu tenure", split: "validation", kept: null }),
  ],
};

describe("the improve tab", () => {
  it("says gains, budgets and verdicts in words", () => {
    expect(percent(0.0321)).toBe("+3.21%");
    expect(percent(-0.005)).toBe("-0.50%");
    expect(percent(null)).toBe("—");
    expect(budget({ ...STATE.spec, max_iteration: 3000 })).toBe("3,000 iterations or 1 s");
    expect(verdictClass("rejected")).toBe("verdict-worse");
    expect(verdictClass("mixed")).toBe("verdict-mixed");
    expect(outcomes(evaluation())).toBe("1 / 1 / 0");
    expect(outcomes(evaluation({ verdict: "failed" }))).toBe("—");
  });

  it("follows the agent's evaluations", () => {
    const running = reduce(initialState, {
      type: "event",
      event: { type: "bench_progress", task: "evaluation", done: 3, total: 8 },
    });
    expect(running.benchProgress?.done).toBe(3);
    const changed = reduce(running, { type: "event", event: { type: "bench_changed" } });
    expect(changed.benchVersion).toBe(1);
    expect(changed.benchProgress).toBeNull();
    const ended = reduce(running, { type: "event", event: { type: "turn_end", error: null } });
    expect(ended.benchProgress).toBeNull();
  });

  it("lists the changes newest first and opens one to its instances", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(STATE))));
    render(<Improve project="p" version="0-2" progress={null} />);
    await screen.findByText("a cooler search");
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const changes = rows.filter((r) => /^\da /.test(r));
    expect(changes.map((r) => r[0])).toEqual(["3", "2", "1"]);
    expect(rows.some((r) => r.includes("revision 2") && r.includes("+3.21%"))).toBe(true);
    expect(screen.getByText("held").getAttribute("title")).toBe("generate.py seed 2");

    fireEvent.click(screen.getByText("a penalty of 0"));
    expect(screen.getByText(/changed the objective/)).toBeTruthy();
    fireEvent.click(screen.getByText("a cooler search"));
    expect(screen.queryByText(/changed the objective/)).toBeNull();
    expect(screen.getByText("instance")).toBeTruthy();
    expect(screen.getAllByText("+5.00%").length).toBe(1);
  });

  it("says how to start when there is no benchmark", async () => {
    const empty = { ...STATE, spec: { ...STATE.spec, instances: [] }, evaluations: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(empty))));
    const progress = { type: "bench_progress", task: "evaluation", done: 1, total: 4 } as const;
    render(<Improve project="p" version="0-0" progress={progress} />);
    await screen.findByText(/No benchmark yet/);
    expect(screen.getByText(/Evaluating on the benchmark: 1 \/ 4 solves/)).toBeTruthy();
  });
});
