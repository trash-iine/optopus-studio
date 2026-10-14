import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { projectLabel } from "./App";
import { Search } from "./components/Search";
import type { RunSummary } from "./generated/server-event";
import { describeStop, heuristicParts } from "./heuristic";

afterEach(cleanup);

describe("heuristics", () => {
  it("says a stop condition in words", () => {
    expect(describeStop({ max_iteration: 20000, max_duration_secs: 8 })).toBe("20,000 iterations or 8 s");
    expect(describeStop({ max_failed_update: 50 })).toBe("50 iterations without improvement");
    expect(describeStop({})).toBe("no limit");
  });

  it("splits a heuristic into its arguments, stop and nested heuristics", () => {
    const parts = heuristicParts({
      kind: "Iterated",
      search: { kind: "LocalSearch", neighbor: "Flip", stop: { max_iteration: 100 } },
      perturbation: { kind: "RandomWalk", neighbor: "Flip", stop: { max_iteration: 3 } },
      stop: { max_duration_secs: 2 },
    });
    expect(parts.kind).toBe("Iterated");
    expect(parts.summary).toMatch(/Iterated local search/);
    expect(parts.stop).toBe("2 s");
    expect(parts.params).toEqual([]);
    expect(parts.children.map((c) => c.role)).toEqual(["search", "perturbation"]);
    expect(heuristicParts(parts.children[0].spec).params).toEqual([["neighbor", "Flip"]]);
  });

  it("numbers the heuristics of a list and keeps their weights", () => {
    const tabu = { kind: "TabuSearch", neighbor: "Flip", tabu_tenure: [2, 5] };
    const parts = heuristicParts({ kind: "BreakoutLocalSearch", directed: [[tabu, 1.0]], steps: [tabu] });
    expect(parts.children.map((c) => c.role)).toEqual(["directed 1 (weight 1)", "steps 1"]);
    expect(heuristicParts(tabu).params).toEqual([
      ["neighbor", "Flip"],
      ["tabu_tenure", "[2, 5]"],
    ]);
  });

  it("shows every variant of a solve with its label", () => {
    const summary = {
      rev: 1,
      worker: "rust",
      seed: 0,
      variants: ["SA", "Tabu"],
      heuristics: [
        { label: "SA", heuristic: { kind: "SimulatedAnnealing", cooling_rate: 0.999, stop: { max_iteration: 10 } } },
        { label: "Tabu", heuristic: { kind: "TabuSearch", neighbor: "Move" } },
      ],
      runs: [{ variant: 0 }, { variant: 0 }, { variant: 1 }, { variant: 1 }],
    } as unknown as RunSummary;
    render(<Search summary={summary} />);
    expect(screen.getByText("rust worker · seed 0 · 2 runs each")).toBeTruthy();
    expect(screen.getByText("SA")).toBeTruthy();
    expect(screen.getByText("SimulatedAnnealing")).toBeTruthy();
    expect(screen.getByText("stops at 10 iterations")).toBeTruthy();
    expect(screen.getByText("0.999")).toBeTruthy();
  });

  it("shows nothing for a result older than its heuristics", () => {
    const { container } = render(<Search summary={{ heuristics: [], runs: [] } as unknown as RunSummary} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("projects", () => {
  it("are listed by title, marking the imported ones", () => {
    expect(projectLabel({ id: "a", title: "visit every city", imported_from: null })).toBe("visit every city");
    expect(projectLabel({ id: "b", title: null, imported_from: "c" })).toBe("Untitled (imported)");
  });
});
