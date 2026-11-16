"""Judging a change of the algorithm on a benchmark of instances (docs/adr/0013).

``bench/bench.json`` lists the instances (``bench/instances/<name>.json``), each in the train,
the validation or the test split, and the budget each run gets. ``evaluate`` solves every
instance of a split with a candidate (the project's work files, or a revision) and a baseline
revision, each run of one side from the same seed as the same run of the other, and compares
them:

- **reference**: the baseline's model scores every solution the candidate found again. A
  candidate whose model scores its solutions otherwise, or finds solutions the baseline's model
  cannot decode, has changed the problem rather than the algorithm, and is rejected.
- **paired**: each pair of runs differs by a gain relative to the baseline's mean on that
  instance, so instances of different scales count alike. A Wilcoxon signed-rank test over all
  pairs says whether the candidate is better, or worse.
- **per instance**: how many instances got better, stayed or got worse, and the mean worsening
  over the instances, counted one way only, so a gain on one cannot hide a loss on another.

The verdict is "better" only for a significant gain whose worsening is at most
``WORSENING_LIMIT``. The budget replaces the stop of the heuristic each side runs, so a candidate
cannot win by searching longer.

``compare`` is the same for several candidates at once, which share the baseline's runs (a race,
candidates.py). The test split is left out of "all": it measures what is reported after the
choices are made, and no choice reads it (docs/adr/0018). ``bench/best.json`` keeps the best
solution known on each instance, from the evaluations whose objectives the reference confirmed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import statistics
from collections import Counter
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import (
    BenchBest,
    BenchCandidate,
    BenchEvaluation,
    BenchInstance,
    BenchInstanceResult,
    BenchProfile,
    BenchProfileVariant,
    BenchProgress,
    BenchRace,
    BenchRaceEntry,
    BenchSide,
    BenchSpec,
    BenchSplit,
    BenchState,
    BenchTask,
    BenchTuning,
    EvaluateRequest,
    RunFinished,
    RunSummary,
    SolveRequest,
    Variant,
    Verdict,
)
from optopus_studio.runner import evaluate_solutions, ignore_progress, run_solve, worker_command
from optopus_studio.solving import initial_solution, rust_binary, solve_timeout

ALPHA = 0.05
# The mean relative worsening over the instances a "better" candidate may have.
WORSENING_LIMIT = 0.01
# A relative difference this small is a tie.
TIE = 1e-9
# Values this close share a rank.
RANK_TIE = 1e-12
# How closely the baseline's model must score a candidate's solution as the candidate does: a
# model that updates its objective by deltas drifts by rounding over a long run.
AGREE = 1e-6
# Up to this many pairs the signed-rank test is exact, beyond it a normal approximation.
EXACT_PAIRS = 200

Split = BenchSplit
# Told how far a task on the benchmark has got.
Progress = Callable[[BenchProgress], Awaitable[None]]
# The files a side's record hashes: what makes a candidate the same as a revision.
ALGORITHM_FILES = ("model.py", "solve.json", "rust/main.rs")


# --- the benchmark on disk ---------------------------------------------------------------------


def spec_path(project: Project) -> Path:
    """Where the benchmark's spec is kept.

    Args:
        project: The project.

    Returns:
        The path of ``bench/bench.json``.
    """
    return project.bench / "bench.json"


def instance_path(project: Project, name: str) -> Path:
    """Where a benchmark instance is kept.

    Args:
        project: The project.
        name: The instance's name.

    Returns:
        The path of ``bench/instances/<name>.json``.
    """
    return project.bench / "instances" / f"{name}.json"


def load_spec(project: Project) -> BenchSpec:
    """The benchmark's spec; an empty one before anything was added.

    Args:
        project: The project.

    Returns:
        The spec.
    """
    path = spec_path(project)
    if not path.is_file():
        return BenchSpec()
    return BenchSpec.model_validate_json(path.read_text())


def save_spec(project: Project, spec: BenchSpec) -> None:
    """Writes the benchmark's spec.

    Args:
        project: The project.
        spec: The benchmark's spec.
    """
    project.bench.mkdir(exist_ok=True)
    spec_path(project).write_text(spec.model_dump_json(indent=2))


def configure(project: Project, **settings: Any) -> BenchSpec:
    """Changes the runs, seed or budget of every later evaluation.

    Args:
        project: The project.
        **settings: The spec's fields to set: runs, seed, max_duration_secs, max_iteration.

    Returns:
        The new spec.

    Raises:
        ProjectError: A setting is invalid, or the runs would have no budget.
    """
    spec = load_spec(project)
    try:
        spec = BenchSpec.model_validate({**spec.model_dump(), **settings})
    except ValidationError as exc:
        raise ProjectError(f"not a benchmark setting: {exc}") from exc
    if spec.max_duration_secs is None and spec.max_iteration is None:
        raise ProjectError("give each run a budget: max_duration_secs, max_iteration or both")
    save_spec(project, spec)
    return spec


def add_instance(
    project: Project, name: str, split: str, source: str, instance: Any
) -> BenchInstance:
    """Stores ``instance`` under ``name``, replacing an instance of that name.

    Args:
        project: The project.
        name: The instance's name.
        split: ``train``, ``validation`` or ``test``.
        source: Where the instance came from, such as "revision 3".
        instance: The instance, in instance.json's form.

    Returns:
        The instance's entry in the spec, with its hash.

    Raises:
        ProjectError: The instance is not a JSON object, or the name or split is invalid.
    """
    if not isinstance(instance, dict):
        raise ProjectError("an instance must be a JSON object, as instance.json is")
    text = json.dumps(instance, ensure_ascii=False, indent=1)
    try:
        entry = BenchInstance(name=name, split=split, source=source, sha256=_sha256(text))
    except ValidationError as exc:
        raise ProjectError(f"cannot add {name!r}: {exc}") from exc
    path = instance_path(project, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    spec = load_spec(project)
    spec.instances = [i for i in spec.instances if i.name != name] + [entry]
    save_spec(project, spec)
    return entry


def remove_instance(project: Project, name: str) -> None:
    """Removes an instance from the benchmark, and its file.

    Args:
        project: The project.
        name: The instance's name.

    Raises:
        ProjectError: There is no such instance.
    """
    spec = load_spec(project)
    if not any(i.name == name for i in spec.instances):
        raise ProjectError(f"no benchmark instance {name!r}")
    spec.instances = [i for i in spec.instances if i.name != name]
    save_spec(project, spec)
    instance_path(project, name).unlink(missing_ok=True)


def read_instance(project: Project, entry: BenchInstance) -> dict[str, Any]:
    """Reads a benchmark instance, after checking it is what was added.

    Args:
        project: The project.
        entry: The instance's entry in the spec.

    Returns:
        The instance.

    Raises:
        ProjectError: The file is missing, or changed since it was added.
    """
    path = instance_path(project, entry.name)
    if not path.is_file():
        raise ProjectError(f"the file of benchmark instance {entry.name!r} is missing")
    text = path.read_text()
    if _sha256(text) != entry.sha256:
        raise ProjectError(f"benchmark instance {entry.name!r} changed since it was added")
    return json.loads(text)


def instances_of(spec: BenchSpec, split: Split) -> list[BenchInstance]:
    """The instances of a split.

    Args:
        spec: The benchmark's spec.
        split: ``train``, ``validation``, ``test``, or ``all`` for train and validation.

    Returns:
        Their entries, in the spec's order.
    """
    wanted = ("train", "validation") if split == "all" else (split,)
    return [i for i in spec.instances if i.split in wanted]


def _sha256(text: str) -> str:
    """The SHA-256 of a text.

    Args:
        text: The text.

    Returns:
        The hash, in hex.
    """
    return hashlib.sha256(text.encode()).hexdigest()


# --- the two sides -----------------------------------------------------------------------------


@dataclass
class Side:
    """What one side of an evaluation solves with.

    Attributes:
        root: The directory of its files: the work files, or a revision's.
        solve: Its solve.json.
        variant: The heuristic it runs.
        binary: Its built Rust port, or None for the Python worker.
    """

    root: Path
    solve: dict[str, Any]
    variant: Variant
    binary: Path | None

    @property
    def worker(self) -> str:
        """The worker the side runs on: python or rust."""
        return "rust" if self.binary else "python"


def pick_variant(solve: dict[str, Any], label: str | None, where: str) -> Variant:
    """A variant of solve.json by its label.

    Args:
        solve: solve.json's content.
        label: The variant's label; None when solve.json has only one.
        where: Whose solve.json it is, in words, for the errors.

    Returns:
        The variant.

    Raises:
        ProjectError: There is no such variant, or no label is given and there are several.
    """
    variants = variants_of(solve)
    if label is None:
        if len(variants) > 1:
            labels = [v.label for v in variants]
            raise ProjectError(f"{where} compares {labels}; say which variant to evaluate")
        return variants[0]
    for v in variants:
        if v.label == label:
            return v
    raise ProjectError(f"{where} has no variant {label!r}; it has {[v.label for v in variants]}")


async def side(root: Path, label: str | None, where: str) -> Side:
    """Gets a side ready: reads its solve.json, picks its variant and builds its port.

    Args:
        root: The directory of its files.
        label: The variant to run; None when solve.json has only one.
        where: Whose files they are, in words.

    Returns:
        The side.

    Raises:
        ProjectError: The files are missing or broken, or the port does not build.
    """
    if not (root / "solve.json").is_file() or not (root / "model.py").is_file():
        raise ProjectError(f"{where} has no model.py and solve.json to evaluate")
    try:
        solve = json.loads((root / "solve.json").read_text())
    except json.JSONDecodeError as exc:
        raise ProjectError(f"the solve.json of {where} is not JSON: {exc}") from exc
    main_rs = root / "rust" / "main.rs"
    binary = await rust_binary(solve, main_rs.read_text() if main_rs.is_file() else None)
    return Side(root, solve, pick_variant(solve, label, where), binary)


def stop_of(spec: BenchSpec) -> dict[str, Any]:
    """The benchmark's budget as a heuristic's stop.

    Args:
        spec: The benchmark's spec.

    Returns:
        The stop condition's arguments.
    """
    limits = (("max_duration_secs", spec.max_duration_secs), ("max_iteration", spec.max_iteration))
    return {key: value for key, value in limits if value is not None}


def budgeted(variant: Variant, spec: BenchSpec) -> Variant:
    """The variant with the benchmark's budget as its stop, whatever stop it had.

    Args:
        variant: The variant.
        spec: The benchmark's spec.

    Returns:
        A copy of the variant with that stop.
    """
    return Variant(label=variant.label, heuristic={**variant.heuristic, "stop": stop_of(spec)})


def request_for(
    s: Side,
    instance: dict[str, Any],
    spec: BenchSpec,
    variants: list[Variant] | None = None,
    runs: int | None = None,
    seed: int | None = None,
) -> SolveRequest:
    """A solve of ``instance`` with the side's variant, or ``variants``, on the benchmark's budget.

    The benchmark's runs and seed apply unless others are given.

    Args:
        s: The side.
        instance: The instance.
        spec: The benchmark's spec.
        variants: The variants to run instead of the side's.
        runs: The runs, instead of the benchmark's.
        seed: The seed, instead of the benchmark's.

    Returns:
        The request.

    Raises:
        ProjectError: The side's solve.json starts from a solution the instance does not hold.
    """
    return SolveRequest(
        model_path=str(s.root / "model.py"),
        instance=instance,
        variants=[budgeted(v, spec) for v in variants or [s.variant]],
        runs=spec.runs if runs is None else runs,
        seed=spec.seed if seed is None else seed,
        initial_solution=initial_solution(s.solve, instance),
    )


def parallelism() -> int:
    """How many solves run at once: ``OPTOPUS_STUDIO_BENCH_PARALLEL``, or half the cores.

    Returns:
        The number, at least 1.
    """
    configured = os.environ.get("OPTOPUS_STUDIO_BENCH_PARALLEL")
    if configured:
        return max(1, int(configured))
    # Runs on a time budget are compared by what they reach in that time, so leave cores free.
    return max(1, (os.cpu_count() or 2) // 2)


async def solve_all(
    jobs: list[tuple[Side, SolveRequest]], task: BenchTask, progress: Progress | None = None
) -> list[RunSummary]:
    """Solves each request with its side, ``parallelism()`` at a time, in the order given.

    Args:
        jobs: Each side and the request it solves.
        task: The task the solves belong to, as the progress says.
        progress: Called as each solve finishes, if given.

    Returns:
        Each solve's summary, in the order of ``jobs``.
    """
    gate = asyncio.Semaphore(parallelism())
    done = 0

    async def solve(s: Side, request: SolveRequest) -> RunSummary:
        """Solves one request when a slot is free, and reports the progress.

        Args:
            s: The side.
            request: The request.

        Returns:
            The solve's summary.
        """
        nonlocal done
        async with gate:
            summary = await run_solve(
                request, 0, s.root, ignore_progress, solve_timeout(request), rust_binary=s.binary
            )
        done += 1
        if progress:
            await progress(BenchProgress(task=task, done=done, total=len(jobs)))
        return summary

    return await all_of([solve(s, request) for s, request in jobs])


async def all_of[T](coroutines: list[Coroutine[Any, Any, T]]) -> list[T]:
    """Runs coroutines together and returns their results in order.

    One that raises cancels the others, solves and their workers with them, and its exception is
    raised as it is.

    Args:
        coroutines: The coroutines.

    Returns:
        Their results, in order.
    """
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(c) for c in coroutines]
    except ExceptionGroup as failed:
        raise failed.exceptions[0] from None
    return [t.result() for t in tasks]


# --- statistics --------------------------------------------------------------------------------


def ranks(values: list[float]) -> list[float]:
    """Ranks from 1 for the lowest, ties sharing the mean of their ranks.

    Args:
        values: The values.

    Returns:
        Each value's rank, in the values' order.
    """
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and math.isclose(
            values[order[j + 1]], values[order[i]], rel_tol=RANK_TIE, abs_tol=RANK_TIE
        ):
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def wilcoxon(diffs: list[float]) -> tuple[float, float]:
    """One-sided p-values of the Wilcoxon signed-rank test that the differences center on 0.

    The test is against "greater" and against "less". Zeros are dropped; tied magnitudes share a
    rank. Up to ``EXACT_PAIRS`` differences the distribution is exact, beyond it normal.

    Args:
        diffs: The paired differences.

    Returns:
        The p-value against "greater" and the one against "less".
    """
    d = [x for x in diffs if abs(x) > TIE]
    n = len(d)
    if n == 0:
        return 1.0, 1.0
    ranked = ranks([abs(x) for x in d])
    # Tied magnitudes share a rank, so each rank's count is the size of a group of ties.
    ties = Counter(ranked).values()
    w_plus = sum(r for r, x in zip(ranked, d, strict=True) if x > 0)
    if n <= EXACT_PAIRS:
        # Doubled ranks are integers; count how many sign patterns reach each rank sum.
        doubled = [round(2 * r) for r in ranked]
        dist = [1.0]
        for r in doubled:
            grown = dist + [0.0] * r
            for s in range(len(dist)):
                grown[s + r] += dist[s]
            dist = [p / 2 for p in grown]
        observed = round(2 * w_plus)
        greater = sum(dist[observed:])
        less = sum(dist[: observed + 1])
        return min(1.0, greater), min(1.0, less)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - sum(t**3 - t for t in ties) / 48
    sd = math.sqrt(var)
    normal = statistics.NormalDist()
    return 1 - normal.cdf((w_plus - mean - 0.5) / sd), normal.cdf((w_plus - mean + 0.5) / sd)


# --- an evaluation -----------------------------------------------------------------------------


@dataclass
class InstanceResult:
    """Both sides' runs on one instance, and the gains they pair into.

    Attributes:
        name: The instance's name.
        sha256: The hash of the instance's file.
        baseline: The baseline's runs.
        candidate: The candidate's runs, paired with the baseline's by seed.
        higher_is_better: The direction the objectives are ranked in.
        gains: Each pair's gain relative to the baseline's mean; positive is better.
    """

    name: str
    sha256: str
    baseline: list[RunFinished]
    candidate: list[RunFinished]
    higher_is_better: bool
    gains: list[float] = field(init=False)

    def __post_init__(self) -> None:
        """Pairs the runs into gains."""
        sign = -1.0 if self.higher_is_better else 1.0
        base = [r.best_objective for r in self.baseline]
        scale = max(abs(statistics.fmean(base)), TIE)
        self.gains = [
            sign * (b.best_objective - c.best_objective) / scale
            for b, c in zip(self.baseline, self.candidate, strict=True)
        ]

    @property
    def gain(self) -> float:
        """The mean gain over the pairs."""
        return statistics.fmean(self.gains)

    @property
    def outcome(self) -> Literal["better", "same", "worse"]:
        """Whether the candidate did better, the same or worse on the instance."""
        if self.gain > TIE:
            return "better"
        return "worse" if self.gain < -TIE else "same"


@dataclass
class Evaluation:
    """One evaluation of a candidate against a baseline revision, and its verdict.

    Attributes:
        id: The evaluation's number among the project's; 0 until it is kept.
        split: The instances it ran on.
        spec: The benchmark's runs, seed and budget.
        candidate: The candidate side, as its record describes it.
        baseline: The baseline side, as its record describes it.
        instances: The results on each instance.
        reference: What the baseline's model said of the candidate's solutions.
        error: Why the candidate failed, if it did.
        verdict: The verdict.
        p_better: The p-value against "better".
        p_worse: The p-value against "worse".
    """

    id: int
    split: Split
    spec: BenchSpec
    candidate: dict[str, Any]
    baseline: dict[str, Any]
    instances: list[InstanceResult] = field(default_factory=list)
    reference: str = ""
    error: str | None = None
    verdict: Verdict = "failed"
    p_better: float = 1.0
    p_worse: float = 1.0

    @property
    def gains(self) -> list[float]:
        """Every pair's gain, over all the instances."""
        return [g for i in self.instances for g in i.gains]

    @property
    def judged(self) -> bool:
        """Whether the candidate was compared, rather than rejected or failed."""
        return self.verdict not in ("rejected", "failed")

    @property
    def worsening(self) -> float:
        """The mean worsening over the instances, counted one way only."""
        if not self.instances:
            return 0.0
        return statistics.fmean(max(0.0, -i.gain) for i in self.instances)

    def judge(self) -> None:
        """Sets the p-values and the verdict from the gains."""
        self.p_better, self.p_worse = wilcoxon(self.gains)
        if self.p_better < ALPHA:
            self.verdict = "better" if self.worsening <= WORSENING_LIMIT else "mixed"
        elif self.p_worse < ALPHA:
            self.verdict = "worse"
        else:
            self.verdict = "same"

    def to_json(self) -> dict[str, Any]:
        """The evaluation's record, as kept in ``bench/results``.

        Returns:
            The record, its runs without their solutions and trajectories.
        """
        return {
            "id": self.id,
            "split": self.split,
            "spec": self.spec.model_dump(mode="json"),
            "candidate": self.candidate,
            "baseline": self.baseline,
            "verdict": self.verdict,
            "error": self.error,
            "reference": self.reference,
            "p_better": self.p_better,
            "p_worse": self.p_worse,
            "worsening": self.worsening,
            "gain": statistics.fmean(self.gains) if self.judged else None,
            "instances": [
                {
                    "name": i.name,
                    "sha256": i.sha256,
                    "gain": i.gain,
                    "outcome": i.outcome,
                    "baseline": [r.model_dump(mode="json", exclude=UNKEPT) for r in i.baseline],
                    "candidate": [r.model_dump(mode="json", exclude=UNKEPT) for r in i.candidate],
                }
                for i in self.instances
            ],
        }


