"""Diagnosing a search on the benchmark: evidence for the next hypothesis (docs/adr/0020).

An evaluation says whether a change is better, a profile how heuristics compare. Neither says
what to change. ``diagnose`` runs one heuristic of a revision (or of the work files) on a
split, through ``probe.py``, and reads what the runs show:

- **the gap** of each instance's runs to the best solution known on it (bench.py), and which
  instances are furthest: the failure set.
- **the spread**: whether the runs of an instance end at one objective or at several. When every
  run of every instance ends at the best known, the benchmark cannot tell a better search from
  this one, and that is said first.
- **probes**: whether a short descent in each neighborhood still improves the runs' best
  solutions, which names a neighborhood the search leaves unused or unfinished.
- **calls**, for a problem written in Python: where a run's time goes among the neighborhoods'
  methods and the objective, and how many of the moves priced would improve.
- **terms**: what the model's optional ``explain`` says the best solutions' objectives are made
  of, on the failure set and on the rest.

``readings`` turns these into sentences, each ending with the kind of change it suggests. They
are hints for the agent's next candidates, as a tuning's signs and a profile's readings are.
Nothing here judges: no verdict reads a diagnosis.
"""

from __future__ import annotations

import asyncio
import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from optopus_studio import bench
from optopus_studio.probe import neighbors_of
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import (
    BenchDiagnosis,
    BenchDiagnosisInstance,
    ProbeRequest,
    SolveRequest,
)
from optopus_studio.runner import run_probe
from optopus_studio.solving import initial_solution, solve_timeout

# What readings() reads into a diagnosis. Like tune's and profiling's thresholds, these are this
# studio's proposals (docs/adr/0020).
# The relative gap to the best known above which an instance is in the failure set.
FAR = bench.WORSENING_LIMIT
# The share of the budget below which a best found means the search stalls.
EARLY = 0.25
# The share of a run's time above which a method is where the time goes.
HEAVY = 0.5
# The share of priced moves that would improve below which a neighborhood is mostly wasted.
WASTED = 0.01
# Objectives this close, relative to their size, are one objective.
SAME = 1e-9


@dataclass
class Probed:
    """What the probe found on one instance.

    Attributes:
        name: The instance's name.
        shape: The sizes of the instance's lists and dicts, in words.
        answer: The probe's answer (probe.py).
        known: The best objective known on the instance, if it ranks as the runs' do.
        known_source: What found it.
    """

    name: str
    shape: str
    answer: dict[str, Any]
    known: float | None = None
    known_source: str = ""

    @property
    def runs(self) -> list[dict[str, Any]]:
        """The probe's runs."""
        return self.answer["runs"]


