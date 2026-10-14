// How a solve searched, for reading: a heuristic of solve.json as its kind, its arguments, its stop
// condition and the heuristics nested in it.

/** What each heuristic does, after optopus-py's user guide (docs/source/heuristics_*.md). */
export const HEURISTIC_SUMMARY: Record<string, string> = {
  LocalSearch: "Best-improvement descent: applies the best move of the whole neighborhood while it improves.",
  SimulatedAnnealing:
    "Draws one random move per iteration; always takes an improving one, and a worsening one with a probability that falls as the temperature cools.",
  BangBangSimulatedAnnealing: "Simulated annealing whose temperature oscillates instead of cooling once.",
  TabuSearch:
    "Applies the best move that is not tabu, even when it makes the solution worse; recent moves stay tabu for a while.",
  LateAcceptanceHillClimbing:
    "Draws one random move per iteration and accepts it when the result is no worse than the current solution, or than the one some iterations ago.",
  RandomWalk: "Applies a uniformly random move every iteration, whatever it does to the objective.",
  BeamSearch: "Keeps several candidate solutions and expands the neighborhood of each every iteration.",
  PopulationAnnealing: "Anneals a population of replicas together, resampling them as the temperature falls.",
  ParallelTempering: "Runs replicas at a ladder of fixed temperatures and swaps neighbors on the ladder.",
  ReinforcementLearningSearch: "Learns which moves to take while it searches.",
  Sequential: "Runs its steps one after another, each until its own stop condition, and repeats.",
  Iterated: "Iterated local search: a search, then a perturbation, then the search again from there.",
  VariableNeighborhoodSearch: "Alternates a search with shakes of increasing strength.",
  Restart: "Runs a heuristic again and again, starting over from a new random solution.",
  GeneticAlgorithm:
    "A steady-state genetic algorithm: recombines two parents per iteration, improves the child with its mutation heuristic, and replaces the worst member.",
  BreakoutLocalSearch: "Descends, then breaks out of the local optimum with perturbations that grow as it stagnates.",
  BranchAndBound:
    "Exact search: takes the open node with the best bound, drops nodes that cannot beat the best so far, and searches the rest with its heuristic.",
};

const STOP_KEYS = new Set(["stop", "restart"]);

export interface HeuristicParts {
  kind: string;
  summary?: string;
  params: [string, string][];
  stop?: string;
  children: { role: string; spec: Record<string, unknown> }[];
}

function isHeuristic(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) && "kind" in value;
}

const count = (n: number) => n.toLocaleString("en-US");

/** A StopCondition's arguments in words: "20,000 iterations or 8 s". */
export function describeStop(stop: unknown): string {
  if (typeof stop !== "object" || stop === null) return String(stop);
  const s = stop as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof s.max_iteration === "number") parts.push(`${count(s.max_iteration)} iterations`);
  if (typeof s.max_duration_secs === "number") parts.push(`${s.max_duration_secs} s`);
  if (typeof s.max_failed_update === "number")
    parts.push(`${count(s.max_failed_update)} iterations without improvement`);
  for (const [key, value] of Object.entries(s)) {
    if (!["max_iteration", "max_duration_secs", "max_failed_update"].includes(key) && value != null)
      parts.push(`${key} ${JSON.stringify(value)}`);
  }
  return parts.length > 0 ? parts.join(" or ") : "no limit";
}

function describeValue(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(describeValue).join(", ")}]`;
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}

/** Splits a heuristic of solve.json into what the GUI shows of it. */
export function heuristicParts(spec: Record<string, unknown>): HeuristicParts {
  const kind = String(spec.kind ?? "unknown");
  const parts: HeuristicParts = { kind, summary: HEURISTIC_SUMMARY[kind], params: [], children: [] };
  for (const [key, value] of Object.entries(spec)) {
    if (key === "kind" || value == null) continue;
    if (key === "stop") {
      parts.stop = describeStop(value);
    } else if (STOP_KEYS.has(key)) {
      parts.params.push([key, describeStop(value)]);
    } else if (isHeuristic(value)) {
      parts.children.push({ role: key, spec: value });
    } else if (Array.isArray(value) && value.some((item) => isHeuristic(item) || (Array.isArray(item) && isHeuristic(item[0])))) {
      value.forEach((item, i) => {
        // A list of heuristics, or of [heuristic, weight] pairs.
        if (isHeuristic(item)) parts.children.push({ role: `${key} ${i + 1}`, spec: item });
        else if (Array.isArray(item) && isHeuristic(item[0]))
          parts.children.push({ role: `${key} ${i + 1} (weight ${describeValue(item[1])})`, spec: item[0] });
      });
    } else {
      parts.params.push([key, describeValue(value)]);
    }
  }
  return parts;
}
