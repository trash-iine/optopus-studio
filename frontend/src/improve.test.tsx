import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Improve } from "./components/Improve";
import type { BenchEvaluation, BenchState } from "./generated/bench-state";
import {
  best,
  budget,
  campaignOutcome,
  campaignText,
  families,
  fate,
  gap,
  leaders,
  outcomes,
  percent,
  progressText,
  raced,
  ranked,
  settings,
  share,
  side,
  studioTitle,
  verdictClass,
} from "./improve";
import { initialState, reduce } from "./studio";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function evaluation(overrides: Partial<BenchEvaluation> = {}): BenchEvaluation {
  return {
    id: 1,
    split: "train",
    candidate: { where: "the work files", rev: null, variant: "SA", worker: "python", candidate_id: null },
    baseline: { where: "revision 1", rev: 1, variant: "SA", worker: "python", candidate_id: null },
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
    evaluation({ id: 3, note: "tuning 1: initial_temperature=5.9", split: "validation", kept: null }),
  ],
  tunings: [
    {
      id: 1,
      rev: 2,
      variants: ["SA"],
      used: 78,
      budget: 80,
      settings: 9,
      eliminated: 5,
      failed: 0,
      best: { initial_temperature: 5.914476968936018 },
      best_variant: null,
      validation: 3,
      signs: [],
    },
    {
      id: 2,
      rev: 2,
      variants: ["RW", "SA"],
      used: 150,
      budget: 150,
      settings: 10,
      eliminated: 3,
      failed: 0,
      best: { cooling_rate: 0.98 },
      best_variant: "SA",
      validation: null,
      signs: ["#6 accepts 0.5% of its moves: almost none"],
    },
  ],
  profiles: [
    {
      id: 1,
      rev: 1,
      split: "train",
      instances: ["small", "large"],
      fractions: [0.1, 0.25, 0.5, 1],
      p: 0.0004,
      variants: [
        {
          label: "Tabu",
          error: null,
          mean_rank: 1.4,
          p_vs_best: 1,
          wins: 2,
          anytime: [0.09, 0.05, 0.02, 0],
          best_found_at: 0.8,
          iterations_per_sec: 1234.5,
          accepted: 0.3,
        },
        {
          label: "bad",
          error: "heuristic: invalid neighbor 'X'",
          mean_rank: null,
          p_vs_best: null,
          wins: 0,
          anytime: [],
          best_found_at: null,
          iterations_per_sec: null,
          accepted: null,
        },
        {
          label: "SA",
          error: null,
          mean_rank: 1.6,
          p_vs_best: 0.2,
          wins: 0,
          anytime: [0.03, 0.04, 0.03, 0.01],
          best_found_at: 0.1,
          iterations_per_sec: 2000,
          accepted: 0.5,
        },
      ],
      readings: ["SA leads at 10% of the budget (gap 3.000% vs 9.000% on 2 of 2 instances)"],
    },
  ],
  candidates: [],
  races: [],
  best: [],
  campaign: null,
};

const CAMPAIGN: NonNullable<BenchState["campaign"]> = {
  status: "running",
  start_rev: 2,
  incumbent_rev: 3,
  round: 2,
  rounds: 5,
  minutes: 30,
  elapsed_minutes: 7.4,
  idle: 1,
  patience: 3,
  reason: null,
  validation: null,
  test: null,
  kept: null,
  error: null,
};

