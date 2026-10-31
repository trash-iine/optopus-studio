"""Judging a change of the algorithm on a benchmark of instances (docs/adr/0013).

``bench/bench.json`` lists the instances (``bench/instances/<name>.json``), each in the train or
the validation split, and the budget each run gets. ``evaluate`` solves every instance of a split
with a candidate (the project's work files, or a revision) and a baseline revision, each run of
one side from the same seed as the same run of the other, and compares them:

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
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import (
    BenchEvaluation,
    BenchInstance,
    BenchInstanceResult,
    BenchSide,
    BenchSpec,
    BenchState,
    EvaluateRequest,
    RunFinished,
    RunSummary,
    SolveRequest,
    Variant,
    Verdict,
)
from optopus_studio.runner import evaluate_solutions, run_solve, worker_command
from optopus_studio.solving import initial_solution, rust_binary, solve_timeout

ALPHA = 0.05
# The mean relative worsening over the instances a "better" candidate may have.
WORSENING_LIMIT = 0.01
# A relative difference this small is a tie.
TIE = 1e-9
# Up to this many pairs the signed-rank test is exact, beyond it a normal approximation.
EXACT_PAIRS = 200

Split = Literal["train", "validation", "all"]
# Told how far an evaluation has got: the task, then done of total.
Progress = Callable[[Literal["evaluation"], int, int], Awaitable[None]]


# --- the benchmark on disk ---------------------------------------------------------------------


def spec_path(project: Project) -> Path:
    return project.bench / "bench.json"


def instance_path(project: Project, name: str) -> Path:
    return project.bench / "instances" / f"{name}.json"


def load_spec(project: Project) -> BenchSpec:
    path = spec_path(project)
    if not path.is_file():
        return BenchSpec()
    return BenchSpec.model_validate_json(path.read_text())


def save_spec(project: Project, spec: BenchSpec) -> None:
    project.bench.mkdir(exist_ok=True)
    spec_path(project).write_text(spec.model_dump_json(indent=2))


def configure(project: Project, **settings: Any) -> BenchSpec:
    """Changes the runs, seed or budget of every later evaluation."""
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
    """Stores ``instance`` under ``name``, replacing an instance of that name."""
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
    spec = load_spec(project)
    if not any(i.name == name for i in spec.instances):
        raise ProjectError(f"no benchmark instance {name!r}")
    spec.instances = [i for i in spec.instances if i.name != name]
    save_spec(project, spec)
    instance_path(project, name).unlink(missing_ok=True)


def read_instance(project: Project, entry: BenchInstance) -> dict[str, Any]:
    path = instance_path(project, entry.name)
    if not path.is_file():
        raise ProjectError(f"the file of benchmark instance {entry.name!r} is missing")
    text = path.read_text()
    if _sha256(text) != entry.sha256:
        raise ProjectError(f"benchmark instance {entry.name!r} changed since it was added")
    return json.loads(text)


def instances_of(spec: BenchSpec, split: Split) -> list[BenchInstance]:
    return [i for i in spec.instances if split == "all" or i.split == split]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- the two sides -----------------------------------------------------------------------------


@dataclass
class Side:
    """What one side of an evaluation solves with."""

    name: str
    root: Path
    solve: dict[str, Any]
    variant: Variant
    binary: Path | None

    @property
    def worker(self) -> str:
        return "rust" if self.binary else "python"


def pick_variant(solve: dict[str, Any], label: str | None, where: str) -> Variant:
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


async def side(name: str, root: Path, label: str | None, where: str) -> Side:
    if not (root / "solve.json").is_file() or not (root / "model.py").is_file():
        raise ProjectError(f"{where} has no model.py and solve.json to evaluate")
    try:
        solve = json.loads((root / "solve.json").read_text())
    except json.JSONDecodeError as exc:
        raise ProjectError(f"the solve.json of {where} is not JSON: {exc}") from exc
    main_rs = root / "rust" / "main.rs"
    binary = await rust_binary(solve, main_rs.read_text() if main_rs.is_file() else None)
    return Side(name, root, solve, pick_variant(solve, label, where), binary)


def budgeted(variant: Variant, spec: BenchSpec) -> Variant:
    """The variant with the benchmark's budget as its stop, whatever stop it had."""
    stop = {
        key: value
        for key, value in (
            ("max_duration_secs", spec.max_duration_secs),
            ("max_iteration", spec.max_iteration),
        )
        if value is not None
    }
    return Variant(label=variant.label, heuristic={**variant.heuristic, "stop": stop})


