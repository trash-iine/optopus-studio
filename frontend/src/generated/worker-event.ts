// Generated from schema/worker-event.json by `npm run gen:types`. Do not edit.

export type WorkerEvent = Started | RunFinished | Done | WorkerError;
/**
 * The direction best_objective is ranked in.
 */
export type HigherIsBetter = boolean;
/**
 * The class name of the problem the model built.
 */
export type Problem = string;
export type Runs = number;
export type Type = "started";
export type BestIteration = number;
export type BestObjective = number;
export type InitialObjective = number;
export type Iterations = number;
export type Run = number;
export type Seed = number | null;
export type TimeToBestSecs = number;
export type TotalTimeSecs = number;
/**
 * (elapsed_secs, iteration, objective) for every improvement of the best.
 */
export type Trajectory = [unknown, unknown, unknown][];
export type Type1 = "run_finished";
export type BestObjective1 = number;
export type BestRun = number;
export type Type2 = "done";
export type Message = string;
export type Stage = "request" | "build" | "heuristic" | "run" | "encode";
export type Traceback = string | null;
export type Type3 = "error";

export interface Started {
  higher_is_better: HigherIsBetter;
  problem: Problem;
  runs: Runs;
  type: Type;
}
export interface RunFinished {
  best_iteration: BestIteration;
  best_objective: BestObjective;
  initial_objective: InitialObjective;
  iterations: Iterations;
  run: Run;
  seed: Seed;
  solution: Solution;
  time_to_best_secs: TimeToBestSecs;
  total_time_secs: TotalTimeSecs;
  trajectory: Trajectory;
  type: Type1;
}
/**
 * The best solution, JSON-encoded by the model.
 */
export interface Solution {
  [k: string]: unknown;
}
export interface Done {
  best_objective: BestObjective1;
  best_run: BestRun;
  type: Type2;
}
export interface WorkerError {
  message: Message;
  stage: Stage;
  traceback: Traceback;
  type: Type3;
}
