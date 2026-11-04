# 0014. Tune a heuristic's settings by racing on the benchmark

- Status: Accepted
- Date: 2026-10-22

## Context

ADR 0013 gives the agent a judge for one change at a time. Most first changes are settings of a
heuristic: a temperature, a cooling rate, a tenure, a neighborhood. Trying them one evaluation at
a time spends a whole evaluation (every instance, every run, both sides) and a turn of the agent
on each point, and the agent guesses the next point from a few verdicts. Algorithm configuration
does this better without a model in the loop: sample many settings, run them on the same
instances and seeds, and stop running the ones that are clearly worse as soon as the evidence
says so, so the budget goes to the ones still in doubt. irace is the reference method.

## Options

1. Let the agent tune by evaluate, one setting per evaluation.
2. A racing tuner in the studio, on the benchmark, driven by one tool call.
3. A tuner in optopus or optopus-py, or irace itself (R), over a script that solves an instance.

## Decision

Option 2 (`tune.py`), the `tune` tool, a simplified irace:

- **The space** is the agent's: the parameters of one variant of a revision's solve.json by their
  path in the heuristic (`cooling_rate`, `search.tabu_tenure`, `steps.0.cooling_rate`), each a
  float or an int in a range, on a log scale or not, or a categorical. The revision's own settings
  are always raced too.
- **Choosing the heuristic too**: the agent may give several variants of solve.json instead, each
  with its parameters (none for one raced as it is), the incumbent first. The variant is then one
  more categorical parameter and each variant's parameters hang on it, as irace's conditional
  parameters do, and as AutoML's CASH joins algorithm selection and tuning. The first iteration
  races every variant's own settings and shares the Latin hypercube among the variants with
  parameters; a setting drawn around an elite switches variant with the probability of the
  iteration's spread, its parameters then drawn anew. The agent's choice of heuristics narrows the
  candidates; the race decides. The winner becomes solve.json's only heuristic, and is checked
  against the incumbent variant of the revision on validation.
- **Iterated racing**: `2 + log2(d)` iterations for `d` parameters, each given an even share of
  what is left of the budget, counted in runs. The first races the revision's settings against a
  Latin hypercube sample; each later one the elites of the last against settings drawn around
  them (a normal around a numeric value, its spread shrinking with each iteration as irace's
  does; a categorical kept or redrawn).
- **A race** runs every setting alive on the same task, a train instance under a seed, task after
  task, each run on the benchmark's budget, which replaces the heuristic's stop as in an
  evaluation. After the first five tasks, a Friedman test over the ranks on each task, and
  Conover's comparison of each setting with the best, eliminate the worse at the 5% level, as
  irace's F-race does. A race ends with its share of the budget or with `2 + log2(d)` settings
  left. A run is never repeated: a setting keeps its results on each task across iterations.
  Settings whose heuristic fails are dropped and reported; the revision's own failing is an error.
- **The check**: the best elite, when it is not the revision's own settings, is written into the
  project files, which become the revision's with that solve.json, and evaluated against the
  revision on validation (ADR 0013). The agent keeps it only on "better" there, as with any other
  change. The test statistics need only the standard library.
- **Signs**: the report ends with what the race shows that settings cannot fix, each with the
  change of structure it suggests: every elite at the outer 10% of a range (widen it, or a
  mechanism is missing); a last race that cannot tell settings apart with under a quarter of them
  dropped (the settings do not matter; change the neighborhood, the delta or the worker);
  instances whose best elite differs and beats the best overall by the evaluation's 1% (one
  setting may not fit all); the best setting finding its best in the first quarter of its runs
  (it stalls; diversify); and it accepting under 1% or over 99% of its moves. The thresholds are
  this studio's proposals, not values from the literature. They are hints for the agent's next
  hypothesis, not verdicts; known best objectives to measure the remaining gap against are not
  available, so that sign is left out.
- Each tuning, every setting's results and run statistics per task and its signs included, is
  kept in `bench/tunings/<n>.json`.

The first option spends far more of the budget on settings that are clearly worse, and an agent
turn on each. The third cannot run a Python problem or a project's Rust port, knows nothing of
revisions, and adds R or another dependency; a tuner in optopus-py would also have to be told how
to run a solve as the studio runs it.

## Consequences

- The agent tunes with one call whose cost it can predict: about budget x the run's budget / the
  cores in use. Racing with an iteration budget is reproducible; with a time budget, the
  benchmark's parallelism applies (ADR 0013).
- Several settings of a race share one worker process (up to `MAX_VARIANTS`), so the cost of
  starting the worker and building the model is paid less often; when that process fails on a
  setting, its settings run again one by one to find which.
- Validation is now used twice for a tuned change, by `tune` and by the final check of the
  improvement loop; with a few instances it is a check, not a selection, so this is accepted.
- The space's ranges are the agent's guess. A `parameter_space()` in optopus-py, saying each
  heuristic's parameters, types and valid ranges, would let the tool check the space and propose
  one; until then a setting optopus refuses fails its runs and is dropped.