# What a record leaves out of a run: the solution, and the trajectory nothing reads back.
UNKEPT = {"solution", "trajectory"}


def results_dir(project: Project) -> Path:
    """Where the evaluations' records are kept.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "results"


def tunings_dir(project: Project) -> Path:
    """Where the tunings' records are kept.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "tunings"


def profiles_dir(project: Project) -> Path:
    """Where the profiles' records are kept.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "profiles"


def candidates_dir(project: Project) -> Path:
    """Where the saved candidates are kept: ``<n>.json``, and the files in ``<n>/``.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "candidates"


def races_dir(project: Project) -> Path:
    """Where the races' records are kept.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "races"


def diagnoses_dir(project: Project) -> Path:
    """Where the diagnoses' records are kept.

    Args:
        project: The project.

    Returns:
        The directory's path.
    """
    return project.bench / "diagnoses"


def diagnoses(project: Project) -> list[dict[str, Any]]:
    """Every diagnosis's record (diagnosis.py), oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(diagnoses_dir(project))


def candidate_records(project: Project) -> list[dict[str, Any]]:
    """Every saved candidate's record (candidates.py), oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(candidates_dir(project))


def races(project: Project) -> list[dict[str, Any]]:
    """Every race's record (candidates.py), oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(races_dir(project))


