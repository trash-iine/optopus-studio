// Generated from schema/solve-request.json by `npm run gen:types`. Do not edit.

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
  instance: Instance;
  model_path: ModelPath;
  runs?: Runs;
  seed?: Seed;
  variants: Variants;
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