def request_for(s: Side, instance: dict[str, Any], spec: BenchSpec) -> SolveRequest:
    return SolveRequest(
        model_path=str(s.root / "model.py"),
        instance=instance,
        variants=[budgeted(s.variant, spec)],
        runs=spec.runs,
        seed=spec.seed,
        initial_solution=initial_solution(s.solve, instance),
    )


def parallelism() -> int:
    configured = os.environ.get("OPTOPUS_STUDIO_BENCH_PARALLEL")
    if configured:
        return max(1, int(configured))
    # Runs on a time budget are compared by what they reach in that time, so leave cores free.
    return max(1, (os.cpu_count() or 2) // 2)


# --- statistics --------------------------------------------------------------------------------


def wilcoxon(diffs: list[float]) -> tuple[float, float]:
    """One-sided p-values of the Wilcoxon signed-rank test that the differences center on 0,
    against "greater" and against "less". Zeros are dropped; tied magnitudes share a rank."""
    d = [x for x in diffs if abs(x) > TIE]
    n = len(d)
    if n == 0:
        return 1.0, 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    ties: list[int] = []
    i = 0
    while i < n:
        j = i
        while j + 1 < n and math.isclose(abs(d[order[j + 1]]), abs(d[order[i]]), rel_tol=1e-12):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        ties.append(j - i + 1)
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d, strict=True) if x > 0)
    if n <= EXACT_PAIRS:
        # Doubled ranks are integers; count how many sign patterns reach each rank sum.
        doubled = [round(2 * r) for r in ranks]
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
    name: str
    sha256: str
    baseline: list[RunFinished]
    candidate: list[RunFinished]
    higher_is_better: bool
    gains: list[float] = field(init=False)

    def __post_init__(self) -> None:
        sign = -1.0 if self.higher_is_better else 1.0
        base = [r.best_objective for r in self.baseline]
        scale = max(abs(statistics.fmean(base)), TIE)
        self.gains = [
            sign * (b.best_objective - c.best_objective) / scale
            for b, c in zip(self.baseline, self.candidate, strict=True)
        ]

    @property
    def gain(self) -> float:
        return statistics.fmean(self.gains)

    @property
    def outcome(self) -> Literal["better", "same", "worse"]:
        if self.gain > TIE:
            return "better"
        return "worse" if self.gain < -TIE else "same"


@dataclass
class Evaluation:
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
        return [g for i in self.instances for g in i.gains]

    @property
    def judged(self) -> bool:
        return self.verdict not in ("rejected", "failed")

    @property
    def worsening(self) -> float:
        if not self.instances:
            return 0.0
        return statistics.fmean(max(0.0, -i.gain) for i in self.instances)

    def judge(self) -> None:
        self.p_better, self.p_worse = wilcoxon(self.gains)
        if self.p_better < ALPHA:
            self.verdict = "better" if self.worsening <= WORSENING_LIMIT else "mixed"
        elif self.p_worse < ALPHA:
            self.verdict = "worse"
        else:
            self.verdict = "same"

    def to_json(self) -> dict[str, Any]:
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
                    "baseline": [
                        r.model_dump(mode="json", exclude={"solution"}) for r in i.baseline
                    ],
                    "candidate": [
                        r.model_dump(mode="json", exclude={"solution"}) for r in i.candidate
                    ],
                }
                for i in self.instances
            ],
        }


def results_dir(project: Project) -> Path:
    return project.bench / "results"