@dataclass
class Diagnosis:
    """A diagnosis of one heuristic on a split, and what it reads from the runs.

    Attributes:
        id: The diagnosis's number among the project's; 0 until it is kept.
        rev: The revision diagnosed, or None for the work files.
        where: Whose files ran, in words.
        variant: The heuristic's label.
        heuristic: The heuristic's dict, as solve.json has it.
        split: The instances it ran on.
        spec: The benchmark's runs, seed and budget.
        instances: What the probe found on each instance.
        higher_is_better: The direction the objectives are ranked in.
        native: Whether the problem is one of optopus's own, which cannot be counted.
        readings: What the runs suggest.
    """

    id: int
    rev: int | None
    where: str
    variant: str
    heuristic: dict[str, Any]
    split: bench.Split
    spec: bench.BenchSpec
    instances: list[Probed] = field(default_factory=list)
    higher_is_better: bool = False
    native: bool = False
    readings: list[str] = field(default_factory=list)

    def score(self, objective: float) -> float:
        """An objective on a scale where lower is better.

        Args:
            objective: The objective.

        Returns:
            The objective, negated when higher is better.
        """
        return -objective if self.higher_is_better else objective

    def scores(self, p: Probed) -> list[float]:
        """The scores of an instance's runs.

        Args:
            p: The instance.

        Returns:
            Each run's best objective, on the scale where lower is better.
        """
        return [self.score(r["best_objective"]) for r in p.runs]

    def reference(self, p: Probed) -> float:
        """The best score known on an instance: the best known, or the runs' own best.

        Args:
            p: The instance.

        Returns:
            The score.
        """
        own = min(self.scores(p))
        return own if p.known is None else min(own, self.score(p.known))

    def gap(self, p: Probed) -> float:
        """The mean distance of an instance's runs from the best known, relative to it.

        Args:
            p: The instance.

        Returns:
            The gap; 0 when every run reached the best known.
        """
        ref = self.reference(p)
        return (statistics.fmean(self.scores(p)) - ref) / max(abs(ref), bench.TIE)

    def distinct(self, p: Probed) -> int:
        """How many different objectives an instance's runs ended at.

        Args:
            p: The instance.

        Returns:
            The number.
        """
        seen: list[float] = []
        for s in self.scores(p):
            if not any(math.isclose(s, t, rel_tol=SAME, abs_tol=SAME) for t in seen):
                seen.append(s)
        return len(seen)

    def found_at(self, run: dict[str, Any]) -> float:
        """The share of its budget a run had spent when it found its best.

        The budget is read as a profile reads it: iterations when the run spent them or the
        budget has no time, the time otherwise.

        Args:
            run: The run.

        Returns:
            The share.
        """
        iterations, seconds = self.spec.max_iteration, self.spec.max_duration_secs
        if iterations is not None and (seconds is None or run["iterations"] >= iterations):
            return min(1.0, run["best_iteration"] / iterations)
        assert seconds is not None
        return min(1.0, run["time_to_best_secs"] / seconds)

    def stall(self) -> float:
        """The mean share of the budget at which the runs found their best.

        Returns:
            The share.
        """
        return statistics.fmean(self.found_at(r) for p in self.instances for r in p.runs)

    def probes(self) -> dict[str, tuple[int, int, float]]:
        """What a short descent in each neighborhood still gained from the runs' best solutions.

        Returns:
            By neighborhood: the runs it improved, the runs probed, and the mean gain over the
            runs probed, relative to each run's best.
        """
        found: dict[str, list[float]] = {}
        for p in self.instances:
            for run in p.runs:
                best = self.score(run["best_objective"])
                for name, after in run["probes"].items():
                    gain = (best - self.score(after)) / max(abs(best), bench.TIE)
                    found.setdefault(name, []).append(gain if gain > SAME else 0.0)
        return {
            name: (sum(1 for g in gains if g > 0), len(gains), statistics.fmean(gains))
            for name, gains in found.items()
        }

    def calls(self) -> dict[str, Any] | None:
        """Where the counted runs' time went, over the instances.

        Returns:
            The runs' iterations and seconds, the seconds and calls of the objective and of each
            neighborhood's methods, and each neighborhood's deltas and how many would improve;
            None for a problem that cannot be counted.
        """
        counted = [p.answer["calls"] for p in self.instances if p.answer.get("calls")]
        if not counted:
            return None
        total: dict[str, Any] = {
            "iterations": sum(c["iterations"] for c in counted),
            "seconds": sum(c["seconds"] for c in counted),
            "objective": [sum(c["objective"][i] for c in counted) for i in (0, 1)],
            "methods": {},
            "deltas": {},
        }
        for c in counted:
            for name, n in c["neighborhoods"].items():
                for method, (count, seconds) in n["calls"].items():
                    entry = total["methods"].setdefault(f"{name}.{method}", [0, 0.0])
                    entry[0] += count
                    entry[1] += seconds
                deltas = total["deltas"].setdefault(name, [0, 0])
                deltas[0] += n["deltas"]
                deltas[1] += n["improving"]
        return total

    def terms(self, names: set[str]) -> dict[str, float]:
        """The mean of each term of the objective over the best solutions of some instances.

        Args:
            names: The instances' names.

        Returns:
            Each term's mean; empty when the model explains nothing.
        """
        values: dict[str, list[float]] = {}
        for p in self.instances:
            if p.name not in names:
                continue
            for run in p.runs:
                for term, value in (run["terms"] or {}).items():
                    values.setdefault(term, []).append(value)
        return {term: statistics.fmean(v) for term, v in values.items()}

    def failures(self) -> list[Probed]:
        """The instances whose runs end furthest from the best known, the furthest first.

        Returns:
            Those more than ``FAR`` away.
        """
        far = [p for p in self.instances if self.gap(p) > FAR]
        return sorted(far, key=self.gap, reverse=True)

    def to_json(self) -> dict[str, Any]:
        """The diagnosis's record, as kept in ``bench/diagnoses``.

        Returns:
            The record, its runs without their solutions.
        """
        return {
            "id": self.id,
            "rev": self.rev,
            "where": self.where,
            "variant": self.variant,
            "split": self.split,
            "spec": self.spec.model_dump(mode="json"),
            "higher_is_better": self.higher_is_better,
            "native": self.native,
            "stall": self.stall(),
            "probes": {name: list(found) for name, found in self.probes().items()},
            "calls": self.calls(),
            "instances": [
                {
                    "name": p.name,
                    "shape": p.shape,
                    "mean": statistics.fmean(r["best_objective"] for r in p.runs),
                    "best": self.score(min(self.scores(p))),
                    "known": p.known,
                    "known_source": p.known_source,
                    "gap": self.gap(p),
                    "distinct": self.distinct(p),
                    "runs": [{k: v for k, v in r.items() if k != "solution"} for r in p.runs],
                }
                for p in self.instances
            ],
            "readings": self.readings,
        }