// A round of two hypotheses on revision 2: the swap move won its race and was adopted.
const ROUND: Pick<BenchState, "candidates" | "races" | "best"> = {
  candidates: [
    {
      id: 1,
      baseline_rev: 2,
      family: "neighborhood",
      hypothesis: "a swap move reaches what a shift cannot",
      evidence: "tuning 2: settings barely matter",
      variant: "SA",
      evaluation: 4,
      verdict: "better",
      gain: 0.021,
      adopted: 3,
      lesson: "the shift alone was stuck",
    },
    {
      id: 2,
      baseline_rev: 2,
      family: "settings",
      hypothesis: "a slower cooling",
      evidence: "",
      variant: "SA",
      evaluation: 5,
      verdict: "same",
      gain: 0,
      adopted: null,
      lesson: "",
    },
    {
      id: 3,
      baseline_rev: 3,
      family: "neighborhood",
      hypothesis: "an ejection chain",
      evidence: "",
      variant: "SA",
      evaluation: null,
      verdict: null,
      gain: null,
      adopted: null,
      lesson: "",
    },
  ],
  races: [
    {
      id: 1,
      baseline: { where: "revision 2", rev: 2, variant: "SA", worker: "python", candidate_id: null },
      baseline_rank: 2.4,
      p: 0.01,
      entries: [
        { candidate: 1, evaluation: 4, verdict: "better", gain: 0.021, mean_rank: 1.2 },
        { candidate: 2, evaluation: 5, verdict: "same", gain: 0, mean_rank: 2.4 },
      ],
      winner: 1,
    },
  ],
  best: [{ name: "small", objective: 93.5, source: "evaluation 4" }],
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
    expect(settings({ initial_temperature: 5.914476968936018, neighbor: "TwoOpt" })).toBe(
      'initial_temperature = 5.914, neighbor = "TwoOpt"',
    );
    const tuning = STATE.tunings[1];
    expect(best(tuning)).toBe("SA: cooling_rate = 0.98");
    expect(best({ ...tuning, best: {} })).toBe("SA: its own settings");
    expect(best(STATE.tunings[0])).toBe("initial_temperature = 5.914");
    expect(progressText({ type: "bench_progress", task: "tuning", done: 40, total: 80 })).toBe(
      "Tuning settings by racing: 40 / 80 runs",
    );
    expect(progressText({ type: "bench_progress", task: "profile", done: 3, total: 12 })).toBe(
      "Profiling heuristics: 3 / 12 solves",
    );
    const profile = STATE.profiles[0];
    expect(ranked(profile).map((v) => v.label)).toEqual(["Tabu", "SA", "bad"]);
    expect(leaders(profile)).toEqual(["SA", "SA", "Tabu", "Tabu"]);
    expect(share(0.0123)).toBe("1.23%");
    expect(gap(0.0000123)).toBe("0.00123%");
    expect(gap(0)).toBe("0%");
    expect(share(null)).toBe("—");
  });

  it("keeps a ledger of the hypotheses saved as candidates", async () => {
    expect(side({ rev: null, candidate_id: 2 })).toBe("candidate 2");
    expect(ROUND.candidates.map(fate)).toEqual(["revision 3", "same", "not raced"]);
    expect(raced(ROUND.races).get(1)).toEqual({ race: 1, won: true });
    expect(families(ROUND.candidates)).toEqual([
      { family: "neighborhood", tried: 2, adopted: 1 },
      { family: "settings", tried: 1, adopted: 0 },
    ]);
    expect(progressText({ type: "bench_progress", task: "race", done: 2, total: 9 })).toBe(
      "Racing candidates: 2 / 9 solves",
    );

    const spec = {
      ...STATE.spec,
      instances: [...STATE.spec.instances, { name: "unseen", split: "test" as const, source: "seed 9", sha256: "d" }],
    };
    const state = { ...STATE, ...ROUND, spec };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state))));
    render(<Improve project="p" version="0-3" progress={null} />);
    await screen.findByText("Hypotheses");
    expect(screen.getByText(/neighborhood 2 \(1 adopted\), settings 1/)).toBeTruthy();
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const ledger = rows.filter((r) => /^\d(neighborhood|settings)/.test(r));
    expect(ledger).toEqual([
      "3neighborhoodan ejection chainrevision 3—not raced——",
      "2settingsa slower coolingrevision 2#1same0.00%—",
      "1neighborhooda swap move reaches what a shift cannotrevision 2#1revision 3+2.10%the shift alone was stuck",
    ]);
    expect(screen.getByText("a swap move reaches what a shift cannot").getAttribute("title")).toBe(
      "tuning 2: settings barely matter",
    );
    expect(screen.getByText("small").getAttribute("title")).toBe(
      "instance.json; best known 93.5 (evaluation 4)",
    );
    expect(screen.getByText("unseen")).toBeTruthy();
    expect(screen.getByText(/never chosen on/)).toBeTruthy();
  });

  it("shows who leads early and who ends best in a profile", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(STATE))));
    render(<Improve project="p" version="0-2" progress={null} />);
    await screen.findByText("Heuristics profiled");
    const sa = screen.getAllByRole("row").find((r) => r.textContent?.startsWith("SA1.60"));
    const cells = [...(sa?.querySelectorAll("td") ?? [])].map((c) => [c.textContent, c.className]);
    expect(cells.slice(3, 7)).toEqual([
      ["3%", "num lead"],
      ["4%", "num lead"],
      ["3%", "num"],
      ["1%", "num"],
    ]);
    expect(screen.getByText(/failed: heuristic: invalid neighbor/)).toBeTruthy();
    expect(screen.getByText(/SA leads at 10% of the budget/).tagName).toBe("LI");
    expect(screen.getByText("1,235")).toBeTruthy();
  });

  it("follows the agent's evaluations and tunings", () => {
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
    const changes = rows.filter((r) => /^\d(a |tuning)/.test(r));
    expect(changes.map((r) => r[0])).toEqual(["3", "2", "1"]);
    expect(rows.some((r) => r.includes("revision 2") && r.includes("+3.21%"))).toBe(true);
    expect(screen.getByText("held").getAttribute("title")).toBe("generate.py seed 2");
    expect(screen.getByText("initial_temperature = 5.914")).toBeTruthy();
    expect(screen.getByText("RW or SA of revision 2")).toBeTruthy();
    expect(screen.getByText("SA: cooling_rate = 0.98")).toBeTruthy();
    expect(screen.getByText(/almost none/).tagName).toBe("LI");

    fireEvent.click(screen.getByText("a penalty of 0"));
    expect(screen.getByText(/changed the objective/)).toBeTruthy();
    fireEvent.click(screen.getByText("a cooler search"));
    expect(screen.queryByText(/changed the objective/)).toBeNull();
    expect(screen.getByText("instance")).toBeTruthy();
    expect(screen.getAllByText("+5.00%").length).toBe(1);
  });

  it("follows a campaign the studio drives", async () => {
    expect(studioTitle("[studio] Improvement campaign, round 2 of 5. The incumbent is revision 3")).toBe(
      "studio: Improvement campaign, round 2 of 5",
    );
    expect(studioTitle("[studio] The campaign ended after 3 rounds and 12 minutes: its 3 rounds are spent.")).toBe(
      "studio: The campaign ended after 3 rounds and 12 minutes",
    );
    expect(campaignText(CAMPAIGN)).toBe("round 2 of 5, 7 of 30 minutes");
    expect(campaignOutcome(CAMPAIGN)).toBe(
      "incumbent revision 3, started from revision 2; 1 of 3 rounds in a row without a gain",
    );
    const check = { evaluation: 9, verdict: "better" as const, gain: 0.031 };
    const kept = { ...CAMPAIGN, status: "finished" as const, kept: true, validation: check, test: { ...check, gain: 0.02 } };
    expect(campaignOutcome(kept)).toBe(
      "revision 3 kept over revision 2: better on validation (+3.10%), better on test (+2.00%)",
    );
    const undone = { ...kept, kept: false, validation: { ...check, verdict: "same" as const, gain: 0 }, test: null };
    expect(campaignOutcome(undone)).toBe("revision 3 not kept, back to revision 2: same on validation (0.00%)");
    expect(campaignOutcome({ ...CAMPAIGN, status: "finished", kept: false, incumbent_rev: 2 })).toBe(
      "no change was better than revision 2",
    );
    expect(campaignOutcome({ ...CAMPAIGN, status: "stopped" })).toBe("revision 3 was not checked on validation");

    const said = reduce(initialState, {
      type: "event",
      event: { type: "studio_message", text: "[studio] Improvement campaign, round 1." },
    });
    expect(said.chat).toEqual([{ role: "studio", text: "[studio] Improvement campaign, round 1." }]);
    expect(said.benchVersion).toBe(1);

    const state = { ...STATE, campaign: { ...kept, reason: "its 5 rounds are spent" } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state))));
    render(<Improve project="p" version="0-4" progress={null} />);
    await screen.findByText("Campaign");
    expect(screen.getByText(/finished: its 5 rounds are spent · round 2 of 5/)).toBeTruthy();
    expect(screen.getByText(/revision 3 kept over revision 2/).className).toBe("verdict-better");
  });

  it("says how to start when there is no benchmark", async () => {
    const empty = {
      ...STATE,
      spec: { ...STATE.spec, instances: [] },
      evaluations: [],
      tunings: [],
      profiles: [],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(empty))));
    const progress = { type: "bench_progress", task: "evaluation", done: 1, total: 4 } as const;
    render(<Improve project="p" version="0-0" progress={progress} />);
    await screen.findByText(/No benchmark yet/);
    expect(screen.getByText(/Evaluating on the benchmark: 1 \/ 4 solves/)).toBeTruthy();
  });
});
