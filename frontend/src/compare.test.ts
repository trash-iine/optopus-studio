import { describe, expect, it } from "vitest";
import { sendsMessage, withAttachments } from "./components/Chat";
import { bound } from "./components/Canvas";
import { change, kpiRows } from "./components/Compare";
import { proof } from "./components/SolveResult";
import { diffLines } from "./diff";
import type { RevisionDetail } from "./generated/revision";
import type { RunFinished, RunSummary } from "./generated/server-event";
import { legendEntries, runLabel, variantStats } from "./views/Convergence";

function run(index: number, variant: number, best: number): RunFinished {
  return {
    type: "run_finished",
    run: index,
    variant,
    seed: 0,
    best_objective: best,
    initial_objective: 30,
    solution: [] as unknown as RunFinished["solution"],
    trajectory: [] as unknown as RunFinished["trajectory"],
    iterations: 10,
    best_iteration: 1,
    time_to_best_secs: index,
    total_time_secs: 10,
    proven_optimal: null,
    dual_bound: null,
  };
}

const summary: RunSummary = {
  rev: 1,
  worker: "python",
  heuristics: [],
  seed: null,
  initial_solution: null,
  native: false,
  live: null,
  problem: "Workload",
  higher_is_better: false,
  variants: ["SA", "Tabu"],
  runs: [run(0, 0, 13), run(1, 0, 15), run(2, 1, 12), run(3, 1, 12)],
  best_run: 2,
  error: null,
};

describe("variants", () => {
  it("summarizes each heuristic in the problem's direction", () => {
    expect(variantStats(summary)).toEqual([
      { label: "SA", runs: 2, best: 13, mean: 14, worst: 15, meanTimeToBest: 0.5, meanTotalTime: 10 },
      { label: "Tabu", runs: 2, best: 12, mean: 12, worst: 12, meanTimeToBest: 2.5, meanTotalTime: 10 },
    ]);
  });

  it("names runs by heuristic and keys the legend by heuristic", () => {
    expect(runLabel(summary, summary.runs[3])).toBe("Tabu #2");
    expect(legendEntries("light", summary).map(([label]) => label)).toEqual(["SA", "Tabu"]);
  });
});

describe("compare", () => {
  it("says whether a change is better in the problem's direction", () => {
    expect(change(10, 8, false).verdict).toBe("better");
    expect(change(10, 8, true).verdict).toBe("worse");
    expect(change(10, 10, true).verdict).toBe("same");
  });

  it("lines up KPI items by label across revisions", () => {
    const detail = (rev: number, items: [string, number][]): RevisionDetail => ({
      rev,
      files: {},
      summary: null,
      view_error: null,
      view: {
        views: [
          { type: "kpi", title: null, items: items.map(([label, value]) => ({ label, value, unit: null })) },
        ],
      },
    });
    const rows = kpiRows(detail(2, [["Cost", 5], ["Trucks", 3]]), detail(1, [["Cost", 7]]));
    expect(rows.map((r) => [r.label, r.a?.value, r.b?.value])).toEqual([
      ["Cost", 5, 7],
      ["Trucks", 3, undefined],
    ]);
  });
});

describe("diffLines", () => {
  it("marks added and removed lines and folds unchanged runs", () => {
    const before = ["a", "b", "c", "d", "e", "f", "g", "h"].join("\n");
    const after = ["a", "b", "c", "d", "e", "F", "g", "h"].join("\n");
    const lines = diffLines(before, after)!;
    expect(lines[0]).toEqual({ kind: "skip", count: 3 });
    expect(lines.filter((l) => l.kind === "removed")).toEqual([{ kind: "removed", text: "f" }]);
    expect(lines.filter((l) => l.kind === "added")).toEqual([{ kind: "added", text: "F" }]);
  });

  it("gives up on files too large to compare", () => {
    const big = Array.from({ length: 3000 }, (_, i) => String(i)).join("\n");
    expect(diffLines(big, `${big}\nx`)).toBeNull();
  });
});

describe("attachments", () => {
  it("puts the attached files first, as the agent expects", () => {
    expect(withAttachments("use this", ["a.csv", "b.xlsx"])).toBe("Attached: a.csv, b.xlsx\n\nuse this");
    expect(withAttachments("", ["a.csv"])).toBe("Attached: a.csv");
    expect(withAttachments("hi", [])).toBe("hi");
  });
});

describe("the Enter key", () => {
  const press = (over: Partial<KeyboardEvent> = {}) =>
    sendsMessage({ key: "Enter", shiftKey: false, isComposing: false, keyCode: 13, ...over });

  it("sends on Enter, not on Shift+Enter", () => {
    expect(press()).toBe(true);
    expect(press({ shiftKey: true })).toBe(false);
  });

  it("does not send when it confirms an IME conversion", () => {
    expect(press({ isComposing: true, keyCode: 229 })).toBe(false);
    // Safari: the composition has already ended, but the key is still the IME's.
    expect(press({ keyCode: 229 })).toBe(false);
  });
});

describe("what a BranchAndBound run proved", () => {
  it("is said only for a run that has a certificate", () => {
    expect(proof(run(0, 0, 12))).toBeNull();
    expect(proof(null)).toBeNull();
    expect(bound(run(0, 0, 12))).toBe("—");
  });

  it("says proven optimal, or the bound and the gap to it", () => {
    const proven = { ...run(0, 0, 12), proven_optimal: true, dual_bound: 12 };
    expect(proof(proven)).toBe("proven optimal");
    expect(bound(proven)).toBe("optimal");
    const open = { ...run(0, 0, 12), proven_optimal: false, dual_bound: 9 };
    expect(proof(open)).toBe("not proven optimal: bound 9, gap 25.0%");
    expect(bound(open)).toBe("9");
    const unbounded = { ...run(0, 0, 12), proven_optimal: false };
    expect(proof(unbounded)).toBe("not proven optimal");
  });
});
