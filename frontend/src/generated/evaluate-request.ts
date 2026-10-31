// Generated from schema/evaluate-request.json by `npm run gen:types`. Do not edit.

/**
 * Path of the model.py that scores the solutions.
 */
export type ModelPath = string;
/**
 * Solutions in the form encode_solution writes.
 */
export type Solutions = unknown[];

/**
 * A worker started with ``--evaluate``: score solutions with a model, without searching.
 *
 * The answer is one JSON line, ``{"objectives": [...]}`` in the order of ``solutions`` on the
 * scale ``best_objective`` reports, or ``{"error": ...}`` when the model cannot build or a
 * solution cannot be decoded. A Rust worker is the model, so it reads only ``instance`` and
 * ``solutions``.
 */
export interface EvaluateRequest {
  heuristic: Heuristic;
  instance: Instance;
  model_path: ModelPath;
  solutions: Solutions;
}
/**
 * A heuristic of the model's solve.json. The Python worker starts a run of it from each solution and stops it before its first iteration, so a built-in problem scores the solution as a run would report it.
 */
export interface Heuristic {
  [k: string]: unknown;
}
export interface Instance {
  [k: string]: unknown;
}
