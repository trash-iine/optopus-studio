# 0020. Diagnose the search, as evidence for the next hypothesis

- Status: Accepted
- Date: 2026-11-10

## Context

The judge (ADR 0013), the race (ADR 0014, 0018) and the profile (ADR 0015) all answer "which is
better". What the agent needs before it writes a candidate is "what is wrong": an evaluation's
instance lines give the rate of iterations, the time to the best and the share of moves
accepted, each a number over a whole run. They do not say whether the best solutions could
still be improved by a move the search has or lacks, where a model written in Python spends its
time, which part of the objective the hard instances suffer from, or whether the benchmark can
still tell a better search from the incumbent. The agent guesses, and its hypotheses repeat the
same few ideas.

Work on designing heuristics with a language model finds that two things move the result: the
diversity of what is tried and how deep the evidence returned for a candidate is. It also finds
that the two uses of a result should be kept apart: a scalar test selects, and richer evidence
(per instance, structural, a trace) only guides the next revision, so that what guides cannot
overfit what selects. The first campaign run on this studio showed the last question matters in
practice: after one adopted change every run of every instance ended at the same objective, and
a round of candidates could only be judged "same".

## Options

1. More numbers in the evaluation's report.
2. Per-step and per-neighborhood statistics from optopus (`RunResult`), through both workers.
3. A diagnosis in the studio, apart from every verdict: probe the incumbent's runs in a
   subprocess that only the Python model serves, and read the result into hints.

## Decision

Option 3: `diagnosis.py` and `probe.py`, the `diagnose` tool.

- **What runs**: one heuristic of a revision or of the work files, on every instance of a split
  with the benchmark's runs, seeds and budget, as one side of an evaluation does. It always runs
  `model.py`, also in a project with a Rust port: the model is the reference a port mirrors
  (ADR 0005), and only it can be wrapped and asked to explain. The probe is its own entry point
  (`python -m optopus_studio.probe`, `ProbeRequest`), not a mode of the worker protocol, so the
  Rust worker is untouched.
- **What it measures**:
  - the *gap* of each instance's runs to the best solution known on it (ADR 0018), and the
    *failure set*, the instances more than 1% away, with their sizes;
  - the *spread*: how many different objectives an instance's runs end at;
  - *probes*: from each run's best solution, a best-improving descent of at most 20 steps in
    each neighborhood (a Python problem's own, the heuristic's, or the ones named). It says
    whether the solution is a local optimum of that neighborhood;
  - *calls*, for a problem written in Python: one more run with the problem's neighborhoods and
    its `objective` wrapped to count calls and time, and the share of priced moves that would
    improve. The wrapping slows the run, so it is apart from the runs measured above;
  - *terms*: the model may define `explain(instance, solution)` returning the parts of the
    objective as numbers; they are averaged over the best solutions of the failure set and of
    the rest.
- **Readings** turn these into sentences that end with the family of change they point to
  (ADR 0018's families): a neighborhood the search leaves unused, or does not finish with; runs
  that end in different local optima; true local optima of every neighborhood, which call for a
  larger move; a search idle for most of its budget; no `delta`, or one method that takes half
  the time; a neighborhood whose moves almost never improve; a term that sets the failure set
  apart. When every run of every instance ends at the best known, that is the only reading: the
  benchmark must be made harder, or the search is done.
- **Where it goes**: the report is the tool's result; the record is kept in
  `bench/diagnoses/<n>.json` and shown in the Improve tab; a campaign's brief (ADR 0019) carries
  the latest diagnosis of the incumbent, or asks for one.
- **It judges nothing.** No verdict, race or final check reads a diagnosis.

The first option keeps the evidence at the grain of a run. The second is the more exact source
for a composition's steps and for built-in problems, and belongs in optopus-py; it changes
three repositories and the worker protocol, and the probe needs none of that to say most of
what matters.

## Consequences

- A diagnosis costs about one side of an evaluation, plus a run and the probes.
- A built-in problem is probed but not counted: its search runs compiled.
- `explain` is a third optional function of `model.py`, beside `encode_solution` and
  `decode_solution`. It takes the problem's own solution, and nothing but the diagnosis calls it.
- The thresholds (1% for the failure set, a quarter of the budget for a stall, half of a run's
  time for a heavy method, 1% of improving moves) are this studio's proposals, as the signs'
  and the readings' are.
- Not done: what each step of a composition contributes, which needs optopus to report it; and
  a comparison of the best solutions' structure across runs.