def shape_of(instance: dict[str, Any]) -> str:
    """The sizes of an instance's lists and dicts, in words.

    Args:
        instance: The instance.

    Returns:
        Such as "tasks 40, workers 5".
    """
    sized = [(k, len(v)) for k, v in instance.items() if isinstance(v, list | dict)]
    return ", ".join(f"{k} {n}" for k, n in sized)


async def diagnose(
    project: Project,
    rev: int | None = None,
    variant: str | None = None,
    split: bench.Split = "train",
    neighbors: list[str] | None = None,
    progress: bench.Progress | None = None,
) -> Diagnosis:
    """Diagnoses one heuristic on a split's instances and keeps the record in ``bench/diagnoses``.

    Args:
        project: The project.
        rev: The revision whose heuristic runs, or None for the work files.
        variant: The heuristic's label; None when solve.json has only one.
        split: The instances to run on.
        neighbors: The neighborhoods to probe; the problem's own, or the heuristic's, when None.
        progress: Called as instances finish, if given.

    Returns:
        The diagnosis.

    Raises:
        ProjectError: The split has no instances, the files cannot run, or the probe fails.
    """
    spec = bench.load_spec(project)
    entries = bench.instances_of(spec, split)
    if not entries:
        raise ProjectError(f"the benchmark has no {split} instances; add some with bench_add")
    where = "the work files" if rev is None else f"revision {rev}"
    root = project.work if rev is None else project.rev_dir(rev)
    side = await bench.side(root, variant, where)
    heuristic = bench.budgeted(side.variant, spec).heuristic
    known = bench.best_known(project)
    result = Diagnosis(
        id=0,
        rev=rev,
        where=where,
        variant=side.variant.label,
        heuristic=side.variant.heuristic,
        split=split,
        spec=spec,
    )
    gate = asyncio.Semaphore(bench.parallelism())
    done = 0

    async def probe(entry: bench.BenchInstance) -> Probed:
        """Probes the heuristic on one instance.

        Args:
            entry: The instance's entry in the spec.

        Returns:
            What the probe found.

        Raises:
            ProjectError: The probe fails.
        """
        nonlocal done
        instance = bench.read_instance(project, entry)
        request = ProbeRequest(
            model_path=str(side.root / "model.py"),
            instance=instance,
            heuristic=heuristic,
            runs=spec.runs,
            seed=spec.seed,
            neighbors=neighbors or [],
            initial_solution=initial_solution(side.solve, instance),
        )
        # The runs, the counted one, and a moment for each probe.
        solve = SolveRequest(
            model_path=request.model_path,
            instance={},
            variants=[side.variant.model_copy(update={"heuristic": heuristic})],
            runs=spec.runs + 1,
        )
        timeout = solve_timeout(solve) + spec.runs * 5.0
        async with gate:
            try:
                answer = await run_probe(request, side.root, timeout)
            except (RuntimeError, OSError) as exc:
                raise ProjectError(f"{where} cannot be diagnosed on {entry.name!r}: {exc}") from exc
        done += 1
        if progress:
            await progress(bench.BenchProgress(task="diagnosis", done=done, total=len(entries)))
        return Probed(entry.name, shape_of(instance), answer)

    result.instances = await bench.all_of([probe(entry) for entry in entries])
    first = result.instances[0].answer
    result.higher_is_better, result.native = first["higher_is_better"], first["native"]
    for p in result.instances:
        best = known.get(p.name)
        if best is not None and best["higher_is_better"] == result.higher_is_better:
            p.known, p.known_source = best["objective"], best["source"]
    result.readings = readings(result)
    result.id = bench.next_id(bench.diagnoses_dir(project))
    bench.keep_record(bench.diagnoses_dir(project), result.id, result.to_json())
    return result


