# 0015. Profile heuristics on the benchmark before composing them

- Status: Accepted; amended by 0021 (the studio builds the usual compositions from a grammar)
- Date: 2026-10-31

## Context

ADR 0014 lets the race choose among the variants the agent writes, and set their nested
settings. Which variants to write is still the agent's guess: it names a few heuristics it knows,
and a composition (a `Sequential`, an `Iterated`) only when it thinks of one. A composition
should come from what the parts do. One heuristic that gets close fast and stalls, joined to
another that starts slowly and ends best, makes a `Sequential`. A search that stops at its local
optimum long before the budget ends makes an `Iterated` with a kick. Instances that each prefer a
different heuristic call for one that adapts within a run. Neither a verdict (ADR 0013) nor a
race (ADR 0014) says any of this. Each compares where runs end, not how they got there.

The agent also knows the literature only as far as its model does. It cannot tell which of
optopus's heuristics a published method corresponds to, or how to build one optopus has no
class of.

## Options

1. Let the agent read convergence from `run_solver` on one instance, as it can now.
2. A profile on the benchmark: every candidate on every instance with the benchmark's runs, seeds
   and budget, reporting how each one behaves, with readings that name compositions.
3. Search the space of compositions automatically, in a grammar over heuristic trees
   (grammatical evolution, irace over a grammar) or by evolving them with a model (FunSearch-like
   loops).

## Decision

Option 2: `profiling.py` and the `profile` tool, together with a page of recipes the agent reads.
The agent still writes the compositions, and `tune` still races them.

- **The candidates** are the variants of a solve.json, in the work files or a revision. A
  profile changes no file and makes no revision.
- **The runs** are an evaluation's (ADR 0013): every instance of a split, the benchmark's runs
  under its seeds, and its budget in place of each heuristic's stop. All candidates therefore start
  from the same solutions and have the same time.
- **What it reports** for each candidate:
  - its mean rank over the runs, each an instance under a seed, with a Friedman test and Conover's
    comparison against the best, as in a race;
  - the instances it wins;
  - its *anytime profile*: the mean gap of its best so far to the best any candidate found on the
    instance, at 10%, 25%, 50% and 100% of the budget. The profile reads this from the run's
    trajectory, against the limit that stopped the run: its iterations when it spent them (or the
    budget has no time), its time otherwise, so a run that stops on its own is measured against
    the time it had;
  - how far into the budget its best was found;
  - its iterations per second and its share of moves accepted.
- **Readings**, the hints it gives for the next variants:
  - a candidate that leads early on two thirds of the instances while another ends best suggests a
    `Sequential` of the two, with the shares of the steps tuned;
  - a candidate not clearly worse than the best that finds its best in the first quarter of the
    budget (it stalls or stops) suggests `Iterated`, `Restart` or a VNS around it;
  - instances whose winners differ, where on some the best candidate is beaten by more than the
    evaluation's 1%, suggest a heuristic that adapts within a run, and something to tell the user;
  - candidates the Friedman test cannot tell apart point to the neighborhood, the delta or the
    worker rather than the heuristic.

  Like tune's signs, the thresholds are this studio's proposals, not values from the literature.
- **Recipes**: `guides/recipes.md`, read as the `recipes` page of `read_docs`. It says, for common
  kinds of problem, which methods the literature reports to work, with their sources, and gives
  each as solve.json: one of optopus's classes, or a composition when optopus has none (ILS,
  iterated tabu, two phases, VND/VNS, multi-start, GRASP, memetic). It also lists the paths worth
  tuning. A move that a method depends on, and that no heuristic provides, is a neighborhood to
  write in model.py. `tests/test_recipes.py` builds every recipe and runs it on a small Python
  problem, so a recipe that no longer fits optopus fails the tests.
- **The prompt** adds a step before refining one change at a time:
  1. name the problem in the literature's terms;
  2. read the recipes, and search the web when allowed (ADR 0016);
  3. profile four to six candidates;
  4. write the two to four compositions the readings suggest;
  5. race them with `tune`'s spaces, with the best single heuristics.
- Each profile is kept in `bench/profiles/<n>.json`, travels with an exported project, and shows
  in the Improve tab: a table per profile, the leader at each share of the budget in bold, and its
  readings.

The first option judges on one instance and a few seeds, what ADR 0013 set out to stop. The
third is research and would multiply the runs. The race would have to search structures and
their conditional parameters at once (one more level of ADR 0014's variants). Racing a handful of
compositions, chosen from evidence, is the part of it that fits the budget of an interactive
session.

## Consequences

- A profile costs about variants x instances x runs x budget / the cores in use. The agent profiles
  once to choose a structure, not after every change.
- The race still decides. A reading that suggests a composition is only a hypothesis until the
  composition wins its race and its evaluation on validation.
- The recipes are kept by hand. They point to methods; they do not prove that one works on a given
  problem. New methods come from the agent's own knowledge or from the web (ADR 0016), not from
  this page.
- The race still searches only the structures the agent wrote. A grammar over compositions in
  `tune` stays possible later, on top of the same records.
