# Projects, revisions and files

You never have to write these files yourself; the agent does. Knowing what they are helps you read
the **Model** tab, ask for precise changes, and judge a result.

## Project and revision

A **project** is one task and its conversation: "plan our delivery routes", "schedule the
workshop". It holds the files the agent is editing, the chat, the files you attached, and its
revisions.

A **revision** is one solve. Each time the agent runs the solver, the current files are copied
next to what they produced (the result and the views) and numbered 1, 2, 3, …. A revision never
changes afterwards, so you can always go back to it, compare it, or package it. It carries its own
data, so it solves the same way later even if you attach new files
([ADR 0004](../adr/0004-import-uploads-into-the-instance.md)).

## The files

| File | What it is | Ask for a change like |
|---|---|---|
| `instance.json` | the data: cities, jobs, items, capacities, imported rows | "add a fourth truck", "use the new demand file" |
| `model.py` | the optimization problem: what is decided, the objective, the constraints | "late deliveries should cost twice as much" |
| `solve.json` | how to search: the heuristic, its parameters, when to stop, how many runs, the seed | "run 10 times for 5 seconds each" |
| `view.py` | what the canvas draws from the result | "show each machine's idle time" |
| `rust/main.rs` | optional: the model ported to Rust, for speed | "port to Rust" |
| `app.json` | optional: what a packaged app lets its user change | "make this an app where the user uploads the orders" |
| `generate.py` | optional: makes instances for the benchmark, like yours but more of them | "improve the search on instances like this one" |

`model.py` builds the problem in one of three ways, the first that fits: one of optopus's
**built-in problems** (TSP, vehicle routing, job shop scheduling, …), a **`Formula`** (a
polynomial objective and constraints over its variables, such as one yes/no per item), or a
**problem written in Python** (anything else: a maximum, a lookup, a simulation). The first two search in Rust; the
third calls Python on every move, which is what **Port to Rust** speeds up.

A constraint that must hold either is part of the representation (a tour visits every city once)
or becomes a penalty large enough that breaking it never pays; the agent's views report any
violation.

`solve.json` of the knapsack example:

```json
{
  "heuristic": {
    "kind": "SimulatedAnnealing",
    "neighbor": "Flip",
    "initial_temperature": 30.0,
    "cooling_rate": 0.999,
    "stop": {"max_iteration": 5000}
  },
  "runs": 3,
  "seed": 0
}
```

Three runs of simulated annealing, each stopping after 5000 iterations, seeded so the same files
give the same result. To compare heuristics, `"heuristics"` lists several, each with a label (see
[`examples/workload/solve.json`](../../examples/workload/solve.json)).

### Starting from a solution

Every run starts from a random solution unless `solve.json` names one:
`"initial_solution": "plan"` starts every run from `instance.json`'s `"plan"`. The solution is in
the form the result shows it, which `model.py`'s `encode_solution` writes and its
`decode_solution` reads back (the workload example has both). It is how to:

- **score a plan of your own**, such as the current schedule. Attach it and ask the agent to start
  from it: each run's initial objective is then what your plan scores, and the best objective how
  much the search improved on it.
- **keep searching from an earlier result** ("keep going from revision 3"). The agent copies that
  revision's best solution into `instance.json`, so the new revision holds what it started from
  ([ADR 0011](../adr/0011-start-from-a-solution-in-the-instance.md)).

A solution that does not fit the problem, such as a tour that visits a city twice, stops the solve
at the start stage.

## Improving the algorithm

Ask the agent to make the search better, or to improve it on its own for a number of rounds or
a time:

> Improve the search on your own for 20 minutes; a solve may take 5 seconds.

Asked to improve on its own, the agent builds the benchmark and starts a **campaign**, which the
studio drives ([ADR 0019](../adr/0019-drive-the-improvement-loop-from-the-studio.md)). The studio
gives the agent a turn per round, each with a brief of where the campaign stands, and ends it
when the rounds or minutes are spent, when three rounds in a row bring nothing, or when you
press **Stop**. The studio then checks the result itself, as described below, and the agent
tells you what came of it.

It does not judge a change on one solve, which rewards luck and changes fitted to one instance.
It first builds a **benchmark**: a few **train** instances and two or three **validation** ones,
from your data and, when that is too little, from a `generate.py` it writes. Then it works in
rounds. In each it writes three or four changes of different kinds (another heuristic or
setting, a faster or richer `model.py`, a Rust port), saves each as a **candidate** with the
hypothesis it tests, and **races** them against the current revision: all solve every train
instance with the same seeds and the same budget per run, the current revision once, and a
paired test gives each candidate its verdict
([ADR 0018](../adr/0018-race-saved-candidates-against-the-incumbent.md)). The studio lets the
agent **adopt** only a candidate judged better. A candidate that scores the current revision's
solution otherwise is refused before it runs.

| Verdict | Meaning |
|---|---|
| better | significantly better, and on no instance more than 1% worse on average |
| mixed | better overall, but clearly worse on some instances; not taken |
| same | no significant difference |
| worse | significantly worse |
| rejected | the change scores solutions otherwise: it changed the problem, not the search |
| failed | the candidate could not solve an instance |

