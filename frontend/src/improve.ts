// What the Improve tab shows of the benchmark (docs/adr/0013, 0014, 0015, 0018), as plain
// functions to test.
import type {
  BenchCandidate,
  BenchEvaluation,
  BenchProfile,
  BenchProfileVariant,
  BenchSpec,
  BenchState,
  BenchTuning,
} from "./generated/bench-state";
import type { BenchProgress } from "./generated/server-event";
import { describeStop } from "./heuristic";

export async function fetchBench(project: string): Promise<BenchState> {
  const response = await fetch(`/api/projects/${project}/bench`);
  if (!response.ok) throw new Error(`benchmark: ${response.status}`);
  return response.json();
}

/** A relative gain as a signed percentage; "—" when there is none. */
export function percent(gain: number | null | undefined): string {
  if (gain == null) return "—";
  const text = `${(gain * 100).toFixed(2)}%`;
  return gain > 0 ? `+${text}` : text;
}

/** Each run's budget in words: the time, the iterations, or whichever comes first. */
export function budget(spec: BenchSpec): string {
  return describeStop({ max_duration_secs: spec.max_duration_secs, max_iteration: spec.max_iteration });
}

/** The class that colors a verdict; its word is always shown with it. */
export function verdictClass(verdict: BenchEvaluation["verdict"]): string {
  if (verdict === "better") return "verdict-better";
  if (verdict === "same") return "verdict-same";
  if (verdict === "mixed") return "verdict-mixed";
  return "verdict-worse";
}

/** How many instances got better, stayed and got worse. */
export function outcomes(e: BenchEvaluation): string {
  if (e.verdict === "rejected" || e.verdict === "failed") return "—";
  const count = (o: string) => e.instances.filter((i) => i.outcome === o).length;
  return `${count("better")} / ${count("same")} / ${count("worse")}`;
}

/** A side of an evaluation: where its files are. */
export function side(s: { rev: number | null; candidate_id?: number | null }): string {
  if (s.candidate_id != null) return `candidate ${s.candidate_id}`;
  return s.rev == null ? "work files" : `revision ${s.rev}`;
}

/** What became of a saved candidate, in a word or two. */
export function fate(c: BenchCandidate): string {
  if (c.adopted != null) return `revision ${c.adopted}`;
  return c.verdict ?? "not raced";
}

/** The race each candidate ran in last, and whether it won it, by the candidate's number. */
export function raced(races: BenchState["races"]): Map<number, { race: number; won: boolean }> {
  const found = new Map<number, { race: number; won: boolean }>();
  for (const r of races) {
    for (const e of r.entries) found.set(e.candidate, { race: r.id, won: r.winner === e.candidate });
  }
  return found;
}

/** The kinds of change tried, with how many of each and how many were adopted, most tried first. */
export function families(candidates: BenchCandidate[]): { family: string; tried: number; adopted: number }[] {
  const counts = new Map<string, { family: string; tried: number; adopted: number }>();
  for (const c of candidates) {
    const entry = counts.get(c.family) ?? { family: c.family, tried: 0, adopted: 0 };
    entry.tried += 1;
    if (c.adopted != null) entry.adopted += 1;
    counts.set(c.family, entry);
  }
  return [...counts.values()].sort((a, b) => b.tried - a.tried);
}

export function settings(values: Record<string, unknown>): string {
  return Object.entries(values)
    .map(([k, v]) => `${k} = ${typeof v === "number" ? Number(v.toPrecision(4)) : JSON.stringify(v)}`)
    .join(", ");
}

/** A tuning's best settings, with their variant when the race chose among several. */
export function best(t: BenchTuning): string {
  const values = settings(t.best ?? {}) || "its own settings";
  return t.best_variant ? `${t.best_variant}: ${values}` : values;
}

// What each task on the benchmark is doing, and what it counts.
const TASKS: Record<BenchProgress["task"], [string, string]> = {
  evaluation: ["Evaluating on the benchmark", "solves"],
  tuning: ["Tuning settings by racing", "runs"],
  profile: ["Profiling heuristics", "solves"],
  race: ["Racing candidates", "solves"],
};

export function progressText(p: BenchProgress): string {
  const [doing, unit] = TASKS[p.task];
  return `${doing}: ${p.done} / ${p.total} ${unit}`;
}

/** A profile's heuristics, the best ranked first and the ones that failed last. */
export function ranked(p: BenchProfile): BenchProfileVariant[] {
  const rank = (v: BenchProfileVariant) => v.mean_rank ?? Number.POSITIVE_INFINITY;
  return [...p.variants].sort((a, b) => rank(a) - rank(b));
}

/** For each share of the budget, the heuristic closest to the best found then: who leads early
 * and who ends best. */
export function leaders(p: BenchProfile): (string | null)[] {
  return p.fractions.map((_, k) => {
    let lead: BenchProfileVariant | null = null;
    for (const v of p.variants) {
      if (v.error == null && (lead == null || v.anytime[k] < lead.anytime[k])) lead = v;
    }
    return lead?.label ?? null;
  });
}

/** A gap to the best, as a percentage to three significant digits: the gaps that matter can be
 * tiny. */
export function gap(value: number): string {
  return `${Number((value * 100).toPrecision(3))}%`;
}

/** A share, such as the moves accepted, as a percentage; "—" when there is none. */
export function share(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}