# --- what the agent reads ----------------------------------------------------------------------


def percent(value: float) -> str:
    """A share as a percentage, to three significant digits.

    Args:
        value: The share.

    Returns:
        The percentage.
    """
    return f"{value * 100:.3g}%"


def readings(d: Diagnosis) -> list[str]:
    """What the runs suggest, each with the kind of change it points to.

    They are hints for the agent's next candidates, not verdicts.

    Args:
        d: The diagnosis.

    Returns:
        The readings, as sentences.
    """
    found = []
    settled = [p for p in d.instances if d.distinct(p) == 1 and d.gap(p) <= SAME]
    if len(settled) == len(d.instances):
        found.append(
            "every run on every instance ends at the same objective, the best known there: the "
            "benchmark cannot tell a better search from this one, so further candidates will be "
            "judged SAME. Make it harder before trying more (larger or tighter instances from "
            "generate.py, or a smaller budget with bench_settings), or stop: the search may be "
            "at the optimum of these instances"
        )
        return found
    if settled:
        names = ", ".join(p.name for p in settled)
        found.append(
            f"on {names} every run ends at the best known objective: only the other instances "
            "can show a gain, and a candidate is judged on few pairs. Replace those with harder "
            "instances"
        )

    failures = d.failures()
    if failures:
        shown = ", ".join(
            f"{p.name} ({percent(d.gap(p))} from the best known"
            + (f", {p.known_source}" if p.known is not None else ", one of its own runs")
            + (f"; {p.shape}" if p.shape else "")
            + ")"
            for p in failures[:4]
        )
        found.append(
            f"the runs end furthest from the best known on {shown}: a better solution exists "
            "there and the search does not reach it reliably. Look at what sets these instances "
            "apart, and aim the next candidates at them [composition, neighborhood]"
        )
    spread = [p for p in d.instances if d.distinct(p) > 1]
    if len(spread) >= max(1, len(d.instances) // 2):
        found.append(
            f"the runs of {len(spread)} of {len(d.instances)} instances end at different "
            "objectives: they stop in different local optima. More starts within the budget "
            "(Restart), a kick out of each (Iterated), or a population that recombines them "
            "[composition]"
        )

    used = set(neighbors_of(d.heuristic))
    probes = d.probes()
    for name, (improved, probed, gain) in probes.items():
        if improved == 0:
            continue
        which = f"{improved} of {probed} best solutions (by {percent(gain)} on average)"
        if name in used:
            found.append(
                f"a short descent in {name}, a neighborhood the search uses, still improves "
                f"{which}: the search stops before it has finished with its own moves. End it "
                f"with a descent (a Sequential whose last step is LocalSearch on {name}), or "
                "cool or settle it sooner [composition, settings]"
            )
        else:
            found.append(
                f"a short descent in {name}, a neighborhood the search does not use, improves "
                f"{which}: add it to the search, as a step after the others (a descent over "
                "each neighborhood in turn) or as the kick's or a second heuristic's move "
                "[composition, heuristic]"
            )
    if probes and not any(improved for improved, _, _ in probes.values()) and spread:
        found.append(
            f"no descent in {', '.join(probes)} improves any best solution, yet the runs differ: "
            "they end in true local optima of every neighborhood there is. A larger move is "
            "needed to leave them: a new neighborhood in model.py (an exchange of two, a chain "
            "of moves), or a stronger kick [neighborhood, composition]"
        )

    stall = d.stall()
    if stall < EARLY:
        found.append(
            f"the runs find their best {stall:.0%} into the budget on average and nothing "
            "after: the rest of the budget is idle. Diversify (Iterated, Restart), or give the "
            "time to a slower schedule [composition, settings]"
        )

    calls = d.calls()
    if calls and calls["seconds"] > 0:
        seconds = calls["seconds"]
        rate = calls["iterations"] / seconds
        objective_share = calls["objective"][1] / seconds
        priced = any(method.endswith(".delta") for method in calls["methods"])
        if not priced and objective_share >= HEAVY / 2:
            found.append(
                f"the neighborhoods have no delta, so every move is priced by applying it and "
                f"calling objective(), {percent(objective_share)} of a run's time: give each "
                "neighborhood a delta computed from the move [delta]"
            )
        for method, (count, spent) in sorted(
            calls["methods"].items(), key=lambda item: -item[1][1]
        ):
            if spent / seconds >= HEAVY:
                found.append(
                    f"{method} takes {percent(spent / seconds)} of a run's time ({count:,} "
                    f"calls, {rate:,.0f} iterations per second while counted): make it cheaper "
                    "(price a move from what it touches, keep what it needs in the solution), "
                    "or enumerate fewer moves [delta, neighborhood]"
                )
                break
        for name, (deltas, improving) in calls["deltas"].items():
            if deltas >= 1000 and improving / deltas < WASTED:
                found.append(
                    f"{percent(improving / deltas)} of the {deltas:,} moves priced in {name} "
                    "would improve: most of the neighborhood is wasted on moves that cannot "
                    "help. Restrict it to the promising ones (moves that touch what is "
                    "violated or the largest term), or add a move that can [neighborhood]"
                )
        python = (calls["objective"][1] + sum(s for _, s in calls["methods"].values())) / seconds
        costly = any("[delta" in reading for reading in found)
        if python >= 0.8 and not costly:
            found.append(
                f"the model's Python takes {percent(python)} of a run's time at {rate:,.0f} "
                "iterations per second, with no method standing out: a port to Rust is what "
                "would make it search more [port]"
            )

    names = {p.name for p in failures}
    if names and len(names) < len(d.instances):
        hard = d.terms(names)
        easy = d.terms({p.name for p in d.instances} - names)
        apart = [
            f"{term} {hard[term]:.4g} against {easy.get(term, 0.0):.4g}"
            for term in hard
            if abs(hard[term]) > 2 * abs(easy.get(term, 0.0)) and abs(hard[term]) > SAME
        ]
        if apart:
            found.append(
                "explain() sets the failure set apart from the rest, on average per best "
                f"solution: {', '.join(apart)}. Aim a move at what makes that term "
                "[neighborhood]"
            )
    return found


def report(d: Diagnosis) -> str:
    """What the agent reads of a diagnosis.

    Args:
        d: The diagnosis.

    Returns:
        The report's text: each instance, the probes, the calls, the terms and the readings.
    """
    budget = bench.describe_budget(d.spec)
    lines = [
        f"diagnosis {d.id}: variant {d.variant} of {d.where} on {len(d.instances)} {d.split} "
        f"instances, {d.spec.runs} runs each of {budget}, run by model.py",
        "per instance: mean and best objective, the best known, the mean gap to it, and how "
        "many different objectives the runs ended at",
    ]
    for p in d.instances:
        objectives = [r["best_objective"] for r in p.runs]
        best = max(objectives) if d.higher_is_better else min(objectives)
        known = f"{p.known:g} ({p.known_source})" if p.known is not None else "none yet"
        lines.append(
            f"  {p.name}: mean {statistics.fmean(objectives):g}, best {best:g}, known {known}, "
            f"gap {percent(d.gap(p))}, {d.distinct(p)} objectives over {len(p.runs)} runs"
            + (f"; {p.shape}" if p.shape else "")
        )
    runs = [r for p in d.instances for r in p.runs]
    seconds = sum(r["total_time_secs"] for r in runs)
    rate = sum(r["iterations"] for r in runs) / seconds if seconds > 0 else 0.0
    accepted = sum(r["n_accepted"] or 0 for r in runs)
    moves = accepted + sum(r["n_rejected"] or 0 for r in runs)
    lines.append(
        f"runs: best found {d.stall():.0%} into the budget on average, {rate:,.0f} iterations "
        f"per second, {bench.share(accepted / moves if moves else None)} of moves accepted"
    )
    probes = d.probes()
    if probes:
        lines.append(
            "probes, a short descent from each run's best solution: "
            + "; ".join(
                f"{name} improves {improved} of {probed} (mean {percent(gain)})"
                for name, (improved, probed, gain) in probes.items()
            )
        )
    errors = {n: e for p in d.instances for n, e in p.answer["probe_errors"].items()}
    lines += [f"  cannot probe {name}: {error}" for name, error in errors.items()]
    calls = d.calls()
    if calls and calls["seconds"] > 0:
        seconds = calls["seconds"]
        parts = [
            f"objective {percent(calls['objective'][1] / seconds)} ({calls['objective'][0]:,})"
        ]
        parts += [
            f"{method} {percent(spent / seconds)} ({count:,})"
            for method, (count, spent) in sorted(
                calls["methods"].items(), key=lambda item: -item[1][1]
            )
            if count
        ]
        lines.append(
            "calls, share of a counted run's time (and calls) in the model's Python: "
            + ", ".join(parts)
        )
        priced = [
            f"{name} {percent(improving / deltas)} of {deltas:,}"
            for name, (deltas, improving) in calls["deltas"].items()
            if deltas
        ]
        if priced:
            lines.append("moves priced that would improve: " + ", ".join(priced))
    elif d.native:
        lines.append("calls: the problem is one of optopus's own, which runs compiled")
    terms = d.terms({p.name for p in d.instances})
    if terms:
        shown = ", ".join(f"{term} {value:.4g}" for term, value in terms.items())
        lines.append(f"explain(), mean per best solution: {shown}")
    explain_error = next(
        (p.answer["explain_error"] for p in d.instances if p.answer["explain_error"]), None
    )
    if explain_error:
        lines.append(f"explain() failed: {explain_error}")
    if d.readings:
        lines.append("readings, what to try next and of which family, as hints:")
        lines += [f"  - {r}" for r in d.readings]
    else:
        lines.append("readings: nothing stands out in these runs.")
    return "\n".join(lines)


def describe(project: Project) -> list[str]:
    """A line per diagnosis, for bench_list.

    Args:
        project: The project.

    Returns:
        The lines of the last five diagnoses.
    """
    return [
        f"  {r['id']}: variant {r['variant']} of {r['where']} on {r['split']}: "
        f"{len(r['readings'])} readings"
        for r in bench.diagnoses(project)[-5:]
    ]


def state(record: dict[str, Any]) -> BenchDiagnosis:
    """A diagnosis's record as the Improve tab shows it.

    Args:
        record: The record as kept on disk.

    Returns:
        The diagnosis.
    """
    return BenchDiagnosis(
        id=record["id"],
        rev=record["rev"],
        variant=record["variant"],
        split=record["split"],
        instances=[
            BenchDiagnosisInstance(
                name=i["name"],
                mean=i["mean"],
                known=i["known"],
                gap=i["gap"],
                distinct=i["distinct"],
                runs=len(i["runs"]),
            )
            for i in record["instances"]
        ],
        readings=record["readings"],
    )
