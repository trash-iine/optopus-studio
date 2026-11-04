// Generated from schema/bench-state.json by `npm run gen:types`. Do not edit.

export type Rev = number | null;
export type Variant = string;
/**
 * 'the work files' or 'revision <n>'.
 */
export type Where = string;
export type Worker = "python" | "rust";
/**
 * Why a candidate was rejected or failed.
 */
export type Detail = string | null;
/**
 * The mean gain over all pairs; null unless judged.
 */
export type Gain = number | null;
export type Id = number;
/**
 * The baseline's mean best objective.
 */
export type Baseline = number;
/**
 * The candidate's mean best objective.
 */
export type Candidate = number;
/**
 * The mean gain over the paired runs, relative to the baseline's mean objective; + is better.
 */
export type Gain1 = number;
export type Name = string;
export type Outcome = "better" | "same" | "worse";
export type Instances = BenchInstanceResult[];
/**
 * The later revision whose files are the candidate's, if it was solved into one.
 */
export type Kept = number | null;
/**
 * What the candidate changes, as the agent said it.
 */
export type Note = string;
export type PBetter = number;
export type PWorse = number;
export type Split = "train" | "validation" | "all";
export type Verdict = "better" | "mixed" | "same" | "worse" | "rejected" | "failed";
/**
 * The mean worsening over the instances, one way.
 */
export type Worsening = number;
export type Evaluations = BenchEvaluation[];
export type Name1 = string;
/**
 * Of the instance file, so a result says what it ran on.
 */
export type Sha256 = string;
/**
 * Where the instance came from, such as 'revision 3'.
 */
export type Source = string;
/**
 * Candidates are chosen on train; the final choice is checked on validation.
 */
export type Split1 = "train" | "validation";
export type Instances1 = BenchInstance[];
/**
 * Each run's time limit, which replaces the stop of every evaluated heuristic.
 */
export type MaxDurationSecs = number | null;
/**
 * Each run's iteration limit, instead of or as well as the time.
 */
export type MaxIteration = number | null;
/**
 * Runs per instance and side, paired by seed.
 */
export type Runs = number;
export type Seed = number;
/**
 * The best settings by parameter path; null when the revision's own stayed.
 */
export type Best = {
  [k: string]: unknown;
} | null;
/**
 * The variant of the best settings when several were raced; null otherwise, or when the revision's own stayed.
 */
export type BestVariant = string | null;
export type Budget = number;
export type Eliminated = number;
export type Failed = number;
export type Id1 = number;
export type Rev1 = number;
/**
 * The settings raced.
 */
export type Settings = number;
/**
 * What the race shows that settings cannot fix, as hints for the next change.
 */
export type Signs = string[];
/**
 * The runs made.
 */
export type Used = number;
/**
 * The evaluation that checked them on validation.
 */
export type Validation = number | null;
/**
 * The variants raced: one, or several to choose among, the first the one the others were measured against.
 */
export type Variants = string[];
export type Tunings = BenchTuning[];

/**
 * GET /api/projects/{id}/bench: the benchmark, and every evaluation and tuning on it.
 */
export interface BenchState {
  evaluations: Evaluations;
  spec: BenchSpec;
  tunings: Tunings;
}
/**
 * One evaluation of a change against a baseline revision (bench.py).
 */
export interface BenchEvaluation {
  baseline: BenchSide;
  candidate: BenchSide;
  detail: Detail;
  gain: Gain;
  id: Id;
  instances: Instances;
  kept: Kept;
  note: Note;
  p_better: PBetter;
  p_worse: PWorse;
  split: Split;
  verdict: Verdict;
  worsening: Worsening;
}
export interface BenchSide {
  rev: Rev;
  variant: Variant;
  where: Where;
  worker: Worker;
}
export interface BenchInstanceResult {
  baseline: Baseline;
  candidate: Candidate;
  gain: Gain1;
  name: Name;
  outcome: Outcome;
}
/**
 * bench/bench.json: the instances and the budget every evaluation runs with.
 */
export interface BenchSpec {
  instances: Instances1;
  max_duration_secs: MaxDurationSecs;
  max_iteration: MaxIteration;
  runs: Runs;
  seed: Seed;
}
export interface BenchInstance {
  name: Name1;
  sha256: Sha256;
  source: Source;
  split: Split1;
}
/**
 * One tuning of a heuristic's settings by racing (tune.py).
 */
export interface BenchTuning {
  best: Best;
  best_variant: BestVariant;
  budget: Budget;
  eliminated: Eliminated;
  failed: Failed;
  id: Id1;
  rev: Rev1;
  settings: Settings;
  signs: Signs;
  used: Used;
  validation: Validation;
  variants: Variants;
}
