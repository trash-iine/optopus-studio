"""Tuning a heuristic's settings on the benchmark by iterated racing (docs/adr/0014).

The agent names the parameters of one variant of a revision's solve.json, with their ranges, and
a budget of runs. ``tune`` then searches without the agent, as irace does, simplified:

- **sampling**: the first iteration races the revision's own settings against a Latin hypercube
  sample of the space; each later one races the elites of the last against settings drawn
  around them, ever closer.
- **racing**: every setting alive runs on the same task, a train instance and a seed, one task
  after another, each run on the benchmark's budget. After the first ``FIRST_TEST`` tasks, a
  Friedman test over the ranks on each task, and Conover's comparison with the best, eliminate
  the settings that are worse, so the budget goes to the ones still in doubt. A run is never made
  twice: an elite keeps its results on the tasks it ran.

The best elite is written into solve.json, and judged against the revision on the validation
split with ``bench.evaluate``, so the settings are checked on instances they were not chosen on.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import random
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from optopus_studio import bench
from optopus_studio.bench import ALPHA, ranks
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import MAX_VARIANTS, BenchProgress, RunSummary, Variant
from optopus_studio.runner import run_solve
from optopus_studio.solving import solve_timeout

# Tasks every setting of a race runs before the first test, and the tests' level.
FIRST_TEST = 5
# Values this close rank as a tie.
TIE = 1e-12

PATH = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+))*\Z")


class Parameter(BaseModel):
    """One argument of the heuristic to tune: a float or an int in [low, high], or one of
    ``choices``. ``name`` is its path in the heuristic, such as "initial_temperature", or
    "search.cooling_rate" in a nested heuristic, or "steps.0.tabu_tenure" in a list."""

    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["float", "int", "categorical"] | None = None
    low: float | None = None
    high: float | None = None
    log: bool = False
    choices: list[Any] | None = None

    @model_validator(mode="after")
    def check(self) -> Parameter:
        if not PATH.match(self.name):
            raise ValueError(f"{self.name!r} is not a path like cooling_rate or search.tenure")
        segments = self.name.split(".")
        if segments[0] == "stop" or segments[-1] == "kind":
            raise ValueError(f"{self.name!r}: the stop is the benchmark's, and kind cannot vary")
        if self.type is None:
            self.type = "categorical" if self.choices is not None else "float"
        if self.type == "categorical":
            if not self.choices or len(self.choices) < 2:
                raise ValueError(f"{self.name!r} needs two or more choices")
            if self.low is not None or self.high is not None or self.log:
                raise ValueError(f"{self.name!r} has choices; low, high and log are for numbers")
            return self
        if self.choices is not None:
            raise ValueError(f"{self.name!r} is a {self.type}; choices are for a categorical one")
        if self.low is None or self.high is None or not self.low < self.high:
            raise ValueError(f"{self.name!r} needs low < high")
        if self.log and self.low <= 0:
            raise ValueError(f"{self.name!r} is sampled on a log scale, so low must be above 0")
        if self.type == "int" and not (self.low.is_integer() and self.high.is_integer()):
            raise ValueError(f"{self.name!r} is an int, so low and high must be whole")
        return self

    def _bounds(self) -> tuple[float, float]:
        """The interval values are drawn from: log-scaled, and one wider for an int, whose
        values are the floors."""
        assert self.low is not None
        assert self.high is not None
        high = self.high + 1 if self.type == "int" else self.high
        return (math.log(self.low), math.log(high)) if self.log else (self.low, high)

    def _value(self, z: float) -> Any:
        assert self.low is not None
        assert self.high is not None
        x = math.exp(z) if self.log else z
        if self.type == "int":
            return int(min(max(math.floor(x), self.low), self.high))
        return min(max(x, self.low), self.high)

    def _position(self, value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        x = value + 0.5 if self.type == "int" else float(value)
        if self.log:
            return math.log(x) if x > 0 else None
        return x

    def at(self, u: float) -> Any:
        """The value at ``u`` in [0, 1) of the space, evenly."""
        if self.choices is not None:
            return self.choices[min(int(u * len(self.choices)), len(self.choices) - 1)]
        lo, hi = self._bounds()
        return self._value(lo + u * (hi - lo))

    def near(self, value: Any, spread: float, rng: random.Random) -> Any:
        """A value drawn around ``value``, within ``spread`` of the space's width."""
        if self.choices is not None:
            if value not in self.choices or rng.random() < spread:
                return rng.choice(self.choices)
            return value
        center = self._position(value)
        if center is None:
            return self.at(rng.random())
        lo, hi = self._bounds()
        for _ in range(20):
            z = rng.gauss(center, spread * (hi - lo))
            if lo <= z < hi:
                return self._value(z)
        return self._value(min(max(center, lo), hi))


