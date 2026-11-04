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
/**
 * The shares of the budget 'anytime' is read at.
 */
export type Fractions = number[];
export type Id1 = number;
export type Instances1 = string[];
/**
 * The Friedman test's p-value over all runs.
 */
export type P = number | null;
/**
 * Compositions the profile suggests, as hints for the next variants.
 */
export type Readings = string[];
/**
 * The revision profiled; null for the work files.
 */
export type Rev1 = number | null;
export type Split1 = "train" | "validation" | "all";
/**
 * The share of moves accepted.
 */
export type Accepted = number | null;
/**
 * The mean gap of its best so far to the best any heuristic found on the instance, relative to that best, at each of the profile's fractions of the budget.
 */
export type Anytime = number[];
/**
 * The mean share of the budget spent when a run found its best.
 */
export type BestFoundAt = number | null;
/**
 * Why its runs failed; the rest is null then.
 */
export type Error = string | null;
export type IterationsPerSec = number | null;
export type Label = string;
/**
 * Over the runs, 1 the best.
 */
export type MeanRank = number | null;
/**
 * Conover's p-value against the best; under 0.05 it is clearly worse.
 */
export type PVsBest = number | null;
/**
 * Instances on which its mean objective is the best.
 */
export type Wins = number;
export type Variants = BenchProfileVariant[];
export type Profiles = BenchProfile[];
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
export type Split2 = "train" | "validation";
export type Instances2 = BenchInstance[];
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
export type Id2 = number;
export type Rev2 = number;
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
export type Variants1 = string[];
export type Tunings = BenchTuning[];

/**
 * GET /api/projects/{id}/bench: the benchmark, and every evaluation, tuning and profile on
 * it.
 */
export interface BenchState {
  evaluations: Evaluations;
  profiles: Profiles;
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
 * One profile of several heuristics on the benchmark (profiling.py, docs/adr/0015).
 */
export interface BenchProfile {
  fractions: Fractions;
  id: Id1;
  instances: Instances1;
  p: P;
  readings: Readings;
  rev: Rev1;
  split: Split1;
  variants: Variants;
}
/**
 * How one heuristic behaved in a profile.
 */
export interface BenchProfileVariant {
  accepted: Accepted;
  anytime: Anytime;
  best_found_at: BestFoundAt;
  error: Error;
  iterations_per_sec: IterationsPerSec;
  label: Label;
  mean_rank: MeanRank;
  p_vs_best: PVsBest;
  wins: Wins;
}
/**
 * bench/bench.json: the instances and the budget every evaluation runs with.
 */
export interface BenchSpec {
  instances: Instances2;
  max_duration_secs: MaxDurationSecs;
  max_iteration: MaxIteration;
  runs: Runs;
  seed: Seed;
}
export interface BenchInstance {
  name: Name1;
  sha256: Sha256;
  source: Source;
  split: Split2;
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
  id: Id2;
  rev: Rev2;
  settings: Settings;
  signs: Signs;
  used: Used;
  validation: Validation;
  variants: Variants1;
}
