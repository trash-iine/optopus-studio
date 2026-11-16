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
import dataclasses
import json
import math
import random
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from optopus_studio import bench, compose
from optopus_studio.bench import ALPHA, ranks
from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import MAX_VARIANTS, BenchProgress, RunFinished, Variant
from optopus_studio.runner import ignore_progress, run_solve
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
    """One argument of the heuristic to tune: a number in [low, high], or one of ``choices``.

    A number is a float or an int. ``name`` is its path in the heuristic, such as
    "initial_temperature", or "search.cooling_rate" in a nested heuristic, or "steps.0.tabu_tenure"
    in a list.

    Attributes:
        name: The argument's path in the heuristic.
        type: float, int or categorical; categorical when ``choices`` is given, float otherwise.
        low: The lowest value of a number.
        high: The highest value of a number.
        log: Whether a number is sampled on a log scale.
        choices: The values of a categorical one.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["float", "int", "categorical"] | None = None
    low: float | None = None
    high: float | None = None
    log: bool = False
    choices: list[Any] | None = None

    @model_validator(mode="after")
    def check(self) -> Parameter:
        """Checks the path and that the bounds or choices fit the type, which it fills in.

        Returns:
            The parameter.

        Raises:
            ValueError: The path is malformed or not tunable, or the bounds or choices do not fit.
        """
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
        """The interval values are drawn from.

        It is log-scaled for a log parameter, and one wider for an int, whose values are the floors.

        Returns:
            The interval's ends.
        """
        assert self.low is not None
        assert self.high is not None
        high = self.high + 1 if self.type == "int" else self.high
        return (math.log(self.low), math.log(high)) if self.log else (self.low, high)

    def _value(self, z: float) -> Any:
        """The value at a point of the interval values are drawn from, kept within [low, high].

        Args:
            z: The point.

        Returns:
            The value.
        """
        assert self.low is not None
        assert self.high is not None
        x = math.exp(z) if self.log else z
        if self.type == "int":
            return int(min(max(math.floor(x), self.low), self.high))
        return min(max(x, self.low), self.high)

    def _position(self, value: Any) -> float | None:
        """Where a value lies in the interval values are drawn from.

        Args:
            value: The value.

        Returns:
            The point, or None when the value is not a number the interval holds.
        """
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        x = value + 0.5 if self.type == "int" else float(value)
        if self.log:
            return math.log(x) if x > 0 else None
        return x

    def unit(self, value: Any) -> float | None:
        """Where ``value`` lies in the space, from 0 to 1; None for a categorical or no number.

        Args:
            value: The value.

        Returns:
            The share of the space below the value, or None.
        """
        position = None if self.choices is not None else self._position(value)
        if position is None:
            return None
        lo, hi = self._bounds()
        return (position - lo) / (hi - lo)

    def at(self, u: float) -> Any:
        """The value at ``u`` in [0, 1) of the space, evenly.

        Args:
            u: The share of the space.

        Returns:
            The value.
        """
        if self.choices is not None:
            return self.choices[min(int(u * len(self.choices)), len(self.choices) - 1)]
        lo, hi = self._bounds()
        return self._value(lo + u * (hi - lo))

    def near(self, value: Any, spread: float, rng: random.Random) -> Any:
        """A value drawn around ``value``, within ``spread`` of the space's width.

        Args:
            value: The value to draw around.
            spread: The spread, as a share of the space's width; for a categorical, the chance of
                drawing a choice anew.
            rng: The random source.

        Returns:
            The value drawn.
        """
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
    """P(X > x) for chi-squared with ``df`` degrees of freedom (Abramowitz & Stegun 26.4.4-5).

    Args:
        x: The statistic.
        df: The degrees of freedom.

    Returns:
        The probability.
    """
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
    """P(T > t) for Student's t with ``df`` degrees of freedom (Abramowitz & Stegun 26.7.3-4).

    Args:
        t: The statistic.
        df: The degrees of freedom.

    Returns:
        The probability.
    """
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
    """The Friedman test over ``blocks``, as irace runs it.

    The blocks are one row of values per task; lower is better.

    Args:
        blocks: The values, a row per task and a column per setting.

    Returns:
        Its p-value, each column's rank sum, and each column's two-sided p-value against the column
        of the lowest rank sum by Conover's comparison.
    """
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
    """One point of the space: a variant and its parameters' values.

    A value is None where the heuristic leaves an argument out (only a variant's own settings can).

    Attributes:
        id: The setting's number in the tuning; 0 the revision's own.
        variant: The variant's label.
        values: Each parameter's value, by path.
        iteration: The iteration it was drawn in.
        parent: The elite it was drawn around, if any.
        results: The best objective of its run on each task.
        runs: Its run on each task, without the solution and trajectory.
        error: Why its runs failed, if they did.
        eliminated: The iteration and the tasks raced when a race eliminated it.
    """

    id: int
    variant: str
    values: dict[str, Any]
    iteration: int
    parent: int | None = None
    # The best objective of its run on each task, and the run, without its solution and
    # trajectory.
    results: dict[int, float] = field(default_factory=dict)
    runs: dict[int, RunFinished] = field(default_factory=dict)
    error: str | None = None
    # (iteration, tasks raced) when a race eliminated it.
    eliminated: tuple[int, int] | None = None

    @property
    def key(self) -> str:
        """What makes two settings the same, for drawing each only once."""
        return json.dumps([self.variant, self.values], sort_keys=True)

    def describe(self) -> str:
        """The setting's values in words.

        Returns:
            The values, or "its own settings" when it has none.
        """
        return (
            ", ".join(
                f"{k}={'(default)' if v is None else _short(v)}" for k, v in self.values.items()
            )
            or "its own settings"
        )


def _short(value: Any) -> str:
    """A value in a few characters.

    Args:
        value: The value.

    Returns:
        A float to four significant digits, anything else as JSON.
    """
    if isinstance(value, float):
        return f"{value:.4g}"
    return json.dumps(value)


def _get(heuristic: dict[str, Any], path: str) -> Any:
    """The value at ``path``, None when its argument is left out; a missing parent is an error.

    Args:
        heuristic: The heuristic's dict.
        path: The argument's path.

    Returns:
        The value, or None.

    Raises:
        ProjectError: Something on the way to the argument is missing, or not a heuristic or list.
    """
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
    """One step along a path: an item of a list, or an argument of a heuristic.

    Args:
        node: The list or heuristic.
        segment: The index or argument's name.
        path: The whole path, for the error.

    Returns:
        The item or argument.

    Raises:
        ProjectError: There is nothing at ``segment``.
    """
    if isinstance(node, list) and segment.isdigit() and int(segment) < len(node):
        return node[int(segment)]
    if isinstance(node, dict) and segment in node:
        return node[segment]
    raise ProjectError(f"the heuristic has nothing at {segment!r} of {path!r}")


def with_values(heuristic: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """A copy of a heuristic with values set at their paths; None leaves an argument as it is.

    Args:
        heuristic: The heuristic's dict.
        values: Each value, by path.

    Returns:
        The copy.
    """
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
    """A race of settings on the benchmark, and what it found.

    Attributes:
        id: The tuning's number among the project's; 0 until it is kept.
        rev: The revision tuned.
        spec: The benchmark's runs, seed and budget.
        side: The revision, with the variant whose own settings the others are measured against.
        space: The parameters of each variant raced, that variant first.
        variants: The revision's variants, by label.
        budget: The runs the race may make.
        seed: The race's seed.
        instances: The train instances, each with its content.
        settings: Every setting drawn.
        iterations: Per iteration: the ids raced, the tasks raced, and the elites it kept.
        used: The runs made.
        higher_is_better: The direction the objectives are ranked in.
        elites: The elites of the last iteration, best first.
        written: Whether the best settings were written into solve.json.
        validation: The evaluation that checked them on validation, if any.
        signs: What the race shows that settings cannot fix.
        progress: Called as runs finish, if given.
        done: The runs finished, for the progress.
        note: What a grammar built of the leaves, in a line; empty without one.
    """

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
    # What a grammar built, in a line, for the report.
    note: str = ""

    @property
    def default(self) -> Setting:
        """The revision's own settings, which the others are measured against."""
        return self.settings[0]

    @property
    def best(self) -> Setting:
        """The best elite."""
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
        """The heuristic a setting runs.

        Args:
            s: The setting.

        Returns:
            The variant's heuristic with the setting's values.
        """
        return with_values(self.variants[s.variant].heuristic, s.values)

    def describe(self, s: Setting) -> str:
        """A setting in words, with its variant when the race chooses among several.

        Args:
            s: The setting.

        Returns:
            The words.
        """
        return f"{s.variant}: {s.describe()}" if self.choosing else s.describe()

    def near(self, parent: Setting, spread: float, rng: random.Random) -> tuple[str, dict]:
        """A setting drawn around ``parent``.

        Now and then it is of another variant, its parameters then drawn anew, since they do not
        carry over.

        Args:
            parent: The elite to draw around.
            spread: How far to draw, as a share of each space's width.
            rng: The random source.

        Returns:
            The variant's label and the values drawn.
        """
        label = parent.variant
        if self.choosing and rng.random() < spread:
            label = rng.choice(list(self.space))
        if label != parent.variant:
            return label, {p.name: p.at(rng.random()) for p in self.space[label]}
        return label, {
            p.name: p.near(parent.values[p.name], spread, rng) for p in self.space[label]
        }

    def task(self, t: int) -> tuple[bench.BenchInstance, dict[str, Any], int]:
        """Task ``t``: every train instance in turn, under the next seed after each round.

        Args:
            t: The task's number.

        Returns:
            The instance's entry, its content, and the seed.
        """
        entry, instance = self.instances[t % len(self.instances)]
        return entry, instance, self.spec.seed + t // len(self.instances)

    def score(self, objective: float) -> float:
        """An objective on a scale where lower is better.

        Args:
            objective: The objective.

        Returns:
            The objective, negated when higher is better.
        """
        return -objective if self.higher_is_better else objective

    def gain(self, s: Setting) -> tuple[float, int] | None:
        """The mean gain of ``s`` over the revision's settings on the tasks both ran.

        The gain is relative to the revision's objective; positive is better.

        Args:
            s: The setting.

        Returns:
            The mean gain and the number of tasks both ran, or None when they share none.
        """
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
        """The tuning's record, as kept in ``bench/tunings``.

        Returns:
            The record.
        """
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
                    "stats": {
                        str(t): [
                            r.n_accepted,
                            r.n_rejected,
                            r.best_iteration,
                            r.iterations,
                            r.total_time_secs,
                        ]
                        for t, r in sorted(s.runs.items())
                    },
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
    """Keeps the tuning's record, numbering it the first time.

    Args:
        project: The project.
        tuning: The tuning.
    """
    # The id is taken when the record is first written, so tunings that overlap get their own.
    if not tuning.id:
        tuning.id = bench.next_id(bench.tunings_dir(project))
    bench.keep_record(bench.tunings_dir(project), tuning.id, tuning.to_json())


def parse_space(space: Any, heuristic: dict[str, Any], empty: bool = False) -> list[Parameter]:
    """Reads one variant's parameters and checks them against its heuristic.

    Args:
        space: The parameters, as the agent gave them.
        heuristic: The variant's heuristic.
        empty: Whether no parameters is allowed, as for a variant only chosen among.

    Returns:
        The parameters.

    Raises:
        ProjectError: The space is not a list of parameters, names one twice, or names an argument
            the heuristic does not have.
    """
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
    """The parameters of each variant to race.

    A list is the parameters of the side's variant alone; a dict by label gives each variant's, the
    side's first, to choose among them.

    Args:
        space: The space, as the agent gave it.
        side: The revision, with the variant the others are measured against.
        where: Whose solve.json it is, in words.

    Returns:
        Each variant's parameters, by label.

    Raises:
        ProjectError: A variant does not exist, its parameters do not fit, or there is nothing to
            tune.
    """
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
    grammar: Any = None,
) -> Tuning:
    """Races settings of revision ``rev`` on the train split and keeps the record.

    The record is kept in ``bench/tunings``. ``space`` is a list of the parameters of ``variant``,
    or a dict of each variant's parameters to choose among them, the first the one to measure
    against.

    Args:
        project: The project.
        rev: The revision whose settings are tuned.
        space: A list of the parameters of ``variant``, or a dict of each variant's parameters.
        budget: The runs the race may make.
        variant: The variant to tune; None when solve.json has only one, or ``space`` is a dict.
        seed: The race's seed; the benchmark's when None.
        progress: Called as runs finish, if given.
        grammar: Instead of ``space``, the leaves to compose and race (compose.py): the race
            then chooses among them and the compositions built of them.

    Returns:
        The tuning.

    Raises:
        ProjectError: The benchmark has no train instances, the space is invalid, the budget is too
            small, or the revision's own settings fail.
    """
    spec = bench.load_spec(project)
    entries = bench.instances_of(spec, "train")
    if not entries:
        raise ProjectError("the benchmark has no train instances; add some with bench_add")
    where = f"revision {rev}"
    composed: list[Variant] = []
    note = ""
    if grammar is not None:
        if variant is not None:
            raise ProjectError("a grammar names its leaves; leave variant out")
        try:
            solve = json.loads((project.rev_dir(rev) / "solve.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"{where} has no solve.json to compose from: {exc}") from exc
        space, composed, note = compose.expand(project, rev, variants_of(solve), grammar, spec)
    if isinstance(space, dict):
        if variant is not None:
            raise ProjectError("a space by variant names the variants; leave variant out")
        if not space:
            raise ProjectError("give the parameters of each variant to choose among")
        variant = next(iter(space))
    side = await bench.side(project.rev_dir(rev), variant, where)
    if composed:
        # The compositions join the revision's variants, as if solve.json had listed them.
        listed = [v.model_dump() for v in [*variants_of(side.solve), *composed]]
        rest = {k: v for k, v in side.solve.items() if k not in ("heuristic", "heuristics")}
        side = dataclasses.replace(side, solve={**rest, "heuristics": listed})
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
    tuning.note = note
    rounds = 2 + int(math.log2(tuning.dimensions))
    # Every variant's own settings race from the first iteration, and a test needs FIRST_TEST
    # tasks of each before it can drop any.
    smallest = rounds * max(2, len(spaces) if tuning.choosing else 0) * (FIRST_TEST + 1)
    if budget < smallest:
        raise ProjectError(
            f"a budget of {budget} runs is too small for {tuning.dimensions} parameters"
            + (f" over {len(spaces)} variants" if tuning.choosing else "")
            + f": give at least {smallest}, better several times that"
            + (", or a lower 'limit' in the grammar" if composed else "")
        )
    await _search(tuning, rounds)
    tuning.signs = signs(tuning)
    _keep(project, tuning)
    return tuning


async def _search(tuning: Tuning, rounds: int) -> None:
    """Iterates the race: draws settings, races them, and keeps the elites.

    Args:
        tuning: The tuning.
        rounds: The iterations, and the elites each keeps.

    Raises:
        ProjectError: Every setting of an iteration failed, or the revision's own did.
    """
    rng = random.Random(tuning.seed)
    # As many elites survive a round as there are rounds.
    survive = rounds
    seen: set[str] = set()

    def add(
        variant: str, values: dict[str, Any], iteration: int, parent: int | None
    ) -> Setting | None:
        """Adds a setting to the tuning, unless the same one was drawn before.

        Args:
            variant: The variant's label.
            values: Each parameter's value.
            iteration: The iteration it is drawn in.
            parent: The elite it was drawn around, if any.

        Returns:
            The setting, or None when it was drawn before.
        """
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
    """Races ``settings`` task by task within ``budget`` new runs; returns the tasks raced.

    After ``FIRST_TEST`` tasks, each task ends with a Friedman test that eliminates the settings
    clearly worse than the best, until ``survive`` are left or the budget is spent.

    Args:
        tuning: The tuning.
        settings: The settings to race.
        budget: The new runs the race may make.
        iteration: The iteration, recorded with an elimination.
        survive: How many settings the race may stop at.

    Returns:
        The number of tasks raced.

    Raises:
        ProjectError: The revision's own settings fail, or the model fails on a task.
    """
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
    """Makes the runs needed, grouping the settings that share a task into solves.

    Args:
        tuning: The tuning.
        needed: Each setting and the task it runs.

    Raises:
        ProjectError: The model fails on a task.
    """
    by_task: dict[int, list[Setting]] = {}
    for s, t in needed:
        by_task.setdefault(t, []).append(s)
    parallel = bench.parallelism()
    jobs: list[tuple[int, list[Setting]]] = []
    for t, settings in by_task.items():
        groups = max(min(len(settings), parallel), math.ceil(len(settings) / MAX_VARIANTS))
        jobs += [(t, settings[g::groups]) for g in range(groups)]
    gate = asyncio.Semaphore(parallel)

    async def solve(t: int, group: list[Setting]) -> None:
        """Runs a group of settings on a task, one solve with a variant each.

        When the solve fails at the heuristic or the run, each setting runs again on its own, to
        find which failed.

        Args:
            t: The task.
            group: The settings.

        Raises:
            ProjectError: The model fails on the task.
        """
        entry, instance, seed = tuning.task(t)
        side = tuning.side
        variants = [Variant(label=f"#{s.id}", heuristic=tuning.heuristic(s)) for s in group]
        request = bench.request_for(side, instance, tuning.spec, variants, runs=1, seed=seed)
        async with gate:
            summary = await run_solve(
                request, tuning.rev, side.root, ignore_progress, solve_timeout(request), side.binary
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
            s.runs[t] = run.model_copy(update={"solution": None, "trajectory": []})
        tuning.done += len(group)
        if tuning.progress:
            await tuning.progress(
                BenchProgress(
                    task="tuning", done=min(tuning.done, tuning.budget), total=tuning.budget
                )
            )

    await bench.all_of([solve(t, group) for t, group in jobs])


def write_best(project: Project, tuning: Tuning) -> None:
    """Makes the project files revision ``tuning.rev``'s, with the best settings in solve.json.

    The variant keeps its own stop. A race among variants settled which to solve with, so it becomes
    solve.json's only heuristic.

    Args:
        project: The project.
        tuning: The tuning.
    """
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
    grammar: Any = None,
) -> tuple[Tuning, bench.Evaluation | None]:
    """``tune``, then writes new best settings into solve.json and checks them.

    They are judged against revision ``rev`` on the validation split, if the benchmark has one. The
    tuning's record is kept even when that fails.

    Args:
        project: The project.
        rev: The revision whose settings are tuned.
        space: A list of the parameters of ``variant``, or a dict of each variant's parameters.
        budget: The runs the race may make.
        variant: The variant to tune; None when solve.json has only one, or ``space`` is a dict.
        seed: The race's seed; the benchmark's when None.
        progress: Called as runs finish, if given.
        grammar: Instead of ``space``, the leaves to compose and race (compose.py).

    Returns:
        The tuning, and the evaluation on validation if there was one.

    Raises:
        ProjectError: The tuning failed, or the evaluation did; then the error says the project
            files hold the tuned settings.
    """
    tuning = await tune(project, rev, space, budget, variant, seed, progress, grammar)
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
    """The settings alive at the end of the last race, its Friedman p-value and their mean ranks.

    Args:
        t: The tuning.

    Returns:
        The settings, the p-value, and each setting's mean rank in the settings' order.
    """
    last = t.iterations[-1]
    alive = [
        s for s in t.settings if s.id in last["raced"] and s.error is None and not s.eliminated
    ]
    p, sums, _ = friedman(
        [[t.score(s.results[task]) for s in alive] for task in range(last["tasks"])]
    )
    return alive, p, [total / last["tasks"] for total in sums]


def _early(runs: list[RunFinished]) -> float | None:
    """The mean share of a run's iterations gone when it found its best.

    Args:
        runs: The runs.

    Returns:
        The share, or None when no run made an iteration.
    """
    shares = [r.best_iteration / r.iterations for r in runs if r.iterations > 0]
    return statistics.fmean(shares) if shares else None


def signs(t: Tuning) -> list[str]:
    """What the race shows that settings cannot fix, each with the change of structure it suggests.

    They are hints for the agent's next hypothesis, not verdicts.

    Args:
        t: The tuning.

    Returns:
        The signs, as sentences.
    """
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

    runs = list(best.runs.values())
    early = _early(runs)
    if early is not None and early < EARLY:
        found.append(
            f"#{best.id} finds its best {early:.0%} of the way through a run on average; the "
            "search stalls after that: diversify (a perturbation, restarts)"
        )
    rate = bench.acceptance(runs)
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
    """What the agent reads of a tuning.

    Args:
        tuning: The tuning.
        evaluation: Its evaluation on validation, if there was one.

    Returns:
        The report's text: the elites, the failures, the signs, and what became of solve.json.
    """
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
    if t.note:
        lines.insert(1, t.note)
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
    runs = list(t.best.runs.values())
    if runs:
        lines.append(
            f"#{t.best.id}'s runs: {bench.speed(runs):,.0f} iterations/s, best found "
            f"{bench.share(_early(runs))} of the way through, "
            f"{bench.share(bench.acceptance(runs))} of moves accepted"
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
    """A setting's gain over the revision's settings, in words.

    Args:
        t: The tuning.
        s: The setting.

    Returns:
        The words.
    """
    if s is t.default:
        return "the revision's settings"
    gain = t.gain(s)
    return f"{gain[0]:+.3%} over {gain[1]} runs" if gain else "no runs shared"


def describe(project: Project) -> list[str]:
    """A line per tuning, for bench_list.

    Args:
        project: The project.

    Returns:
        The lines of the last ten tunings.
    """
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
