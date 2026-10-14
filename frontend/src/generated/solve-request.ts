// Generated from schema/solve-request.json by `npm run gen:types`. Do not edit.

/**
 * Path of the project's model.py.
 */
export type ModelPath = string;
export type Runs = number;
export type Seed = number | null;

/**
 * One solve: the model to build, its data, and how to search.
 */
export interface SolveRequest {
  heuristic: Heuristic;
  instance: Instance;
  model_path: ModelPath;
  runs?: Runs;
  seed?: Seed;
}
/**
 * A heuristic as {'kind': <optopus class>, **constructor arguments}; 'stop' is a StopCondition's arguments, and a nested heuristic is another such dict.
 */
export interface Heuristic {
  [k: string]: unknown;
}
/**
 * The project's instance.json.
 */
export interface Instance {
  [k: string]: unknown;
}
