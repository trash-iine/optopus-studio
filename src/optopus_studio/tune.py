"""Tuning a heuristic's settings on the benchmark by iterated racing (docs/adr/0014).

The agent names the parameters of one variant of a revision's solve.json, with their ranges, and
a budget of runs; or several variants, each with its own parameters, to choose among them as well
(the kind of heuristic is then one more categorical parameter, and the others hang on it, as in
irace's conditional parameters). ``tune`` then searches without the agent, as irace does,
simplified:

- **sampling**: the first iteration races each variant's own settings against a Latin hypercube
  sample of each variant's parameters; each later one races the elites of the last against
  settings drawn around them, ever closer, now and then of another variant.
- **racing**: every setting alive runs on the same task, a train instance and a seed, one task
  after another, each run on the benchmark's budget. After the first ``FIRST_TEST`` tasks, a
  Friedman test over the ranks on each task, and Conover's comparison with the best, eliminate
  the settings that are worse, so the budget goes to the ones still in doubt. A run is never made
  twice: an elite keeps its results on the tasks it ran.

The best elite is written into solve.json, and judged against the revision on the validation
split with ``bench.evaluate``, so the settings are checked on instances they were not chosen on.
``signs`` reads the race for what the settings cannot fix (a range too narrow, settings that do
not matter, instances that want different ones, a search that stalls), for the agent's next
change of the structure.
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
from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import MAX_VARIANTS, BenchProgress, RunSummary, Variant
from optopus_studio.runner import run_solve
from optopus_studio.solving import solve_timeout

# Tasks every setting of a race runs before the first test, and the tests' level.
FIRST_TEST = 5
# Values this close rank as a tie.
TIE = 1e-12
# What signs() reads into a race. These are this studio's proposals, not values from the
# literature (docs/adr/0014): the outer share of a range that counts as its edge, the share of
# settings eliminated below which a race with no difference left is flat, the share of a run's
# iterations within which a best found counts as found early, and the rates of accepted moves
# that count as almost none and almost all.
EDGE = 0.1
FLAT = 0.25
EARLY = 0.25
ACCEPTED = (0.01, 0.99)

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

    def unit(self, value: Any) -> float | None:
        """Where ``value`` lies in the space, from 0 to 1; None for a categorical or no number."""
        position = None if self.choices is not None else self._position(value)
        if position is None:
            return None
        lo, hi = self._bounds()
        return (position - lo) / (hi - lo)

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


# What a run did besides its best: moves accepted and rejected (None from a heuristic that does
# not count them), the iteration of its best, its iterations and its seconds.
Stats = tuple[int | None, int | None, int, int, float]


@dataclass
class Setting:
    """One point of the space: a variant and its parameters' values, None where the heuristic
    leaves an argument out (only a variant's own settings can)."""

    id: int
    variant: str
    values: dict[str, Any]
    iteration: int
    parent: int | None = None
    # The best objective of its run on each task, and what the run did.
    results: dict[int, float] = field(default_factory=dict)
    stats: dict[int, Stats] = field(default_factory=dict)
    error: str | None = None
    # (iteration, tasks raced) when a race eliminated it.
    eliminated: tuple[int, int] | None = None

    @property
    def key(self) -> str:
        return json.dumps([self.variant, self.values], sort_keys=True)

    def describe(self) -> str:
        return (
            ", ".join(
                f"{k}={'(default)' if v is None else _short(v)}" for k, v in self.values.items()
            )
            or "its own settings"
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
    # The revision, with the variant whose own settings the others are measured against.
    side: bench.Side
    # The parameters of each variant raced, that variant first.
    space: dict[str, list[Parameter]]
    variants: dict[str, Variant]
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
    signs: list[str] = field(default_factory=list)
    progress: bench.Progress | None = None
    # Runs finished, for progress.
    done: int = 0

    @property
    def default(self) -> Setting:
        return self.settings[0]

    @property
    def best(self) -> Setting:
        return self.elites[0]

    @property
    def choosing(self) -> bool:
        """Whether the race chooses among variants too."""
        return len(self.space) > 1

    @property
    def dimensions(self) -> int:
        """The parameters, the kind of heuristic one of them when the race chooses it."""
        return sum(len(p) for p in self.space.values()) + (len(self.space) if self.choosing else 0)

    def heuristic(self, s: Setting) -> dict[str, Any]:
        return with_values(self.variants[s.variant].heuristic, s.values)

    def describe(self, s: Setting) -> str:
        return f"{s.variant}: {s.describe()}" if self.choosing else s.describe()

    def near(self, parent: Setting, spread: float, rng: random.Random) -> tuple[str, dict]:
        """A setting drawn around ``parent``: of another variant now and then, its parameters
        then drawn anew, since they do not carry over."""
        label = parent.variant
        if self.choosing and rng.random() < spread:
            label = rng.choice(list(self.space))
        if label != parent.variant:
            return label, {p.name: p.at(rng.random()) for p in self.space[label]}
        return label, {
            p.name: p.near(parent.values[p.name], spread, rng) for p in self.space[label]
        }

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
            "variants": list(self.space),
            "worker": self.side.worker,
            "spec": self.spec.model_dump(mode="json"),
            "space": {
                label: [p.model_dump(mode="json", exclude_none=True) for p in parameters]
                for label, parameters in self.space.items()
            },
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
                    "variant": s.variant,
                    "values": s.values,
                    "iteration": s.iteration,
                    "parent": s.parent,
                    "results": {str(t): v for t, v in sorted(s.results.items())},
                    "stats": {str(t): list(v) for t, v in sorted(s.stats.items())},
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
            "signs": self.signs,
        }


def _keep(project: Project, tuning: Tuning) -> None:
    # The id is taken when the record is first written, so tunings that overlap get their own.
    if not tuning.id:
        tuning.id = bench.next_id(bench.tunings_dir(project))
    bench.keep_record(bench.tunings_dir(project), tuning.id, tuning.to_json())


def parse_space(space: Any, heuristic: dict[str, Any], empty: bool = False) -> list[Parameter]:
    if not isinstance(space, list) or not (space or empty):
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


def parse_spaces(space: Any, side: bench.Side, where: str) -> dict[str, list[Parameter]]:
    """The space of one variant, a list of parameters, as the parameters of each variant to
    choose among, a dict by label whose first is the side's."""
    if not isinstance(space, dict):
        return {side.variant.label: parse_space(space, side.variant.heuristic)}
    variants = {v.label: v for v in variants_of(side.solve)}
    spaces = {}
    for label, parameters in space.items():
        if label not in variants:
            raise ProjectError(f"{where} has no variant {label!r}; it has {list(variants)}")
        try:
            spaces[label] = parse_space(parameters, variants[label].heuristic, empty=True)
        except ProjectError as exc:
            raise ProjectError(f"variant {label!r}: {exc}") from exc
    if len(spaces) == 1 and not next(iter(spaces.values())):
        raise ProjectError("nothing to tune: give parameters, or variants to choose among")
    return spaces


async def tune(
    project: Project,
    rev: int,
    space: Any,
    budget: int,
    variant: str | None = None,
    seed: int | None = None,
    progress: bench.Progress | None = None,
) -> Tuning:
    """Races settings of revision ``rev`` on the train split with ``budget`` runs, and keeps the
    record in ``bench/tunings``. ``space`` is a list of the parameters of ``variant``, or a dict
    of each variant's parameters to choose among them, the first the one to measure against."""
    spec = bench.load_spec(project)
    entries = bench.instances_of(spec, "train")
    if not entries:
        raise ProjectError("the benchmark has no train instances; add some with bench_add")
    where = f"revision {rev}"
    if isinstance(space, dict):
        if variant is not None:
            raise ProjectError("a space by variant names the variants; leave variant out")
        if not space:
            raise ProjectError("give the parameters of each variant to choose among")
        variant = next(iter(space))
    side = await bench.side(project.rev_dir(rev), variant, where)
    spaces = parse_spaces(space, side, where)
    tuning = Tuning(
        id=0,
        rev=rev,
        spec=spec,
        side=side,
        space=spaces,
        variants={v.label: v for v in variants_of(side.solve)},
        budget=budget,
        seed=spec.seed if seed is None else seed,
        instances=[(entry, bench.read_instance(project, entry)) for entry in entries],
        progress=progress,
    )
    rounds = 2 + int(math.log2(tuning.dimensions))
    smallest = rounds * 2 * (FIRST_TEST + 1)
    if budget < smallest:
        raise ProjectError(
            f"a budget of {budget} runs is too small for {tuning.dimensions} parameters: give "
            f"at least {smallest}, better ten times that"
        )
    await _search(tuning, rounds)
    tuning.signs = signs(tuning)
    _keep(project, tuning)
    return tuning


async def _search(tuning: Tuning, rounds: int) -> None:
    rng = random.Random(tuning.seed)
    # As many elites survive a round as there are rounds.
    survive = rounds
    seen: set[str] = set()

    def add(
        variant: str, values: dict[str, Any], iteration: int, parent: int | None
    ) -> Setting | None:
        s = Setting(len(tuning.settings), variant, values, iteration, parent)
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
            for label, parameters in tuning.space.items():
                own = {p.name: _get(tuning.variants[label].heuristic, p.name) for p in parameters}
                first = add(label, own, 1, None)
                assert first is not None
                new.append(first)
            # The rest shared among the variants with parameters, each sampled in a Latin
            # hypercube of its own.
            sampled = [label for label, parameters in tuning.space.items() if parameters]
            rest = max(0, size - len(new))
            for k, label in enumerate(sampled):
                count = rest // len(sampled) + (1 if k < rest % len(sampled) else 0)
                parameters = tuning.space[label]
                columns = {p.name: rng.sample(range(count), count) for p in parameters}
                for i in range(count):
                    values = {
                        p.name: p.at((columns[p.name][i] + rng.random()) / count)
                        for p in parameters
                    }
                    s = add(label, values, 1, None)
                    if s:
                        new.append(s)
        else:
            spread = 0.5 * (1 / max(2, size)) ** ((iteration - 1) / tuning.dimensions)
            weights = [len(tuning.elites) - i for i in range(len(tuning.elites))]
            for _ in range(max(0, size - len(tuning.elites)) * 10):
                if len(new) >= size - len(tuning.elites):
                    break
                parent = rng.choices(tuning.elites, weights)[0]
                s = add(*tuning.near(parent, spread, rng), iteration, parent.id)
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
        variants = [Variant(label=f"#{s.id}", heuristic=tuning.heuristic(s)) for s in group]
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
                await bench.all_of([solve(t, [s]) for s in group])
            else:
                group[0].error = f"{error.stage}: {error.message}"
            return
        tuning.higher_is_better = bool(summary.higher_is_better)
        for run in summary.runs:
            s = group[run.variant]
            s.results[t] = run.best_objective
            s.stats[t] = (
                run.n_accepted,
                run.n_rejected,
                run.best_iteration,
                run.iterations,
                run.total_time_secs,
            )
        tuning.done += len(group)
        if tuning.progress:
            await tuning.progress(
                BenchProgress(
                    task="tuning", done=min(tuning.done, tuning.budget), total=tuning.budget
                )
            )

    await bench.all_of([solve(t, group) for t, group in jobs])


def write_best(project: Project, tuning: Tuning) -> None:
    """Makes the project files revision ``tuning.rev``'s, with the best settings in solve.json;
    the variant keeps its own stop. A race among variants settled which to solve with, so it
    becomes solve.json's only heuristic."""
    project.restore(tuning.rev)
    solve = copy.deepcopy(tuning.side.solve)
    best = tuning.best
    heuristic = tuning.heuristic(best)
    if tuning.choosing:
        solve.pop("heuristics", None)
        solve["heuristic"] = heuristic
    elif "heuristics" in solve:
        for entry in solve["heuristics"]:
            if entry.get("label") == best.variant:
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
    try:
        if bench.instances_of(tuning.spec, "validation"):
            label = tuning.side.variant.label
            evaluation = await bench.evaluate(
                project,
                rev,
                "validation",
                variant=None if tuning.choosing else label,
                baseline_variant=label,
                note=f"tuning {tuning.id}: {tuning.describe(tuning.best)}",
                progress=progress,
            )
            tuning.validation = evaluation.id
    except ProjectError as exc:
        raise ProjectError(
            f"{exc}; the project files are now revision {rev}'s with the tuned settings in "
            "solve.json"
        ) from exc
    finally:
        _keep(project, tuning)
    return tuning, evaluation


# --- what the agent reads ----------------------------------------------------------------------


def _last_race(t: Tuning) -> tuple[list[Setting], float, list[float]]:
    """The settings alive at the end of the last race, its Friedman p-value and their mean
    ranks."""
    last = t.iterations[-1]
    alive = [
        s for s in t.settings if s.id in last["raced"] and s.error is None and not s.eliminated
    ]
    p, sums, _ = friedman(
        [[t.score(s.results[task]) for s in alive] for task in range(last["tasks"])]
    )
    return alive, p, [total / last["tasks"] for total in sums]


def _rate(stats: list[Stats]) -> float | None:
    return bench.acceptance((a, r) for a, r, *_ in stats)


def _early(stats: list[Stats]) -> float | None:
    """The mean share of a run's iterations gone when it found its best."""
    shares = [best / iterations for _, _, best, iterations, _ in stats if iterations > 0]
    return statistics.fmean(shares) if shares else None


def signs(t: Tuning) -> list[str]:
    """What the race shows that settings cannot fix, each with the change of structure it
    suggests: hints for the agent's next hypothesis, not verdicts."""
    found = []
    best = t.best
    kind = f" of {best.variant}" if t.choosing else ""
    elites = [s for s in t.elites if s.variant == best.variant]
    for p in t.space[best.variant]:
        units = [u for s in elites if (u := p.unit(s.values[p.name])) is not None]
        if len(units) < len(elites):
            continue
        if all(u < EDGE for u in units):
            end = "low"
        elif all(u > 1 - EDGE for u in units):
            end = "high"
        else:
            continue
        found.append(
            f"{p.name}: every elite{kind} is at the {end} end of [{p.low:g}, {p.high:g}]; "
            "widen the range, or the search lacks another mechanism"
        )

    _, p_last, _ = _last_race(t)
    ran = [s for s in t.settings if s.error is None]
    dropped = sum(1 for s in ran if s.eliminated)
    if len(ran) > 1 and p_last >= ALPHA and dropped < FLAT * len(ran):
        found.append(
            f"the settings barely matter: {dropped} of {len(ran)} dropped and the last race "
            f"could not tell the rest apart (p = {p_last:.2g}); change the structure "
            "(neighborhood, delta, Rust) rather than the settings"
        )

    n = len(t.instances)
    if n > 1 and len(t.elites) > 1:
        winners: list[tuple[str, int]] = []
        apart = False
        for i, (entry, _) in enumerate(t.instances):
            tasks = [
                task
                for task in range(i, 1 + max(best.results, default=-1), n)
                if all(task in s.results for s in t.elites)
            ]
            if len(tasks) < 2:
                continue
            means = {
                s.id: statistics.fmean(t.score(s.results[task]) for task in tasks) for s in t.elites
            }
            winner = min(means, key=means.__getitem__)
            winners.append((entry.name, winner))
            margin = (means[best.id] - means[winner]) / max(abs(means[best.id]), bench.TIE)
            apart = apart or margin >= bench.WORSENING_LIMIT
        if apart and len({winner for _, winner in winners}) > 1:
            shown = ", ".join(f"{name} #{winner}" for name, winner in winners)
            found.append(
                f"instances prefer different elites: {shown}; one setting may not fit them all, "
                "so tell the user: a setting per kind of instance, chosen by its features, may"
            )

    stats = list(best.stats.values())
    early = _early(stats)
    if early is not None and early < EARLY:
        found.append(
            f"#{best.id} finds its best {early:.0%} of the way through a run on average; the "
            "search stalls after that: diversify (a perturbation, restarts)"
        )
    rate = _rate(stats)
    if rate is not None and rate < ACCEPTED[0]:
        found.append(
            f"#{best.id} accepts {rate:.1%} of its moves: almost none, the search barely moves; "
            "a larger neighborhood or a perturbation"
        )
    elif rate is not None and rate > ACCEPTED[1]:
        found.append(
            f"#{best.id} accepts {rate:.1%} of its moves: almost all, the search wanders; a "
            "greedier acceptance"
        )
    return found


def report(tuning: Tuning, evaluation: bench.Evaluation | None) -> str:
    t = tuning
    budget = bench.describe_budget(t.spec)
    raced = f"variants {', '.join(t.space)}" if t.choosing else f"variant {t.side.variant.label}"
    lines = [
        f"tuning {t.id}: {raced} of revision {t.rev} ({t.side.worker} worker) on "
        f"{len(t.instances)} train instances: {t.used} of {t.budget} runs of {budget}, "
        f"{len(t.iterations)} iterations of racing, {len(t.settings)} settings",
        "elites, best first: gain over the revision's settings on the runs both made (+ is "
        "better), mean rank in the last race",
    ]
    alive, _, mean_ranks = _last_race(t)
    rank = {s.id: r for s, r in zip(alive, mean_ranks, strict=True)}
    for s in t.elites:
        lines.append(f"  #{s.id}: {t.describe(s)}; {_gain(t, s)}, rank {rank[s.id]:.2f}")
    default = t.default
    if default not in t.elites:
        fate = (
            f"eliminated in iteration {default.eliminated[0]} after {default.eliminated[1]} tasks"
            if default.eliminated
            else "not among the elites"
        )
        lines.append(f"  the revision's settings (#0: {t.describe(default)}) were {fate}")
    failed = [s for s in t.settings if s.error]
    if failed:
        shown = "; ".join(f"#{s.id} ({t.describe(s)}): {s.error}" for s in failed[:3])
        more = f" and {len(failed) - 3} more" if len(failed) > 3 else ""
        lines.append(f"failed: {shown}{more}")
    stats = list(t.best.stats.values())
    if stats:
        rate, early = _rate(stats), _early(stats)
        speed = bench.speed((iterations, secs) for *_, iterations, secs in stats)
        lines.append(
            f"#{t.best.id}'s runs: {speed:,.0f} iterations/s, best found "
            f"{'?' if early is None else f'{early:.0%}'} of the way through, "
            f"{'?' if rate is None else f'{rate:.0%}'} of moves accepted"
        )
    if t.signs:
        lines.append("signs, hints for the next change rather than verdicts:")
        lines += [f"  - {sign}" for sign in t.signs]
    if t.best is default:
        lines.append("the revision's own settings stay the best; solve.json is unchanged")
        return "\n".join(lines)
    where = (
        f"#{t.best.id} ({t.best.variant}) as solve.json's only heuristic"
        if t.choosing
        else f"#{t.best.id} in solve.json"
    )
    lines.append(f"the project files are revision {t.rev}'s with {where} (its stop unchanged)")
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
        best = next((s for s in r["settings"] if s["id"] == r["best"]), None) or {}
        values = ", ".join(f"{k}={_short(v)}" for k, v in best.get("values", {}).items())
        if len(r["variants"]) > 1:
            values = f"{best.get('variant')}: {values or 'its own settings'}"
        outcome = (
            "kept the revision's settings" if r["best"] == 0 else f"best #{r['best']} {values}"
        )
        checked = f", validation evaluation {r['validation']}" if r.get("validation") else ""
        signs = f"; signs: {len(r['signs'])}" if r.get("signs") else ""
        lines.append(
            f"  {r['id']}: {' or '.join(r['variants'])} of revision {r['rev']}, {r['used']} "
            f"runs: {outcome}{checked}{signs}"
        )
    return lines
