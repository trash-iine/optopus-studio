# 0013. Judge a change of the algorithm on a benchmark of instances

- Status: Accepted; amended by 0018 (several candidates raced at once, a ledger of them, and a
  test split)
- Date: 2026-10-22

## Context

The agent can model a task and solve it, and it can compare heuristics within one solve
(`"heuristics"` in solve.json). The next step is improving the search itself, by the agent and on
its own: other settings, another heuristic, a cheaper delta or a new neighborhood in `model.py`, a
Rust port. Each such change needs a judge, and a solve of the project's one instance with a few
seeds is a poor one:

- it rewards luck, and a change fitted to that instance;
- a run's own stop condition is part of the candidate, so a candidate can win by running longer;
- a change to `model.py` can change the objective, by a penalty weight or a bug, and look like an
  improvement while it solves another problem.

The literature on automated heuristic design agrees on what helps: a plain loop that keeps the
best candidate and tries one change at a time is a strong baseline; feedback richer than one
score (per instance, and why) makes better candidates; and choosing the final candidate on
instances it was not chosen on removes most overfitting, at almost no cost.

## Options

1. Let the agent compare solves as it does now, with more runs.
2. A judge in the studio: a set of instances split into train and validation, a fixed budget per
   run, paired runs, and a check of the objective against a reference; the agent proposes and the
   judge decides.
3. A tuner in optopus or optopus-py that runs a whole search over settings.

## Decision

Option 2 (`bench.py`), driven by the agent through tools.

- **The benchmark** is the project's, not a revision's: `bench/bench.json` lists the instances
  (`bench/instances/<name>.json`), each `train` or `validation`, and the runs and budget of every
  evaluation. Instances come from the user's data (`instance.json`, a revision, an app case, an
  upload) or from `generate.py`, which the agent writes and which runs in a subprocess like
  `view.py`. Each instance is stored with its SHA-256, which every result records, and a changed
  file is refused. Results are kept in `bench/results/<n>.json`. Instances can be large, and every
  revision would copy them, so revisions do not; `model.py` still reads only `instance.json`
  (ADR 0004).
- **An evaluation** solves every instance of a split with the candidate (the work files or a
  revision) and a baseline revision, one variant of each, run `i` of both sides from the same seed.
  The benchmark's budget replaces the evaluated heuristic's stop on both sides.
- **The reference** is the baseline's model. Every best solution of the candidate is scored again
  by it, with a new `--evaluate` mode of the Python worker that mirrors the Rust worker's, so
  either can be the baseline. A candidate whose objectives differ, or whose solutions the
  reference cannot decode, is rejected: it changed the problem, not the search. This is
  `verify.py`'s objective check, generalized.
- **The verdict** comes from a one-sided Wilcoxon signed-rank test over all pairs, each pair's gain
  relative to the baseline's mean on its instance, so instances of different scales count alike.
  "Better" also needs the mean worsening over the instances, counted one way so a gain on one
  instance cannot hide a loss on another, to stay within 1%. A significant gain with more
  worsening is "mixed". The test is exact up to 200 pairs, using only the standard library.
- **The loop** is the system prompt's: one hypothesis at a time against the incumbent revision on
  train, kept as a revision only when better, and the result checked against the starting
  revision on validation before it is presented.

The first option keeps every weakness above. The third cannot run a problem written in Python or
a project's Rust port, and knows nothing of revisions; what the studio needs from optopus-py is
smaller (see below).

## Consequences

- The worker protocol gains `EvaluateRequest` (`--evaluate`) and `RunFinished.n_accepted` and
  `n_rejected`, which the report shows next to the rate of iterations and the time to best, so
  the agent can tell why a candidate is worse, not only that it is. Both workers send them.
- `generate.py` is a project file, snapshotted like the others; `bench/` is exported with the
  project.
- Runs on a time budget are compared under the load of the runs beside them, so an evaluation
  runs at most half the cores at once (`OPTOPUS_STUDIO_BENCH_PARALLEL` changes it). Comparing
  settings that run at the same speed is reproducible with an iteration budget instead.
- The attempts are the evaluations: each keeps the agent's note of what changed, and a change
  was kept when a later revision has the candidate's files (`model.py`, `solve.json`,
  `rust/main.rs`, by hash), which is how the loop keeps one. Nothing else is logged, so the
  record cannot disagree with the revisions. `bench_list` shows them to the agent, and the GUI's
  Improve tab (`GET /api/projects/{id}/bench`, `BenchState`) to the user, fetched again on the
  `bench_changed` event; `bench_progress` reports a running evaluation or tuning.
- Not yet done: a common `evaluate(solution)` on every problem in optopus-py would replace the
  worker's zero-iteration run. The tuner of solve.json's settings is ADR 0014.