To tune a heuristic's settings (a temperature, a rate, a tenure, which neighborhood), the agent
does not try them one evaluation at a time: it names the parameters and their ranges, and the
studio **races** sampled settings on the train instances, as irace does. Every setting still in
the race runs on the same instance and seed, and after a few of them a Friedman test drops the
settings that are clearly worse, so the runs go to the ones still in doubt. The best is written
into `solve.json` and evaluated against the revision on the validation instances, like any other
change ([ADR 0014](../adr/0014-tune-settings-by-racing.md)). When several heuristics could suit,
the agent races them all, each with its own parameters, so the race chooses the heuristic too, and
the winner becomes `solve.json`'s only one. The report ends with **signs** of what settings cannot
fix: the best settings at the edge of a range, settings that barely matter, instances that prefer
different settings, a search that stalls early or accepts almost no move or almost every one. The
agent reads them to choose its next change, and tells you when the instances want different
settings.

Before it refines one change at a time, the agent chooses the structure of the search from
evidence ([ADR 0015](../adr/0015-profile-heuristics-before-composing-them.md)). It names your
problem in the literature's terms and reads the studio's **recipes**: the methods reported to work
on that kind of problem, and how to build one that optopus has no class of from optopus's
heuristics (iterated local search, two phases, VNS, multi-start, GRASP, a memetic algorithm). It
puts four to six candidates in `solve.json` and **profiles** them on the benchmark. Each
candidate solves every train instance with the benchmark's runs and budget, and the profile
reports:

- its rank, and the instances it wins;
- how far its best so far is from the best found, at 10%, 25%, 50% and the end of the budget;
- how early it found its best.

From this the profile reads the compositions worth trying:

- one candidate that leads early and another that ends best make a `Sequential` of the two;
- a candidate that stalls goes inside an `Iterated` with a kick;
- instances that prefer different heuristics want one that adapts within a run.

The agent writes those as variants and races them with the best single heuristics, so the race
chooses the composition and sets the settings inside it. It can also name the heuristics as the
leaves of a **grammar** and let the studio build the usual compositions of them, each step with
a stop of its own to tune, the ones the profile favors first
([ADR 0021](../adr/0021-build-compositions-from-a-grammar-of-leaves.md)).

With **Web search** on in the chat panel, the agent also searches the web for methods reported on
problems like yours ([ADR 0016](../adr/0016-let-the-agent-search-the-web-when-allowed.md)). It
is off by default. Each search shows as a tool line. What the agent reads only suggests
candidates; the benchmark still judges every change, and the agent names its source in the
change's note.

Only a better change is solved into a new revision; the others stay in the ledger with the
lesson the agent drew from them, so it does not try one twice and sees which kinds of change it
has not tried. The canvas's
**Improve** tab follows along: the benchmark's instances, the hypotheses, every change judged
with its verdict, gain and the revision it was solved into (click one for each instance), every
tuning and every profile. At the end of a campaign the studio
evaluates the final revision against the one it started from on the validation instances, which
none of the choices were made on. It keeps the improvement only if it holds there, and otherwise
makes the files the starting revision's again.

The benchmark may also hold **test** instances. Nothing is chosen on them: a campaign measures
the result it kept on them, after every choice was made.

The budget of the evaluation replaces each heuristic's own stop, so a change cannot win by
running longer. The objective is fixed by the revision the change is compared with: its model
scores the candidate's solutions again, so a change of a penalty weight is caught. Changing what
is optimized is a change of the model, which the agent agrees with you first. The benchmark,
every evaluation, tuning and profile are kept in the project's `bench/` folder and exported with it
([ADR 0013](../adr/0013-improve-against-a-benchmark-of-instances.md)).

## The examples

[`examples/`](../../examples/) holds four complete projects; the tests solve each one:

| Example | Problem | Written as |
|---|---|---|
| `tsp` | the shortest tour through cities | built-in `Tsp`, with a Rust port |
| `job_shop` | jobs on machines, finished as early as possible | built-in job shop scheduling |
| `knapsack` | the most value within a weight capacity; also has an `app.json` | `Formula` |
| `workload` | tasks to skilled workers, so the busiest finishes earliest; compares three heuristics | Python, with a Rust port |

They are not projects you open in the studio. To try one, attach its `instance.json` with **+**
and ask for the same task, for example "pack the most value into a capacity of 20 with these
items". Reading an example's `model.py` and `view.py` next to the Model tab is a good way to see
what the agent writes.

## Sharing a project

**Export** in the header downloads the project as a zip: the chat, every revision and the attached
files. Whoever receives it opens it with **Import**, which adds it as a new project. Their agent
starts a new session that reads the conversation first
([ADR 0007](../adr/0007-share-a-project-as-a-zip.md)).

## Turning a model into an app

When a model is ready for people who will not talk to the agent, ask the agent to make it an app.
It writes `app.json`, naming the tables the app's user may replace and the settings they may
change. **Package** above the canvas then downloads the selected revision as a zip, which runs
without the agent or a login:

```bash
uv run optopus-studio app optopus-app-<project>-r<rev>.zip   # http://127.0.0.1:8766
```

Its user gives their own files, sets the values, solves, and sends you an exported case when
something looks wrong. Attach that case with **+** in the studio and the agent reproduces it. To
hand an app to someone without this repository, build it into a Docker image. Both are described
in the [README](../../README.md#packaging-a-model-as-an-app).
