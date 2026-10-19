// Generated from schema/solve-request.json by `npm run gen:types`. Do not edit.

/**
 * The key of instance.json the solution was read from.
 */
export type Key = string;
/**
 * Path of the project's model.py.
 */
export type ModelPath = string;
export type Runs = number;
export type Seed = number | null;
/**
 * @minItems 1
 * @maxItems 8
 */
export type Variants =
  | [Variant]
  | [Variant, Variant]
  | [Variant, Variant, Variant]
  | [Variant, Variant, Variant, Variant]
  | [Variant, Variant, Variant, Variant, Variant]
  | [Variant, Variant, Variant, Variant, Variant, Variant]
  | [Variant, Variant, Variant, Variant, Variant, Variant, Variant]
  | [Variant, Variant, Variant, Variant, Variant, Variant, Variant, Variant];
export type Label = string;

/**
 * One solve: the model to build, its data, and how to search.
 *
 * Every variant runs ``runs`` times with the same per-run seeds, so variants start from the same
 * initial solutions and compare fairly.
 */
export interface SolveRequest {
  initial_solution?: InitialSolution | null;
  instance: Instance;
  model_path: ModelPath;
  runs?: Runs;
  seed?: Seed;
  variants: Variants;
}
/**
 * Where every run of a solve starts instead of a random solution.
 */
export interface InitialSolution {
  key: Key;
  solution: Solution;
}
/**
 * The solution in the form encode_solution writes it, which the worker turns back into the problem's own with the model's decode_solution.
 */
export interface Solution {
  [k: string]: unknown;
}
/**
 * The project's instance.json.
 */
export interface Instance {
  [k: string]: unknown;
}
/**
 * One heuristic of a solve, under the label the GUI shows it by.
 */
export interface Variant {
  heuristic: Heuristic;
  label: Label;
}
/**
 * A heuristic as {'kind': <optopus class>, **constructor arguments}; 'stop' is a StopCondition's arguments, and a nested heuristic is another such dict.
 */
export interface Heuristic {
  [k: string]: unknown;
}
