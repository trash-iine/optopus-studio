# Recipes: methods that work on a kind of problem, built from optopus's heuristics

This page is the studio's, not optopus-py's. It says which methods the literature reports work
on common kinds of problem, and how to write each in solve.json, as one of optopus's heuristics
or as a composition of them when optopus has no class of that name. Treat it as where to start
looking, not as the answer: profile the candidates on the benchmark, race the promising ones
with `tune`, and keep only what wins on validation.

In the recipes, `"Move"` and `"Swap"` stand for the problem's own neighborhoods, by the names
model.py gives them (or a built-in problem's, see the `problems` page). Every recipe's stop is
replaced by the benchmark's budget when it is evaluated, profiled or tuned; the stops of the
steps inside it are kept, and are worth tuning. A step starts afresh each time it is called (an
annealing step at its initial temperature), so give it a short schedule of its own, not one
sized for the whole run (see the `heuristics_composed` page).

## 1. Which methods to try, by kind of problem

Name the problem in the literature's terms first ("a generalized assignment problem with a
balance objective", "a capacitated VRP with time windows"), then start from its row.

| Kind of problem | Methods reported to work | In optopus |
|---|---|---|
| Traveling salesman | Lin-Kernighan-Helsgaun (Helsgaun 2000); ILS with 2-opt / Or-opt and a double-bridge kick (Johnson & McGeoch 1997) | `LinKernighanHelsgaun`; ILS below |
| Vehicle routing | Hybrid genetic search (Vidal 2022); ALNS (Ropke & Pisinger 2006) | `HybridGeneticSearch`, `AdaptiveLargeNeighborhoodSearch` |
| Assignment of tasks to agents with capacities (generalized assignment, workload balancing) | Tabu search and annealing over shift and swap moves (Osman 1995; Díaz & Fernández 2001); ILS; ejection chains (Yagiura, Ibaraki & Glover 2004) | `TabuSearch`, `SimulatedAnnealing`, ILS and VNS below; an ejection chain is a neighborhood to write |
| Flow shop | Iterated greedy (Ruiz & Stützle 2007) | `IteratedGreedy` |
| Job shop | Tabu search over critical-path moves (Nowicki & Smutnicki 1996) | `TabuSearch` on `JobShopScheduling` |
| Quadratic assignment | Robust / iterated tabu search (Taillard 1991; Misevicius 2005) | `TabuSearch`; iterated tabu below |
| Max cut, QUBO | Breakout local search (Benlic & Hao 2013); tabu search | `BreakoutLocalSearch`, `TabuSearch` |
| SAT | WalkSAT (Selman, Kautz & Cohen 1994) | `WalkSat` |
| Graph coloring | TabuCol (Hertz & de Werra 1987); hybrid evolutionary (Galinier & Hao 1999) | `TabuSearch`; memetic below |
| Bin packing | Iterated greedy, ALNS | `IteratedGreedy`, `AdaptiveLargeNeighborhoodSearch` |
| Knapsack and covering with a construction | GRASP (Feo & Resende 1995) | GRASP below, on a problem with ruin methods |
| Anything with a slowly varying, rugged objective | Late acceptance (Burke & Bykov 2017); annealing (Kirkpatrick et al. 1983) | `LateAcceptanceHillClimbing`, `SimulatedAnnealing` |

## 2. Compositions for methods optopus has no class of

Each is a whole `"heuristic"` of solve.json. The paths after it are the arguments most worth
giving `tune`.

### Iterated local search (Lourenço, Martin & Stützle 2003)

A descent to a local optimum, a small random kick, and again. The usual first composition for a
search that stalls.

```json
{"kind": "Iterated",
 "search": {"kind": "LocalSearch", "neighbor": "Move", "stop": {"max_iteration": 5000}},
 "perturbation": {"kind": "RandomWalk", "neighbor": "Move", "stop": {"max_iteration": 5}},
 "stop": {"max_duration_secs": 1.0}}
```

Tune `perturbation.stop.max_iteration` (the kick's strength, int, 1 to a tenth of the size).

### Iterated annealing or tabu (Misevicius 2005)

ILS whose search is a short annealing or tabu run, for problems where a plain descent ends too
soon.

```json
{"kind": "Iterated",
 "search": {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [5, 15],
            "stop": {"max_iteration": 2000}},
 "perturbation": {"kind": "RandomWalk", "neighbor": "Swap", "stop": {"max_iteration": 10}},
 "stop": {"max_duration_secs": 1.0}}
```

Tune `search.tabu_tenure.0`, `search.tabu_tenure.1`, `search.stop.max_iteration` and
`perturbation.stop.max_iteration`.

### Two phases: explore, then intensify

A heuristic that leads early, then one that ends best, as a profile reads them. The pair runs
again and again until the budget ends, each step to its own stop.

```json
{"kind": "Sequential",
 "steps": [
   {"kind": "SimulatedAnnealing", "neighbor": "Move", "initial_temperature": 2.0,
    "cooling_rate": 0.999, "stop": {"max_iteration": 5000}},
   {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [5, 15],
    "stop": {"max_iteration": 5000}}],
 "stop": {"max_duration_secs": 1.0}}
```

Tune the steps' shares (`steps.0.stop.max_iteration`, `steps.1.stop.max_iteration`) with
their own settings (`steps.0.cooling_rate`, `steps.1.tabu_tenure.1`).

### Variable neighborhood descent and search (Mladenović & Hansen 1997)

A descent over each neighborhood in turn (VND) polishes with all of them:

```json
{"kind": "Sequential",
 "steps": [
   {"kind": "LocalSearch", "neighbor": "Move", "stop": {"max_iteration": 5000}},
   {"kind": "LocalSearch", "neighbor": "Swap", "stop": {"max_iteration": 5000}}],
 "stop": {"max_duration_secs": 1.0}}
```

VNS kicks harder the longer it stays stuck:

```json
{"kind": "VariableNeighborhoodSearch",
 "search": {"kind": "LocalSearch", "neighbor": "Move", "stop": {"max_iteration": 5000}},
 "shakes": [
   {"kind": "RandomWalk", "neighbor": "Swap", "stop": {"max_iteration": 2}},
   {"kind": "RandomWalk", "neighbor": "Swap", "stop": {"max_iteration": 4}},
   {"kind": "RandomWalk", "neighbor": "Swap", "stop": {"max_iteration": 8}}],
 "stop": {"max_duration_secs": 1.0}}
```

Tune `shakes.0.stop.max_iteration` and the others, or put the VND above as the `search`.

### Multi-start

Many short searches from random starts, when each converges fast and the basins differ.

```json
{"kind": "Restart",
 "heuristic": {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [5, 15],
               "stop": {"max_failed_update": 2000}},
 "restart": {"max_iteration": 0},
 "stop": {"max_duration_secs": 1.0}}
```

Tune `heuristic.stop.max_failed_update` (how long an attempt runs).

### GRASP (Feo & Resende 1995)

A randomized greedy construction, then a descent, again and again. It needs a problem that
`GreedyRandomizedConstruction` runs on: `Vrp`, `Tsp`, `FlowShop`, `BinPacking`, or a Python
problem with the ruin methods (the `python_problems` page).

```json
{"kind": "Iterated",
 "search": {"kind": "LocalSearch", "neighbor": "Move", "stop": {"max_iteration": 5000}},
 "perturbation": {"kind": "GreedyRandomizedConstruction", "alpha": 0.2},
 "stop": {"max_duration_secs": 1.0}}
```

Tune `perturbation.alpha` (0 greedy, 1 random).

### Memetic algorithm (Moscato 1989; Galinier & Hao 1999)

A population recombined by the problem's crossover, every child improved by a short search. A
Python problem needs a `crossover(a, b, rng)` method (and `distance(a, b)` for the selections
that read diversity).

```json
{"kind": "GeneticAlgorithm", "population_size": 20,
 "mutation": {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [5, 15],
              "stop": {"max_iteration": 500}},
 "stop": {"max_duration_secs": 1.0}}
```

Tune `population_size` and `mutation.stop.max_iteration`.

### A search that adapts its moves within a run

When instances prefer different heuristics, one that learns which moves pay during the run may
fit them all: `ReinforcementLearningSearch` over the problem's neighborhood, or
`AdaptiveLargeNeighborhoodSearch` on a problem with ruin methods.

```json
{"kind": "ReinforcementLearningSearch", "neighbor": "Move", "learning_rate": 0.01,
 "max_candidates": 32, "stop": {"max_duration_secs": 1.0}}
```

Tune `learning_rate` (log) and `softmax_temperature` (log).

## 3. When a method is neither a class nor a composition

Take the method apart into what it builds with (a construction), how it improves (a descent, a
tabu or annealing walk), how it escapes (a kick, a restart, a population), and the moves it makes
them with. The first three map to the heuristics and compositions above. A move the method
depends on (an ejection chain, Or-opt, a Kempe chain, a move along a critical path) is a
neighborhood to write in model.py, with its own `delta`; then use it by name in the
composition. Say to the user what the studio's version leaves out of the published method, and
name the source in the evaluation's note.