def history(project: Project) -> list[dict[str, Any]]:
    """Every evaluation's result, oldest first."""
    return _records(results_dir(project))


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir():
        return []
    files = sorted((p for p in path.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    return [json.loads(p.read_text()) for p in files]


def next_id(path: Path) -> int:
    ids = [int(p.stem) for p in path.glob("*.json") if p.stem.isdigit()] if path.is_dir() else []
    return max(ids, default=0) + 1


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
    """Compares a candidate with a baseline revision on a split of the benchmark, and keeps the
    result in ``bench/results``."""
    spec = load_spec(project)
    entries = instances_of(spec, split)
    if not entries:
        raise ProjectError(f"the benchmark has no {split} instances; add some with bench_add")
    base_where = f"revision {baseline_rev}"
    cand_where = "the work files" if candidate_rev is None else f"revision {candidate_rev}"
    cand_root = project.work if candidate_rev is None else project.rev_dir(candidate_rev)
    base = await side("baseline", project.rev_dir(baseline_rev), baseline_variant, base_where)
    cand = await side("candidate", cand_root, variant, cand_where)
    data = [(entry, read_instance(project, entry)) for entry in entries]

    evaluation = Evaluation(
        id=next_id(results_dir(project)),
        split=split,
        spec=spec,
        candidate={**_describe_side(cand, cand_where, candidate_rev), "note": note},
        baseline=_describe_side(base, base_where, baseline_rev),
    )
    try:
        requests = [
            (s, entry, request_for(s, inst, spec)) for entry, inst in data for s in (base, cand)
        ]
    except ProjectError as exc:
        evaluation.error = str(exc)
        return _keep(project, evaluation)

    gate = asyncio.Semaphore(parallelism())
    done = 0

    async def ignore(_: RunSummary) -> None:
        pass

    async def solve(s: Side, request: SolveRequest) -> RunSummary:
        nonlocal done
        async with gate:
            summary = await run_solve(
                request, 0, s.root, ignore, solve_timeout(request), rust_binary=s.binary
            )
        done += 1
        if progress:
            await progress("evaluation", done, len(requests))
        return summary

    # Interleaved, so both sides run under the same load.
    summaries = await asyncio.gather(*(solve(s, request) for s, _, request in requests))
    by_side: dict[tuple[str, str], RunSummary] = {
        (s.name, entry.name): summary
        for (s, entry, _), summary in zip(requests, summaries, strict=True)
    }
    for entry, _ in data:
        b, c = by_side[("baseline", entry.name)], by_side[("candidate", entry.name)]
        if b.error:
            raise ProjectError(
                f"{base_where} fails on {entry.name!r} at {b.error.stage}: {b.error.message}"
            )
        if c.error:
            evaluation.error = (
                f"{cand_where} fails on {entry.name!r} at {c.error.stage}: {c.error.message}"
            )
            return _keep(project, evaluation)
        if b.higher_is_better != c.higher_is_better:
            evaluation.verdict = "rejected"
            evaluation.reference = (
                f"the candidate ranks its objective the other way on {entry.name!r}: "
                f"higher_is_better is {c.higher_is_better}, the baseline's {b.higher_is_better}"
            )
            return _keep(project, evaluation)
        evaluation.instances.append(
            InstanceResult(entry.name, entry.sha256, b.runs, c.runs, bool(b.higher_is_better))
        )

    problem = await _check_reference(base, data, evaluation)
    if problem:
        evaluation.verdict = "rejected"
        evaluation.reference = problem
        return _keep(project, evaluation)
    solutions = sum(len(i.candidate) for i in evaluation.instances)
    evaluation.reference = (
        f"the baseline's model scores all {solutions} of the candidate's solutions as the "
        "candidate does"
    )
    evaluation.judge()
    return _keep(project, evaluation)


async def _check_reference(
    base: Side, data: list[tuple[BenchInstance, dict[str, Any]]], evaluation: Evaluation
) -> str | None:
    """Why the baseline's model does not agree with the candidate's objectives, if it does not."""
    command = [str(base.binary)] if base.binary else worker_command()
    for (entry, instance), result in zip(data, evaluation.instances, strict=True):
        request = EvaluateRequest(
            model_path=str(base.root / "model.py"),
            instance=instance,
            solutions=[r.solution for r in result.candidate],
            heuristic=base.variant.heuristic,
        )
        try:
            objectives = await evaluate_solutions(command, request, base.root)
        except (RuntimeError, OSError) as exc:
            return (
                f"the baseline's model cannot score the candidate's solutions on "
                f"{entry.name!r}: {exc}"
            )
        for run, got in zip(result.candidate, objectives, strict=True):
            if not math.isclose(run.best_objective, got, rel_tol=1e-9, abs_tol=1e-9):
                return (
                    f"on {entry.name!r} the candidate reports {run.best_objective!r} for the best "
                    f"solution of its run {run.run}, which the baseline's model scores {got!r}: "
                    "the candidate changed the objective, not only the search"
                )
    return None


def _describe_side(s: Side, where: str, rev: int | None) -> dict[str, Any]:
    files = {
        name: _sha256((s.root / name).read_text())
        for name in ("model.py", "solve.json", "rust/main.rs")
        if (s.root / name).is_file()
    }
    return {
        "where": where,
        "rev": rev,
        "variant": s.variant.label,
        "worker": s.worker,
        "files": files,
    }


def _keep(project: Project, evaluation: Evaluation) -> Evaluation:
    path = results_dir(project)
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{evaluation.id}.json").write_text(json.dumps(evaluation.to_json(), indent=1))
    return evaluation


# --- what the agent reads ----------------------------------------------------------------------


def _rate(runs: list[RunFinished]) -> float:
    seconds = sum(r.total_time_secs for r in runs)
    return sum(r.iterations for r in runs) / seconds if seconds > 0 else 0.0


def _accepted(runs: list[RunFinished]) -> str:
    counts = [(r.n_accepted, r.n_rejected) for r in runs]
    if any(a is None or b is None for a, b in counts):
        return "?"
    moves = sum(a + b for a, b in counts)  # type: ignore[operator]
    return f"{sum(a for a, _ in counts) / moves:.0%}" if moves else "?"  # type: ignore[misc]


# What each side's runs on an instance show, baseline -> candidate.
METRICS = ("mean objective", "iterations/s", "time to best", "accepted")


def _side_line(runs: list[RunFinished]) -> tuple[str, ...]:
    values = [r.best_objective for r in runs]
    return (
        f"{statistics.fmean(values):g}",
        f"{_rate(runs):,.0f}",
        f"{statistics.fmean(r.time_to_best_secs for r in runs):.3g}s",
        _accepted(runs),
    )


def describe_budget(spec: BenchSpec) -> str:
    return " or ".join(
        part
        for part in (
            f"{spec.max_duration_secs:g}s" if spec.max_duration_secs else "",
            f"{spec.max_iteration} iterations" if spec.max_iteration else "",
        )
        if part
    )


def report(evaluation: Evaluation) -> str:
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
    spec = load_spec(project)
    budget = {
        k: v
        for k, v in (
            ("max_duration_secs", spec.max_duration_secs),
            ("max_iteration", spec.max_iteration),
        )
        if v is not None
    }
    lines = [f"runs {spec.runs} per instance, seed {spec.seed}, budget per run {budget}"]
    for split in ("train", "validation"):
        entries = instances_of(spec, split)
        names = ", ".join(f"{i.name} ({i.source})" for i in entries) or "none"
        lines.append(f"{split}: {names}")
    past = history(project)
    if past:
        lines.append("evaluations:")
        kept = kept_revisions(project, past)
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


# The files a side's record hashes: what makes a candidate the same as a revision.
ALGORITHM_FILES = ("model.py", "solve.json", "rust/main.rs")


def kept_revisions(project: Project, records: list[dict[str, Any]]) -> dict[int, int]:
    """For each evaluation of the work files, the first revision after its baseline whose files
    are the candidate's: the change was solved into it, as the agent does with a better one."""
    hashes: dict[int, dict[str, str]] = {}
    for rev in project.revisions():
        root = project.rev_dir(rev)
        hashes[rev] = {
            name: _sha256((root / name).read_text())
            for name in ALGORITHM_FILES
            if (root / name).is_file()
        }
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


def state(project: Project) -> BenchState:
    """What the GUI's Improve tab shows."""
    past = history(project)
    kept = kept_revisions(project, past)
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
    return BenchState(spec=load_spec(project), evaluations=evaluations)


def _side_of(record: dict[str, Any]) -> BenchSide:
    return BenchSide(
        where=record["where"], rev=record["rev"], variant=record["variant"], worker=record["worker"]
    )
