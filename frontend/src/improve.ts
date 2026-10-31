// What the Improve tab shows of the benchmark (docs/adr/0013), as plain functions to test.
import type { BenchEvaluation, BenchSpec, BenchState } from "./generated/bench-state";
import type { BenchProgress } from "./generated/server-event";

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
  const parts = [];
  if (spec.max_duration_secs != null) parts.push(`${spec.max_duration_secs} s`);
  if (spec.max_iteration != null) parts.push(`${spec.max_iteration.toLocaleString("en-US")} iterations`);
  return parts.join(" or ");
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

/** A side of an evaluation: where its files are, and the variant when it is not the only one. */
export function side(s: BenchEvaluation["candidate"]): string {
  return s.rev == null ? "work files" : `revision ${s.rev}`;
}

export function progressText(p: BenchProgress): string {
  return `Evaluating on the benchmark: ${p.done} / ${p.total} solves`;
}
