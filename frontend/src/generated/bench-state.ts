// Generated from schema/bench-state.json by `npm run gen:types`. Do not edit.

export type Name = string;
export type Objective = number;
/**
 * What found it, such as 'evaluation 4'.
 */
export type Source = string;
export type Best = BenchBest[];
export type ElapsedMinutes = number;
/**
 * Why the final check could not be made, if so.
 */
export type Error = string | null;
/**
 * The latest rounds in a row that brought no new incumbent.
 */
export type Idle = number;
export type IncumbentRev = number;
/**
 * Whether the incumbent was kept after the final check; null until then.
 */
export type Kept = boolean | null;
/**
 * The minutes it may take, if it has such a budget.
 */
export type Minutes = number | null;
/**
 * The rounds in a row without one after which it ends.
 */
export type Patience = number;
/**
 * Why it ended, once it has.
 */
export type Reason = string | null;
/**
 * The rounds begun.
 */
export type Round = number;
/**
 * The rounds it may take, if it has such a budget.
 */
export type Rounds = number | null;
/**
 * The revision it started from, and is checked against.
 */
export type StartRev = number;
export type Status = "running" | "finished" | "stopped";
export type Evaluation = number;
export type Gain = number | null;
export type Verdict = "better" | "mixed" | "same" | "worse" | "rejected" | "failed";
/**
 * The revision it was adopted as, if it was.
 */
export type Adopted = number | null;
/**
 * The revision it changes, and is judged against.
 */
export type BaselineRev = number;
/**
 * Its latest evaluation, if it was judged.
 */
export type Evaluation1 = number | null;
/**
 * What suggested it: a reading, a sign, a source.
 */
export type Evidence = string;
export type Family =
  | "settings"
  | "heuristic"
  | "composition"
  | "neighborhood"
  | "delta"
  | "representation"
  | "start"
  | "port";
export type Gain1 = number | null;
/**
 * What it changes and why that should help.
 */
export type Hypothesis = string;
export type Id = number;
/**
 * What its result taught, in the agent's words.
 */
export type Lesson = string;
/**
 * The heuristic of its solve.json it runs.
 */
export type Variant = string;
export type Verdict1 = ("better" | "mixed" | "same" | "worse" | "rejected" | "failed") | null;
export type Candidates = BenchCandidate[];
/**
 * The saved candidate the side ran, if it is one (docs/adr/0018).
 */
export type CandidateId = number | null;
export type Rev = number | null;
export type Variant1 = string;
/**
 * 'the work files', 'revision <n>' or 'candidate <n>'.
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
export type Gain2 = number | null;
export type Id1 = number;
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
export type Gain3 = number;
export type Name1 = string;
export type Outcome = "better" | "same" | "worse";
export type Instances = BenchInstanceResult[];
/**
 * The later revision whose files are the candidate's, if it was solved into one.
 */
export type Kept1 = number | null;
/**
 * What the candidate changes, as the agent said it.
 */
export type Note = string;
export type PBetter = number;
export type PWorse = number;
export type Split = "train" | "validation" | "test" | "all";
export type Verdict2 = "better" | "mixed" | "same" | "worse" | "rejected" | "failed";
/**
 * The mean worsening over the instances, one way.
 */
export type Worsening = number;
export type Evaluations = BenchEvaluation[];
/**
 * The shares of the budget 'anytime' is read at.
 */
export type Fractions = number[];
export type Id2 = number;
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
export type Error1 = string | null;
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
export type BaselineRank = number | null;
export type Candidate1 = number;
/**
 * Its evaluation against the baseline, from the race.
 */
export type Evaluation2 = number;
export type Gain4 = number | null;
/**
 * Over the runs, 1 the best, among the baseline and the candidates judged.
 */
export type MeanRank1 = number | null;
export type Verdict3 = "better" | "mixed" | "same" | "worse" | "rejected" | "failed";
export type Entries = BenchRaceEntry[];
export type Id3 = number;
/**
 * The Friedman test's p-value over all runs.
 */
export type P1 = number | null;
/**
 * The best-ranked candidate judged better than the baseline, if any.
 */
export type Winner = number | null;
export type Races = BenchRace[];
export type Name2 = string;
/**
 * Of the instance file, so a result says what it ran on.
 */
export type Sha256 = string;
/**
 * Where the instance came from, such as 'revision 3'.
 */
export type Source1 = string;
/**
 * Candidates are chosen on train; the final choice is checked on validation; test only measures what is reported, and decides nothing.
 */