# --- statistics --------------------------------------------------------------------------------


def chi2_sf(x: float, df: int) -> float:
    """P(X > x) for chi-squared with ``df`` degrees of freedom (Abramowitz & Stegun 26.4.4-5)."""
    if x <= 0:
        return 1.0
    if df % 2 == 0:
        term = total = 1.0
        for j in range(1, df // 2):
            term *= x / 2 / j
            total += term
        return min(1.0, math.exp(-x / 2) * total)
    term, total = math.sqrt(x), 0.0
    for j in range(1, (df - 1) // 2 + 1):
        total += term
        term *= x / (2 * j + 1)
    tail = math.erfc(math.sqrt(x / 2))
    return min(1.0, tail + math.sqrt(2 / math.pi) * math.exp(-x / 2) * total)


def t_sf(t: float, df: int) -> float:
    """P(T > t) for Student's t with ``df`` degrees of freedom (Abramowitz & Stegun 26.7.3-4)."""
    if t < 0:
        return 1 - t_sf(-t, df)
    theta = math.atan(t / math.sqrt(df))
    sin, cos = math.sin(theta), math.cos(theta)
    if df % 2 == 0:
        term = total = 1.0
        for j in range(1, df // 2):
            term *= cos * cos * (2 * j - 1) / (2 * j)
            total += term
        inside = sin * total
    else:
        term, total = cos, 0.0
        for j in range(1, (df - 1) // 2 + 1):
            total += term
            term *= cos * cos * (2 * j) / (2 * j + 1)
        inside = 2 / math.pi * (theta + sin * total)
    return max(0.0, (1 - inside) / 2)


def friedman(blocks: list[list[float]]) -> tuple[float, list[float], list[float]]:
    """The Friedman test over ``blocks`` (one row of values per task, lower is better), as irace
    runs it: its p-value, each column's rank sum, and each column's two-sided p-value against the
    column of the lowest rank sum by Conover's comparison."""
    n, k = len(blocks), len(blocks[0])
    ranked = [ranks(b) for b in blocks]
    sums = [sum(r[c] for r in ranked) for c in range(k)]
    if n < 2 or k < 2:
        return 1.0, sums, [1.0] * k
    a = sum(x * x for r in ranked for x in r)
    c = n * k * (k + 1) ** 2 / 4
    if a - c <= TIE:
        # Every task a tie.
        return 1.0, sums, [1.0] * k
    statistic = (k - 1) * sum((s - n * (k + 1) / 2) ** 2 for s in sums) / (a - c)
    best = min(sums)
    df = (n - 1) * (k - 1)
    spread = 2 * (n * a - sum(s * s for s in sums)) / df
    if spread <= TIE:
        # The same order on every task.
        compared = [1.0 if s - best <= TIE else 0.0 for s in sums]
    else:
        compared = [min(1.0, 2 * t_sf((s - best) / math.sqrt(spread), df)) for s in sums]
    return chi2_sf(statistic, k - 1), sums, compared


# --- a tuning ----------------------------------------------------------------------------------


@dataclass
class Setting:
    """One point of the space: the parameters' values, None where the heuristic leaves an
    argument out (only the revision's own settings can)."""

    id: int
    values: dict[str, Any]
    iteration: int
    parent: int | None = None
    # The best objective of its run on each task.
    results: dict[int, float] = field(default_factory=dict)
    error: str | None = None
    # (iteration, tasks raced) when a race eliminated it.
    eliminated: tuple[int, int] | None = None

    @property
    def key(self) -> str:
        return json.dumps(self.values, sort_keys=True)

    def describe(self) -> str:
        return ", ".join(
            f"{k}={'(default)' if v is None else _short(v)}" for k, v in self.values.items()
        )


def _short(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return json.dumps(value)


def _get(heuristic: dict[str, Any], path: str) -> Any:
    """The value at ``path``, None when its argument is left out; a missing parent is an error."""
    *parents, leaf = path.split(".")
    node: Any = heuristic
    for segment in parents:
        node = _child(node, segment, path)
    if isinstance(node, list):
        return _child(node, leaf, path)
    if not isinstance(node, dict):
        raise ProjectError(f"{path!r}: {'.'.join(parents)} is not a heuristic or a list")
    return node.get(leaf)


def _child(node: Any, segment: str, path: str) -> Any:
    if isinstance(node, list) and segment.isdigit() and int(segment) < len(node):
        return node[int(segment)]
    if isinstance(node, dict) and segment in node:
        return node[segment]
    raise ProjectError(f"the heuristic has nothing at {segment!r} of {path!r}")


def with_values(heuristic: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(heuristic)
    for path, value in values.items():
        if value is None:
            continue
        *parents, leaf = path.split(".")
        node: Any = result
        for segment in parents:
            node = node[int(segment)] if isinstance(node, list) else node[segment]
        if isinstance(node, list):
            node[int(leaf)] = value
        else:
            node[leaf] = value
    return result


@dataclass
class Tuning:
    id: int
    rev: int
    spec: bench.BenchSpec
    side: bench.Side
    space: list[Parameter]
    budget: int
    seed: int
    instances: list[tuple[bench.BenchInstance, dict[str, Any]]]
    settings: list[Setting] = field(default_factory=list)
    # Per iteration: the ids raced, the tasks raced, and the elites it kept, best first.
    iterations: list[dict[str, Any]] = field(default_factory=list)
    used: int = 0
    higher_is_better: bool = False
    elites: list[Setting] = field(default_factory=list)
    written: bool = False
    validation: int | None = None
    progress: bench.Progress | None = None
    # Runs finished, for progress.
    done: int = 0

    @property
    def default(self) -> Setting:
        return self.settings[0]

    @property
    def best(self) -> Setting:
        return self.elites[0]

    def task(self, t: int) -> tuple[bench.BenchInstance, dict[str, Any], int]:
        """Task ``t``: every train instance in turn, under the next seed after each round."""
        entry, instance = self.instances[t % len(self.instances)]
        return entry, instance, self.spec.seed + t // len(self.instances)

    def score(self, objective: float) -> float:
        return -objective if self.higher_is_better else objective

    def gain(self, s: Setting) -> tuple[float, int] | None:
        """The mean gain of ``s`` over the revision's settings on the tasks both ran, relative to
        the revision's objective (+ is better), and how many those are."""
        shared = [t for t in s.results if t in self.default.results]
        if not shared:
            return None
        gains = [
            (self.score(self.default.results[t]) - self.score(s.results[t]))
            / max(abs(self.default.results[t]), bench.TIE)
            for t in shared
        ]
        return statistics.fmean(gains), len(shared)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rev": self.rev,
            "variant": self.side.variant.label,
            "worker": self.side.worker,
            "spec": self.spec.model_dump(mode="json"),
            "space": [p.model_dump(mode="json", exclude_none=True) for p in self.space],
            "budget": self.budget,
            "used": self.used,
            "seed": self.seed,
            "higher_is_better": self.higher_is_better,
            "tasks": [
                {"instance": self.task(t)[0].name, "seed": self.task(t)[2]}
                for t in range(1 + max(max(s.results, default=-1) for s in self.settings))
            ],
            "settings": [
                {
                    "id": s.id,
                    "values": s.values,
                    "iteration": s.iteration,
                    "parent": s.parent,
                    "results": {str(t): v for t, v in sorted(s.results.items())},
                    "error": s.error,
                    "eliminated": s.eliminated,
                }
                for s in self.settings
            ],
            "iterations": self.iterations,
            "elites": [s.id for s in self.elites],
            "best": self.best.id if self.elites else None,
            "written": self.written,
            "validation": self.validation,
        }


def _keep(project: Project, tuning: Tuning) -> None:
    bench.keep_record(bench.tunings_dir(project), tuning.id, tuning.to_json())


def parse_space(space: Any, heuristic: dict[str, Any]) -> list[Parameter]:
    if not isinstance(space, list) or not space:
        raise ProjectError("give the space as a list of parameters")
    try:
        parameters = [Parameter.model_validate(p) for p in space]
    except ValidationError as exc:
        raise ProjectError(f"not a parameter space: {exc}") from exc
    names = [p.name for p in parameters]
    if len(set(names)) < len(names):
        raise ProjectError(f"a parameter is named twice in {names}")
    for p in parameters:
        _get(heuristic, p.name)
    return parameters


async def tune(
    project: Project,
    rev: int,
    space: Any,
    budget: int,
    variant: str | None = None,
    seed: int | None = None,
    progress: bench.Progress | None = None,
) -> Tuning:
    """Races settings of ``variant`` of revision ``rev`` on the train split with ``budget`` runs,
    and keeps the record in ``bench/tunings``."""
    spec = bench.load_spec(project)
    entries = bench.instances_of(spec, "train")
    if not entries:
        raise ProjectError("the benchmark has no train instances; add some with bench_add")
    where = f"revision {rev}"
    side = await bench.side(project.rev_dir(rev), variant, where)
    parameters = parse_space(space, side.variant.heuristic)
    rounds = 2 + int(math.log2(len(parameters)))
    smallest = rounds * 2 * (FIRST_TEST + 1)
    if budget < smallest:
        raise ProjectError(
            f"a budget of {budget} runs is too small for {len(parameters)} parameters: give at "
            f"least {smallest}, better ten times that"
        )
    tuning = Tuning(
        id=bench.next_id(bench.tunings_dir(project)),
        rev=rev,
        spec=spec,
        side=side,
        space=parameters,
        budget=budget,
        seed=spec.seed if seed is None else seed,
        instances=[(entry, bench.read_instance(project, entry)) for entry in entries],
        progress=progress,
    )
    await _search(tuning, rounds)
    _keep(project, tuning)
    return tuning


async def _search(tuning: Tuning, rounds: int) -> None:
    rng = random.Random(tuning.seed)
    start = {p.name: _get(tuning.side.variant.heuristic, p.name) for p in tuning.space}
    # As many elites survive a round as there are rounds.
    survive = rounds
    seen: set[str] = set()

    def add(values: dict[str, Any], iteration: int, parent: int | None) -> Setting | None:
        s = Setting(len(tuning.settings), values, iteration, parent)
        if s.key in seen:
            return None
        seen.add(s.key)
        tuning.settings.append(s)
        return s

    for iteration in range(1, rounds + 1):
        share = (tuning.budget - tuning.used) // (rounds - iteration + 1)
        size = share // (FIRST_TEST + min(5, iteration))
        new: list[Setting] = []
        if iteration == 1:
            first = add(start, 1, None)
            assert first is not None
            new.append(first)
            columns = {p.name: rng.sample(range(size - 1), size - 1) for p in tuning.space}
            for i in range(size - 1):
                values = {
                    p.name: p.at((columns[p.name][i] + rng.random()) / (size - 1))
                    for p in tuning.space
                }
                s = add(values, 1, None)
                if s:
                    new.append(s)
        else:
            spread = 0.5 * (1 / max(2, size)) ** ((iteration - 1) / len(tuning.space))
            weights = [len(tuning.elites) - i for i in range(len(tuning.elites))]
            for _ in range(max(0, size - len(tuning.elites)) * 10):
                if len(new) >= size - len(tuning.elites):
                    break
                parent = rng.choices(tuning.elites, weights)[0]
                values = {p.name: p.near(parent.values[p.name], spread, rng) for p in tuning.space}
                s = add(values, iteration, parent.id)
                if s:
                    new.append(s)
            if not new:
                break
        raced = tuning.elites + new
        tasks = await _race(tuning, raced, share, iteration, survive)
        alive = [s for s in raced if s.error is None and s.eliminated is None]
        if not alive:
            raise ProjectError(f"every setting failed; the first: {raced[0].error}")
        _, sums, _ = friedman([[tuning.score(s.results[t]) for s in alive] for t in range(tasks)])
        order = sorted(range(len(alive)), key=sums.__getitem__)
        tuning.elites = [alive[i] for i in order[:survive]]
        tuning.iterations.append(
            {
                "iteration": iteration,
                "raced": [s.id for s in raced],
                "tasks": tasks,
                "elites": [s.id for s in tuning.elites],
            }
        )


async def _race(
    tuning: Tuning, settings: list[Setting], budget: int, iteration: int, survive: int
) -> int:
    """Races ``settings`` task by task within ``budget`` new runs; returns the tasks raced."""
    used, tasks = 0, 0
    alive = list(settings)
    while True:
        steps = range(tasks, FIRST_TEST) if tasks < FIRST_TEST else range(tasks, tasks + 1)
        needed = [(s, t) for t in steps for s in alive if t not in s.results]
        if tasks >= FIRST_TEST and used + len(needed) > budget:
            break
        await _run(tuning, needed)
        used += len(needed)
        tuning.used += len(needed)
        tasks = steps[-1] + 1
        for s in alive:
            if s.error is not None and s is tuning.default:
                raise ProjectError(f"revision {tuning.rev}'s own settings fail: {s.error}")
        alive = [s for s in alive if s.error is None]
        if len(alive) > 1:
            blocks = [[tuning.score(s.results[t]) for s in alive] for t in range(tasks)]
            p, _, compared = friedman(blocks)
            if p < ALPHA:
                for s, q in zip(alive, compared, strict=True):
                    if q < ALPHA:
                        s.eliminated = (iteration, tasks)
                alive = [s for s in alive if s.eliminated is None]
        if len(alive) <= survive:
            break
    return tasks


async def _run(tuning: Tuning, needed: list[tuple[Setting, int]]) -> None:
    by_task: dict[int, list[Setting]] = {}
    for s, t in needed:
        by_task.setdefault(t, []).append(s)
    parallel = bench.parallelism()
    jobs: list[tuple[int, list[Setting]]] = []
    for t, settings in by_task.items():
        groups = max(min(len(settings), parallel), math.ceil(len(settings) / MAX_VARIANTS))
        jobs += [(t, settings[g::groups]) for g in range(groups)]
    gate = asyncio.Semaphore(parallel)

    async def ignore(_: RunSummary) -> None:
        pass

    async def solve(t: int, group: list[Setting]) -> None:
        entry, instance, seed = tuning.task(t)
        side = tuning.side
        variants = [
            Variant(label=f"#{s.id}", heuristic=with_values(side.variant.heuristic, s.values))
            for s in group
        ]
        request = bench.request_for(side, instance, tuning.spec, variants, runs=1, seed=seed)
        async with gate:
            summary = await run_solve(
                request, tuning.rev, side.root, ignore, solve_timeout(request), side.binary
            )
        if summary.error:
            error = summary.error
            if error.stage not in ("heuristic", "run"):
                raise ProjectError(
                    f"revision {tuning.rev} fails on {entry.name!r} at {error.stage}: "
                    f"{error.message}"
                )
            if len(group) > 1:
                # Which setting failed: each on its own.
                await asyncio.gather(*(solve(t, [s]) for s in group))
            else:
                group[0].error = f"{error.stage}: {error.message}"
            return
        tuning.higher_is_better = bool(summary.higher_is_better)
        for run in summary.runs:
            group[run.variant].results[t] = run.best_objective
        tuning.done += len(group)
        if tuning.progress:
            await tuning.progress(
                BenchProgress(
                    task="tuning", done=min(tuning.done, tuning.budget), total=tuning.budget
                )
            )

    await asyncio.gather(*(solve(t, group) for t, group in jobs))


def write_best(project: Project, tuning: Tuning) -> None:
    """Makes the project files revision ``tuning.rev``'s, with the best settings in solve.json;
    the variant keeps its own stop."""
    project.restore(tuning.rev)
    solve = copy.deepcopy(tuning.side.solve)
    variant = tuning.side.variant
    heuristic = with_values(variant.heuristic, tuning.best.values)
    if "heuristics" in solve:
        for entry in solve["heuristics"]:
            if entry.get("label") == variant.label:
                entry["heuristic"] = heuristic
    else:
        solve["heuristic"] = heuristic
    project.write_file("solve.json", json.dumps(solve, indent=2))
    tuning.written = True


async def tune_and_check(
    project: Project,
    rev: int,
    space: Any,
    budget: int,
    variant: str | None = None,
    seed: int | None = None,
    progress: bench.Progress | None = None,
) -> tuple[Tuning, bench.Evaluation | None]:
    """``tune``, then, when the best settings are new, writes them into solve.json and judges
    them against revision ``rev`` on the validation split, if the benchmark has one."""
    tuning = await tune(project, rev, space, budget, variant, seed, progress)
    if tuning.best is tuning.default:
        return tuning, None
    write_best(project, tuning)
    evaluation = None
    if bench.instances_of(tuning.spec, "validation"):
        label = tuning.side.variant.label
        evaluation = await bench.evaluate(
            project,
            rev,
            "validation",
            variant=label,
            baseline_variant=label,
            note=f"tuning {tuning.id}: {tuning.best.describe()}",
            progress=progress,
        )
        tuning.validation = evaluation.id
    _keep(project, tuning)
    return tuning, evaluation


# --- what the agent reads ----------------------------------------------------------------------


def report(tuning: Tuning, evaluation: bench.Evaluation | None) -> str:
    t = tuning
    budget = bench.describe_budget(t.spec)
    lines = [
        f"tuning {t.id}: variant {t.side.variant.label} of revision {t.rev} ({t.side.worker} "
        f"worker) on {len(t.instances)} train instances: {t.used} of {t.budget} runs of {budget}, "
        f"{len(t.iterations)} iterations of racing, {len(t.settings)} settings",
        "elites, best first: gain over the revision's settings on the runs both made (+ is "
        "better), mean rank in the last race",
    ]
    last = t.iterations[-1]
    alive = [
        s for s in t.settings if s.id in last["raced"] and s.error is None and not s.eliminated
    ]
    _, sums, _ = friedman(
        [[t.score(s.results[task]) for s in alive] for task in range(last["tasks"])]
    )
    rank = {s.id: total / last["tasks"] for s, total in zip(alive, sums, strict=True)}
    for s in t.elites:
        lines.append(f"  #{s.id}: {s.describe()}; {_gain(t, s)}, rank {rank[s.id]:.2f}")
    default = t.default
    if default not in t.elites:
        fate = (
            f"eliminated in iteration {default.eliminated[0]} after {default.eliminated[1]} tasks"
            if default.eliminated
            else "not among the elites"
        )
        lines.append(f"  the revision's settings (#0: {default.describe()}) were {fate}")
    failed = [s for s in t.settings if s.error]
    if failed:
        shown = "; ".join(f"#{s.id} ({s.describe()}): {s.error}" for s in failed[:3])
        more = f" and {len(failed) - 3} more" if len(failed) > 3 else ""
        lines.append(f"failed: {shown}{more}")
    if t.best is default:
        lines.append("the revision's own settings stay the best; solve.json is unchanged")
        return "\n".join(lines)
    lines.append(
        f"the project files are revision {t.rev}'s with #{t.best.id} in solve.json "
        "(its stop unchanged)"
    )
    if evaluation is None:
        lines.append(
            "the benchmark has no validation instances to check it on; add some and evaluate "
            f"against revision {t.rev} on validation"
        )
    else:
        lines += ["", bench.report(evaluation)]
    return "\n".join(lines)


def _gain(t: Tuning, s: Setting) -> str:
    if s is t.default:
        return "the revision's settings"
    gain = t.gain(s)
    return f"{gain[0]:+.3%} over {gain[1]} runs" if gain else "no runs shared"


def describe(project: Project) -> list[str]:
    """A line per tuning, for bench_list."""
    lines = []
    for r in bench.tunings(project)[-10:]:
        best = next((s for s in r["settings"] if s["id"] == r["best"]), None)
        values = ", ".join(f"{k}={_short(v)}" for k, v in (best or {}).get("values", {}).items())
        outcome = (
            "kept the revision's settings" if r["best"] == 0 else f"best #{r['best']} {values}"
        )
        checked = f", validation evaluation {r['validation']}" if r.get("validation") else ""
        lines.append(
            f"  {r['id']}: variant {r['variant']} of revision {r['rev']}, {r['used']} runs: "
            f"{outcome}{checked}"
        )
    return lines
