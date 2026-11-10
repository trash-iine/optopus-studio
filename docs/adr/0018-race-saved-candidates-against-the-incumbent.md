# 0018. Race saved candidates against the incumbent, and keep a ledger of them

- Status: Accepted
- Date: 2026-11-10

## Context

ADR 0013 judges one change at a time: the work files against a revision. A change to `model.py`
(a neighborhood, a cheaper delta, a representation) can only be tried that way, since `tune`
(ADR 0014) races variants of one solve.json. Three weaknesses follow.

- **One hypothesis a round.** Each evaluation runs both sides, so `k` hypotheses cost `2k` sides,
  and the agent tries them in turn. A round whose one hypothesis fails brings nothing, and a
  loop that stops after a few rounds without a gain then stops early. Running several candidates
  a round raises the worst case far more than the best (the literature on agent loops for
  heuristic design reports the same: parallel candidates buy variance, not peaks).
- **The record is a note.** An evaluation keeps the agent's note and the verdict. What kind of
  change it was, what suggested it and what its result taught are not kept, so the agent cannot
  see which kinds of change it has not tried, and repeats itself after its context is cut.
- **Validation is used again and again**, by every tuning and by the final check, and nothing
  says how far the incumbent still is from the best solutions seen.

The rule that only a better change is kept is also only prose in the system prompt.

## Options

1. Keep one change at a time; ask the agent in the prompt to note more.
2. Let `evaluate` take several revisions as candidates.
3. Saved candidates: the work files copied aside with their hypothesis, raced together against
   the revision they change, and adopted by the studio only when judged better.

## Decision

Option 3 (`candidates.py`, and `compare` in `bench.py`).

- **A candidate** is `bench/candidates/<n>/` (the files that make the algorithm: `model.py`,
  `solve.json`, `rust/main.rs`) and `bench/candidates/<n>.json`: the revision it changes, its
  hypothesis, its *family* (settings, heuristic, composition, neighborhood, delta,
  representation, start, port), the evidence that suggested it, and later a lesson.
  `candidate_save` makes one from the work files and puts the work files back to that revision,
  so several are written one after another. It makes no revision: the history holds only what
  was solved.
- **Gates** refuse a candidate before any run is spent on it: the same files saved before
  (pointing at that entry of the ledger), files that change nothing, a port that does not build,
  and a model that scores the baseline's own solutions (from its `result.json`) otherwise than
  the baseline did. The last is the reference check of ADR 0013 the other way round, and costs
  one `--evaluate` call.
- **A race** (`race`) solves the train instances with the baseline once and with every candidate,
  all from the same seeds on the benchmark's budget. Each candidate is paired with the
  baseline's runs and gets the evaluation `evaluate` would have made of it, reference check
  included, kept in `bench/results` as any other. A Friedman test ranks them all. The winner is
  the best-ranked candidate whose own verdict is "better". `k` candidates cost `k + 1` sides.
- **Adopting** (`adopt`) is the studio's: a candidate whose evaluation is not "better" is
  refused, and so is one judged against a revision that is no longer the incumbent. An adopted
  candidate's files become the work files and are solved into a revision.
- **The ledger** is the candidates' records with the verdicts read from their evaluations, so it
  cannot disagree with them (ADR 0013's rule). `bench_list` shows it with the families tried and
  not tried, and the Improve tab as "Hypotheses".
- **The best known**: `bench/best.json` keeps, per instance, the best solution of any judged
  evaluation, whose objectives the reference confirmed. It is dropped when the instance is
  replaced. The solution is kept with its objective, so a later reader can score it again under
  another model.
- **A test split**: an instance may be `test`. No tool the agent chooses with runs on it
  (`evaluate`, `profile`, `tune` and `race` refuse it, and "all" means train and validation). It
  measures the result that is reported, after every choice was made.

The first option leaves the cost and the empty rounds. The second fills the history with
revisions that lost, each of which `run_solver` would have had to solve first.

## Consequences

- A candidate that is the best of `k` on train is judged on the same runs it was chosen on, so
  its verdict is more optimistic than one evaluation's. The final check on validation, and the
  test split, are what guard against that; the race does not correct its p-values.
- A race runs every candidate on every task. It does not drop losers early as a tuning's race
  does: with a handful of candidates the saving is small, and full runs are what give each its
  own verdict.
- `bench/candidates`, `bench/races` and `bench/best.json` are exported with the project.
- `evaluate` on the work files stays, for the one change the evidence suggests.
- Not yet done: the studio does not run the test split or drive the rounds itself; that is the
  campaign of ADR 0019. Tunings and profiles do not feed `best.json` yet.