def history(project: Project) -> list[dict[str, Any]]:
    """Every evaluation's result, oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(results_dir(project))


def profiles(project: Project) -> list[dict[str, Any]]:
    """Every profile's record (profiling.py), oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(profiles_dir(project))


def tunings(project: Project) -> list[dict[str, Any]]:
    """Every tuning's record (tune.py), oldest first.

    Args:
        project: The project.

    Returns:
        The records.
    """
    return _records(tunings_dir(project))


def _records(path: Path) -> list[dict[str, Any]]:
    """The records in a directory, by number.

    Args:
        path: The directory.

    Returns:
        The records, the lowest number first; empty when there is no directory.
    """
    if not path.is_dir():
        return []
    files = sorted((p for p in path.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    return [json.loads(p.read_text()) for p in files]


def next_id(path: Path) -> int:
    """The number the next record in a directory takes.

    Args:
        path: The directory.

    Returns:
        One more than the highest number there, or 1.
    """
    ids = [int(p.stem) for p in path.glob("*.json") if p.stem.isdigit()] if path.is_dir() else []
    return max(ids, default=0) + 1


def keep_record(path: Path, id: int, record: dict[str, Any]) -> None:
    """Writes a record as ``<id>.json`` in ``path``, which ``_records`` reads back.

    Args:
        path: The directory.
        id: The record's number.
        record: The record.
    """
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{id}.json").write_text(json.dumps(record, indent=1))


@dataclass
class Contender:
    """One side of a comparison and how its record names it.

    Attributes:
        side: What it solves with.
        where: Whose files they are, in words.
        rev: Its revision, or None for the work files or a saved candidate.
        note: What it changes, in the agent's words.
        candidate_id: The saved candidate it is, if it is one (candidates.py).
    """

    side: Side
    where: str
    rev: int | None = None
    note: str = ""
    candidate_id: int | None = None

    def describe(self) -> dict[str, Any]:
        """The side as an evaluation's record describes it.

        Returns:
            The description, with its files' hashes.
        """
        return {
            "where": self.where,
            "rev": self.rev,
            "variant": self.side.variant.label,
            "worker": self.side.worker,
            "files": file_hashes(self.side.root),
            "candidate_id": self.candidate_id,
        }


async def evaluate(
    project: Project,
    baseline_rev: int,
    split: Split = "train",
    candidate_rev: int | None = None,
    variant: str | None = None,
    baseline_variant: str | None = None,
    note: str = "",
    progress: Progress | None = None,
) -> Evaluation:
    """Compares a candidate with a baseline revision on a split and keeps the result.

    Once both sides are set up, the result is kept in ``bench/results``, whether the candidate is
    judged, rejected or fails. A failure on the baseline's side raises instead, and keeps nothing.

    Args:
        project: The project.
        baseline_rev: The baseline revision.
        split: The instances to compare on.
        candidate_rev: The candidate revision, or None for the work files.
        variant: The candidate's variant; None when its solve.json has only one.
        baseline_variant: The baseline's variant; None when its solve.json has only one.
        note: What the candidate changes, in the agent's words.
        progress: Called as solves finish, if given.

    Returns:
        The evaluation.

    Raises:
        ProjectError: The split has no instances, a side cannot be set up, or the baseline fails.
    """
    base_where = f"revision {baseline_rev}"
    cand_where = "the work files" if candidate_rev is None else f"revision {candidate_rev}"
    cand_root = project.work if candidate_rev is None else project.rev_dir(candidate_rev)
    base = await side(project.rev_dir(baseline_rev), baseline_variant, base_where)
    cand = await side(cand_root, variant, cand_where)
    (evaluation,) = await compare(
        project,
        Contender(base, base_where, baseline_rev),
        [Contender(cand, cand_where, candidate_rev, note)],
        split,
        progress=progress,
    )
    return evaluation


async def compare(
    project: Project,
    baseline: Contender,
    candidates: list[Contender],
    split: Split = "train",
    task: BenchTask = "evaluation",
    progress: Progress | None = None,
) -> list[Evaluation]:
    """Compares each candidate with the baseline on a split, and keeps an evaluation of each.

    The baseline runs once, and every candidate is paired with those runs: on each instance, run
    ``i`` of every side starts from the same seed. Each candidate is then judged as ``evaluate``
    judges one, on its own.

    Args:
        project: The project.
        baseline: The baseline side.
        candidates: The candidate sides.
        split: The instances to compare on.
        task: The task the solves belong to, as the progress says.
        progress: Called as solves finish, if given.

    Returns:
        Each candidate's evaluation, in the candidates' order.

    Raises:
        ProjectError: The split has no instances, or the baseline fails.
    """
    spec = load_spec(project)
    entries = instances_of(spec, split)
    if not entries:
        raise ProjectError(f"the benchmark has no {split} instances; add some with bench_add")
    data = [(entry, read_instance(project, entry)) for entry in entries]
    base = baseline.side
    evaluations = [
        Evaluation(
            id=0,
            split=split,
            spec=spec,
            candidate={**c.describe(), "note": c.note},
            baseline=baseline.describe(),
        )
        for c in candidates
    ]

    # A side whose solve.json starts from a solution the instances do not hold cannot run.
    live = []
    try:
        base_requests = [request_for(base, inst, spec) for _, inst in data]
    except ProjectError as exc:
        for evaluation in evaluations:
            evaluation.error = str(exc)
        return [_keep(project, e) for e in evaluations]
    requests = {}
    for c, evaluation in zip(candidates, evaluations, strict=True):
        try:
            requests[id(c)] = [request_for(c.side, inst, spec) for _, inst in data]
            live.append((c, evaluation))
        except ProjectError as exc:
            evaluation.error = str(exc)

    # Interleaved, so every side runs under the same load.
    jobs = []
    for n in range(len(data)):
        jobs.append((base, base_requests[n]))
        jobs += [(c.side, requests[id(c)][n]) for c, _ in live]
    summaries = await solve_all(jobs, task, progress)
    width = 1 + len(live)
    for n, (entry, _) in enumerate(data):
        b = summaries[n * width]
        if b.error:
            raise ProjectError(
                f"{baseline.where} fails on {entry.name!r} at {b.error.stage}: {b.error.message}"
            )
        for k, (c, evaluation) in enumerate(live):
            if evaluation.error or evaluation.verdict == "rejected":
                continue
            s = summaries[n * width + 1 + k]
            if s.error:
                evaluation.error = (
                    f"{c.where} fails on {entry.name!r} at {s.error.stage}: {s.error.message}"
                )
            elif b.higher_is_better != s.higher_is_better:
                evaluation.verdict = "rejected"
                evaluation.reference = (
                    f"the candidate ranks its objective the other way on {entry.name!r}: "
                    f"higher_is_better is {s.higher_is_better}, the baseline's "
                    f"{b.higher_is_better}"
                )
            else:
                evaluation.instances.append(
                    InstanceResult(
                        entry.name, entry.sha256, b.runs, s.runs, bool(b.higher_is_better)
                    )
                )

    for _, evaluation in live:
        if evaluation.error or evaluation.verdict == "rejected":
            continue
        problem = await _check_reference(base, data, evaluation)
        if problem:
            evaluation.verdict = "rejected"
            evaluation.reference = problem
            continue
        solutions = sum(len(i.candidate) for i in evaluation.instances)
        evaluation.reference = (
            f"the baseline's model scores all {solutions} of the candidate's solutions as the "
            "candidate does"
        )
        evaluation.judge()
    return [_keep(project, e) for e in evaluations]


async def _check_reference(
    base: Side, data: list[tuple[BenchInstance, dict[str, Any]]], evaluation: Evaluation
) -> str | None:
    """Why the baseline's model does not agree with the candidate's objectives, if it does not.

    Args:
        base: The baseline side.
        data: Each instance's entry and content.
        evaluation: The evaluation, with the candidate's runs.

    Returns:
        The disagreement in words, or None when the model scores every solution as the candidate
        did.
    """
    command = [str(base.binary)] if base.binary else worker_command()
    gate = asyncio.Semaphore(parallelism())

    async def score(instance: dict[str, Any], result: InstanceResult) -> list[float] | Exception:
        """Scores the candidate's solutions on one instance with the baseline's model.

        Args:
            instance: The instance.
            result: The runs on it.

        Returns:
            Each solution's objective, or the exception the scoring raised.
        """
        request = EvaluateRequest(
            model_path=str(base.root / "model.py"),
            instance=instance,
            solutions=[r.solution for r in result.candidate],
            heuristic=base.variant.heuristic,
        )
        async with gate:
            try:
                return await evaluate_solutions(command, request, base.root)
            except (RuntimeError, OSError) as exc:
                return exc

    scored = await asyncio.gather(
        *(score(inst, result) for (_, inst), result in zip(data, evaluation.instances, strict=True))
    )
    for (entry, _), result, objectives in zip(data, evaluation.instances, scored, strict=True):
        if isinstance(objectives, Exception):
            return (
                f"the baseline's model cannot score the candidate's solutions on "
                f"{entry.name!r}: {objectives}"
            )
        for run, got in zip(result.candidate, objectives, strict=True):
            if not math.isclose(run.best_objective, got, rel_tol=AGREE, abs_tol=AGREE):
                return (
                    f"on {entry.name!r} the candidate reports {run.best_objective!r} for the best "
                    f"solution of its run {run.run}, which the baseline's model scores {got!r}: "
                    "the candidate changed the objective, not only the search"
                )
    return None


def file_hashes(root: Path) -> dict[str, str]:
    """The hashes of the files that make an algorithm.

    Args:
        root: The directory of the files.

    Returns:
        Each file's hash, by name, for the files there are.
    """
    return {
        name: _sha256((root / name).read_text())
        for name in ALGORITHM_FILES
        if (root / name).is_file()
    }


def _keep(project: Project, evaluation: Evaluation) -> Evaluation:
    """Numbers the evaluation and keeps its record.

    Args:
        project: The project.
        evaluation: The evaluation.

    Returns:
        The evaluation, with its number.
    """
    # The id is taken when the record is written, so evaluations that overlap get their own.
    evaluation.id = next_id(results_dir(project))
    keep_record(results_dir(project), evaluation.id, evaluation.to_json())
    if evaluation.judged:
        # The reference agreed with the candidate's objectives, so both sides' count.
        note_best(
            project,
            f"evaluation {evaluation.id}",
            {i.name: (i.sha256, i.baseline + i.candidate) for i in evaluation.instances},
            evaluation.instances[0].higher_is_better,
        )
    return evaluation


# --- the best known ----------------------------------------------------------------------------


def best_path(project: Project) -> Path:
    """Where the best solution known on each instance is kept.

    Args:
        project: The project.

    Returns:
        The path of ``bench/best.json``.
    """
    return project.bench / "best.json"


def best_known(project: Project) -> dict[str, dict[str, Any]]:
    """The best solution known on each instance still in the benchmark as it was found on.

    An entry holds the instance's ``sha256``, the ``objective``, ``higher_is_better``, the
    ``solution`` as encode_solution wrote it, and its ``source``. The objective is the model's
    that found it: one who needs it under another model scores the solution again.

    Args:
        project: The project.

    Returns:
        The entries, by instance name.
    """
    path = best_path(project)
    if not path.is_file():
        return {}
    hashes = {i.name: i.sha256 for i in load_spec(project).instances}
    kept = json.loads(path.read_text())
    return {name: b for name, b in kept.items() if hashes.get(name) == b["sha256"]}


def note_best(
    project: Project,
    source: str,
    runs: dict[str, tuple[str, list[RunFinished]]],
    higher_is_better: bool,
) -> None:
    """Keeps the runs' solutions that beat the best known on their instances.

    Args:
        project: The project.
        source: What made the runs, such as "evaluation 4".
        runs: By instance name, the hash of the instance's file and the runs on it.
        higher_is_better: The direction the objectives are ranked in.
    """
    known = best_known(project)
    changed = False
    for name, (sha256, made) in runs.items():
        if not made:
            continue
        pick = max if higher_is_better else min
        run = pick(made, key=lambda r: r.best_objective)
        old = known.get(name)
        if old is not None and old["higher_is_better"] == higher_is_better:
            gain = run.best_objective - old["objective"]
            if (gain if higher_is_better else -gain) <= TIE * max(abs(old["objective"]), 1.0):
                continue
        known[name] = {
            "sha256": sha256,
            "objective": run.best_objective,
            "higher_is_better": higher_is_better,
            "solution": run.solution,
            "source": source,
        }
        changed = True
    if changed:
        project.bench.mkdir(exist_ok=True)
        best_path(project).write_text(json.dumps(known))


# --- what the agent reads ----------------------------------------------------------------------


def speed(runs: Iterable[RunFinished]) -> float:
    """Iterations per second over the runs.

    Args:
        runs: The runs.

    Returns:
        The iterations per second; 0 when the runs took no time.
    """
    runs = list(runs)
    seconds = sum(r.total_time_secs for r in runs)
    return sum(r.iterations for r in runs) / seconds if seconds > 0 else 0.0


def acceptance(runs: Iterable[RunFinished]) -> float | None:
    """The share of moves accepted over the runs.

    Args:
        runs: The runs.

    Returns:
        The share; None when a run did not count them, or none was made.
    """
    runs = list(runs)
    if any(r.n_accepted is None or r.n_rejected is None for r in runs):
        return None
    accepted = sum(r.n_accepted or 0 for r in runs)
    moves = accepted + sum(r.n_rejected or 0 for r in runs)
    return accepted / moves if moves else None


def share(value: float | None) -> str:
    """A share as a whole percentage.

    Args:
        value: The share, or None.

    Returns:
        The percentage, or "?" when there is none.
    """
    return "?" if value is None else f"{value:.0%}"


# What each side's runs on an instance show, baseline -> candidate.
METRICS = ("mean objective", "iterations/s", "time to best", "accepted")


def _side_line(runs: list[RunFinished]) -> tuple[str, ...]:
    """What one side's runs on an instance show: ``METRICS`` in words.

    Args:
        runs: The runs.

    Returns:
        Each metric's value, in ``METRICS``' order.
    """
    values = [r.best_objective for r in runs]
    return (
        f"{statistics.fmean(values):g}",
        f"{speed(runs):,.0f}",
        f"{statistics.fmean(r.time_to_best_secs for r in runs):.3g}s",
        share(acceptance(runs)),
    )


def describe_budget(spec: BenchSpec) -> str:
    """Each run's budget in words: the time, the iterations, or both.

    Args:
        spec: The benchmark's spec.

    Returns:
        The words, such as "1s or 3000 iterations".
    """
    return " or ".join(
        part
        for part in (
            f"{spec.max_duration_secs:g}s" if spec.max_duration_secs else "",
            f"{spec.max_iteration} iterations" if spec.max_iteration else "",
        )
        if part
    )


def report(evaluation: Evaluation) -> str:
    """What the agent reads of an evaluation.

    Args:
        evaluation: The evaluation.

    Returns:
        The report's text: the setup, the failure or rejection, or each instance and the verdict.
    """
    e = evaluation
    head = (
        f"evaluation {e.id}: {e.candidate['where']} (variant {e.candidate['variant']}, "
        f"{e.candidate['worker']} worker) against {e.baseline['where']} (variant "
        f"{e.baseline['variant']}, {e.baseline['worker']} worker) on {e.split}: "
        f"{e.spec.runs} runs per instance, {describe_budget(e.spec)} each, seed {e.spec.seed}"
    )
    lines = [head]
    if e.error:
        return "\n".join([*lines, f"FAILED: {e.error}"])
    if e.verdict == "rejected":
        return "\n".join([*lines, f"REJECTED: {e.reference}"])
    lines.append(f"reference: {e.reference}")
    lines.append(
        "per instance: gain relative to the baseline's mean (+ is better), wins/ties/losses "
        "over the paired runs, then baseline -> candidate"
    )
    for i in e.instances:
        wins = sum(g > TIE for g in i.gains)
        losses = sum(g < -TIE for g in i.gains)
        b, c = _side_line(i.baseline), _side_line(i.candidate)
        pairs = ", ".join(
            f"{metric} {x} -> {y}" for metric, x, y in zip(METRICS, b, c, strict=True)
        )
        lines.append(
            f"  {i.name}: {i.gain:+.3%} ({wins}/{len(i.gains) - wins - losses}/{losses}); {pairs}"
        )
    outcomes = [i.outcome for i in e.instances]
    lines.append(
        f"overall: mean gain {statistics.fmean(e.gains):+.3%} over {len(e.gains)} pairs; "
        f"p = {e.p_better:.3g} against better, {e.p_worse:.3g} against worse (Wilcoxon); "
        f"instances {outcomes.count('better')} better, {outcomes.count('same')} same, "
        f"{outcomes.count('worse')} worse; mean worsening {e.worsening:.3%} "
        f"(at most {WORSENING_LIMIT:.0%} for better)"
    )
    lines.append(f"verdict: {e.verdict.upper()}")
    return "\n".join(lines)


def describe_bench(project: Project) -> str:
    """What bench_list shows: the budget, the instances, and the latest evaluations.

    Args:
        project: The project.

    Returns:
        The text.
    """
    spec = load_spec(project)
    lines = [f"runs {spec.runs} per instance, seed {spec.seed}, budget per run {stop_of(spec)}"]
    for split in ("train", "validation", "test"):
        entries = instances_of(spec, split)
        names = ", ".join(f"{i.name} ({i.source})" for i in entries) or "none"
        lines.append(f"{split}: {names}")
    known = best_known(project)
    if known:
        found = ", ".join(f"{n} {b['objective']:g} ({b['source']})" for n, b in known.items())
        lines.append(f"best known: {found}")
    past = history(project)
    if past:
        lines.append("evaluations:")
        kept = kept_revisions(project, past) | adopted_revisions(project, past)
        for r in past[-20:]:
            gain = f"{r['gain']:+.3%}" if r.get("gain") is not None else "-"
            note = r["candidate"].get("note")
            solved = f", kept as revision {kept[r['id']]}" if r["id"] in kept else ""
            lines.append(
                f"  {r['id']}: {r['candidate']['where']} vs {r['baseline']['where']} on "
                f"{r['split']}: {r['verdict']} (gain {gain}{solved})"
                + (f" - {note}" if note else "")
            )
    return "\n".join(lines)


def kept_revisions(project: Project, records: list[dict[str, Any]]) -> dict[int, int]:
    """The later revision each evaluation of the work files was kept as, if any.

    That is the first revision after its baseline whose files are the candidate's: the change was
    solved into it, as the agent does with a better one.

    Args:
        project: The project.
        records: The evaluations' records.

    Returns:
        The revision, by evaluation number, for the evaluations kept as one.
    """
    hashes = {rev: file_hashes(project.rev_dir(rev)) for rev in project.revisions()}
    kept = {}
    for r in records:
        if r["candidate"]["rev"] is not None or r["baseline"]["rev"] is None:
            continue
        files = r["candidate"]["files"]
        later = (rev for rev in hashes if rev > r["baseline"]["rev"] and hashes[rev] == files)
        rev = next(later, None)
        if rev is not None:
            kept[r["id"]] = rev
    return kept


def adopted_revisions(project: Project, records: list[dict[str, Any]]) -> dict[int, int]:
    """The revision each evaluation of a saved candidate was adopted as, if it was.

    Args:
        project: The project.
        records: The evaluations' records.

    Returns:
        The revision, by evaluation number.
    """
    adopted = {c["id"]: c["adopted"] for c in candidate_records(project) if c.get("adopted")}
    return {
        r["id"]: adopted[r["candidate"]["candidate_id"]]
        for r in records
        if r["candidate"].get("candidate_id") in adopted
    }


def latest_evaluations(records: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """The latest evaluation of each saved candidate on train.

    Args:
        records: The evaluations' records, oldest first.

    Returns:
        The record, by candidate number.
    """
    return {
        r["candidate"]["candidate_id"]: r
        for r in records
        if r["candidate"].get("candidate_id") is not None and r["split"] == "train"
    }


def state(project: Project) -> BenchState:
    """What the GUI's Improve tab shows.

    Args:
        project: The project.

    Returns:
        The benchmark and every evaluation, tuning and profile on it.
    """
    past = history(project)
    kept = kept_revisions(project, past) | adopted_revisions(project, past)
    judged = latest_evaluations(past)
    evaluations = [
        BenchEvaluation(
            id=r["id"],
            split=r["split"],
            candidate=_side_of(r["candidate"]),
            baseline=_side_of(r["baseline"]),
            note=r["candidate"].get("note", ""),
            verdict=r["verdict"],
            gain=r["gain"],
            worsening=r["worsening"],
            p_better=r["p_better"],
            p_worse=r["p_worse"],
            detail=r["error"] or (r["reference"] if r["verdict"] == "rejected" else None),
            instances=[
                BenchInstanceResult(
                    name=i["name"],
                    gain=i["gain"],
                    outcome=i["outcome"],
                    baseline=statistics.fmean(run["best_objective"] for run in i["baseline"]),
                    candidate=statistics.fmean(run["best_objective"] for run in i["candidate"]),
                )
                for i in r["instances"]
            ],
            kept=kept.get(r["id"]),
        )
        for r in past
    ]
    raced = [_tuning(t) for t in tunings(project)]
    profiled = [_profile(p) for p in profiles(project)]
    return BenchState(
        spec=load_spec(project),
        evaluations=evaluations,
        tunings=raced,
        profiles=profiled,
        candidates=[_candidate(c, judged.get(c["id"])) for c in candidate_records(project)],
        races=[_race(r) for r in races(project)],
        best=[
            BenchBest(name=name, objective=b["objective"], source=b["source"])
            for name, b in best_known(project).items()
        ],
    )


def _candidate(record: dict[str, Any], evaluation: dict[str, Any] | None) -> BenchCandidate:
    """A saved candidate as the Improve tab's ledger shows it.

    Args:
        record: The candidate's record as kept on disk.
        evaluation: Its latest evaluation's record, if it was judged.

    Returns:
        The candidate.
    """
    return BenchCandidate(
        id=record["id"],
        baseline_rev=record["baseline_rev"],
        family=record["family"],
        hypothesis=record["hypothesis"],
        evidence=record.get("evidence", ""),
        variant=record["variant"],
        evaluation=evaluation["id"] if evaluation else None,
        verdict=evaluation["verdict"] if evaluation else None,
        gain=evaluation["gain"] if evaluation else None,
        adopted=record.get("adopted"),
        lesson=record.get("lesson", ""),
    )


def _race(record: dict[str, Any]) -> BenchRace:
    """A race's record as the Improve tab shows it.

    Args:
        record: The record as kept on disk.

    Returns:
        The race.
    """
    return BenchRace(
        id=record["id"],
        baseline=_side_of(record["baseline"]),
        baseline_rank=record["baseline_rank"],
        p=record["p"],
        entries=[BenchRaceEntry(**e) for e in record["entries"]],
        winner=record["winner"],
    )


def _tuning(record: dict[str, Any]) -> BenchTuning:
    """A tuning's record as the Improve tab shows it.

    Args:
        record: The record as kept on disk.

    Returns:
        The tuning.
    """
    settings = record["settings"]
    best = next((s for s in settings if s["id"] == record["best"]), None)
    changed = best is not None and best["id"] != 0
    return BenchTuning(
        id=record["id"],
        rev=record["rev"],
        variants=record["variants"],
        used=record["used"],
        budget=record["budget"],
        settings=len(settings),
        eliminated=sum(1 for s in settings if s["eliminated"]),
        failed=sum(1 for s in settings if s["error"]),
        best=best["values"] if changed else None,
        best_variant=best["variant"] if changed and len(record["variants"]) > 1 else None,
        validation=record["validation"],
        signs=record["signs"],
    )


def _profile(record: dict[str, Any]) -> BenchProfile:
    """A profile's record as the Improve tab shows it.

    Args:
        record: The record as kept on disk.

    Returns:
        The profile.
    """
    return BenchProfile(
        id=record["id"],
        rev=record["rev"],
        split=record["split"],
        instances=record["instances"],
        fractions=record["fractions"],
        p=record["p"],
        variants=[
            BenchProfileVariant(
                label=v["label"],
                error=v["error"],
                mean_rank=v.get("mean_rank"),
                p_vs_best=v.get("p_vs_best"),
                wins=v.get("wins", 0),
                anytime=v.get("anytime", []),
                best_found_at=v.get("best_found_at"),
                iterations_per_sec=v.get("iterations_per_sec"),
                accepted=v.get("accepted"),
            )
            for v in record["variants"]
        ],
        readings=record["readings"],
    )


def _side_of(record: dict[str, Any]) -> BenchSide:
    """A side of an evaluation's record as the Improve tab shows it.

    Args:
        record: The record as kept on disk.

    Returns:
        The side.
    """
    return BenchSide(
        where=record["where"],
        rev=record["rev"],
        variant=record["variant"],
        worker=record["worker"],
        candidate_id=record.get("candidate_id"),
    )