export type Split2 = "train" | "validation" | "test";
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
export type Best1 = {
  [k: string]: unknown;
} | null;
/**
 * The variant of the best settings when several were raced; null otherwise, or when the revision's own stayed.
 */
export type BestVariant = string | null;
export type Budget = number;
export type Eliminated = number;
export type Failed = number;
export type Id4 = number;
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
 * GET /api/projects/{id}/bench: the benchmark and everything judged or measured on it.
 */
export interface BenchState {
  best: Best;
  campaign: BenchCampaign | null;
  candidates: Candidates;
  evaluations: Evaluations;
  profiles: Profiles;
  races: Races;
  spec: BenchSpec;
  tunings: Tunings;
}
/**
 * The best objective known on one instance of the benchmark.
 */
export interface BenchBest {
  name: Name;
  objective: Objective;
  source: Source;
}
/**
 * The project's latest improvement campaign (campaign.py, docs/adr/0019).
 */
export interface BenchCampaign {
  elapsed_minutes: ElapsedMinutes;
  error: Error;
  idle: Idle;
  incumbent_rev: IncumbentRev;
  kept: Kept;
  minutes: Minutes;
  patience: Patience;
  reason: Reason;
  round: Round;
  rounds: Rounds;
  start_rev: StartRev;
  status: Status;
  /**
   * Measured only when the result was kept.
   */
  test: BenchCheck | null;
  validation: BenchCheck | null;
}
/**
 * A campaign's final check of its result against the revision it started from.
 */
export interface BenchCheck {
  evaluation: Evaluation;
  gain: Gain;
  verdict: Verdict;
}
/**
 * One saved candidate, a line of the ledger: a hypothesis and what became of it.
 */
export interface BenchCandidate {
  adopted: Adopted;
  baseline_rev: BaselineRev;
  evaluation: Evaluation1;
  evidence: Evidence;
  family: Family;
  gain: Gain1;
  hypothesis: Hypothesis;
  id: Id;
  lesson: Lesson;
  variant: Variant;
  verdict: Verdict1;
}
/**
 * One evaluation of a change against a baseline revision (bench.py).
 */
export interface BenchEvaluation {
  baseline: BenchSide;
  candidate: BenchSide;
  detail: Detail;
  gain: Gain2;
  id: Id1;
  instances: Instances;
  kept: Kept1;
  note: Note;
  p_better: PBetter;
  p_worse: PWorse;
  split: Split;
  verdict: Verdict2;
  worsening: Worsening;
}
/**
 * One side of an evaluation: whose files, which heuristic, which worker.
 */
export interface BenchSide {
  candidate_id: CandidateId;
  rev: Rev;
  variant: Variant1;
  where: Where;
  worker: Worker;
}
/**
 * How the candidate did against the baseline on one instance.
 */
export interface BenchInstanceResult {
  baseline: Baseline;
  candidate: Candidate;
  gain: Gain3;
  name: Name1;
  outcome: Outcome;
}
/**
 * One profile of several heuristics on the benchmark (profiling.py, docs/adr/0015).
 */
export interface BenchProfile {
  fractions: Fractions;
  id: Id2;
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
  error: Error1;
  iterations_per_sec: IterationsPerSec;
  label: Label;
  mean_rank: MeanRank;
  p_vs_best: PVsBest;
  wins: Wins;
}
/**
 * One race of several candidates against a baseline revision (candidates.py).
 */
export interface BenchRace {
  baseline: BenchSide;
  baseline_rank: BaselineRank;
  entries: Entries;
  id: Id3;
  p: P1;
  winner: Winner;
}
/**
 * How one candidate did in a race.
 */
export interface BenchRaceEntry {
  candidate: Candidate1;
  evaluation: Evaluation2;
  gain: Gain4;
  mean_rank: MeanRank1;
  verdict: Verdict3;
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
/**
 * One instance of the benchmark, kept under bench/instances.
 */
export interface BenchInstance {
  name: Name2;
  sha256: Sha256;
  source: Source1;
  split: Split2;
}
/**
 * One tuning of a heuristic's settings by racing (tune.py).
 */
export interface BenchTuning {
  best: Best1;
  best_variant: BestVariant;
  budget: Budget;
  eliminated: Eliminated;
  failed: Failed;
  id: Id4;
  rev: Rev2;
  settings: Settings;
  signs: Signs;
  used: Used;
  validation: Validation;
  variants: Variants1;
}
