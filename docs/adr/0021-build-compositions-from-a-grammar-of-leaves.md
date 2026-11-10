# 0021. Build compositions from a grammar of leaves, and race them

- Status: Accepted
- Date: 2026-11-10

## Context

ADR 0015 chose to let the agent write the compositions a profile's readings suggest, and left
"a grammar over compositions in `tune`" for later. In use, writing them is the dull part of
improving a search and the part most often cut short: a `Sequential` of two heuristics in both
orders, each step with a stop sized to the budget, the same heuristics inside `Iterated`,
`Restart` and `VariableNeighborhoodSearch`, and for each the paths of the parameters worth
tuning. The agent writes two or three and stops, so the race (ADR 0014) chooses among few
structures, and a step's stop the agent guessed is often not among the parameters it gives.

Searching composition trees freely (grammatical evolution, irace over a full grammar) would
multiply the runs, which ADR 0015 already rejected for an interactive session.

## Options

1. Keep the compositions hand-written; say more about them in the prompt.
2. A small fixed grammar of depth one over leaves the agent names, expanded by the studio into
   variants with their parameters, ordered by the profile, cut to a limit, and handed to the
   race there is.
3. A full grammar with nesting, searched by the tuner as conditional parameters.

## Decision

Option 2: `compose.py`, as `grammar` of the `tune` tool.

- **Leaves** are variants of the revision's solve.json, each with its parameters as in `spaces`,
  the incumbent first. Choosing them stays the agent's, from the recipes, the profile and its
  sources.
- **Templates**, each one composition per leaf or ordered pair of leaves:
  - `sequential`: `Sequential` of two leaves, both orders;
  - `iterated`: `Iterated`, the leaf as the search, a `RandomWalk` of five moves as the kick;
  - `restart`: `Restart` of the leaf, an attempt ending after 2000 iterations without a new best;
  - `vns`: `VariableNeighborhoodSearch`, the leaf as the search, shakes of 2, 4 and 8 moves.
- **Stops**: a leaf inside a composition gets a stop of its own, a tenth of the benchmark's
  budget in the budget's own measure (iterations or seconds), and that stop is a parameter of
  the race, from a hundredth to half of the budget on a log scale. The kick's length (1 to 50)
  and a restart's patience (50 to 50000) are parameters too, and the kick's neighborhood is a
  choice when the grammar names several (`kicks`). A leaf's own parameters move with it
  (`tabu_tenure.1` becomes `steps.1.tabu_tenure.1`).
- **Order and limit**: with a profile of the revision that ran every leaf, a `Sequential` is
  ranked by how early its first leaf leads and how well its second ends, and the others by how
  well their leaf ends, ahead when it finds its best in the first quarter of the budget.
  Without one, the templates take turns in the order of the leaves. The first `limit` (12 by
  default) are raced.
- **The race** is ADR 0014's, unchanged: the compositions join the revision's variants as if
  solve.json had listed them, and the leaves and compositions form one space. The winner
  becomes solve.json's only heuristic and is checked on validation as before.
- **The budget**: every variant's own settings race from the first iteration, so the least
  budget is `iterations x variants x 6` runs, and the tool refuses less, saying the number.

The first option is what there was. The third makes the space large enough that the race needs
far more runs than a session has, for structures (three levels of nesting) that the readings
rarely call for; the agent can still write one by hand and race it as a leaf.

## Consequences

- One call now covers what took the agent several files of solve.json and a guessed space.
  Profiling the leaves first makes the limit cut what matters least.
- The grammar builds nothing a profile cannot suggest: no population, no VND as a search, no
  three-step sequence. Those stay hand-written, and the recipes say how.
- The defaults (a tenth of the budget, five moves, 2000 iterations) are this studio's starting
  points, not values from the literature; they are tuned by the race, not trusted.
- `tests/test_compose.py` builds every template and runs it on a small Python problem, as the
  recipes are tested.
