"""Profiling heuristics on the benchmark before composing them (docs/adr/0015).

The agent puts the heuristics worth considering as variants of solve.json; ``profile`` runs each
on every instance of a split with the benchmark's runs, seeds and budget, as an evaluation does,
and says how each behaves rather than only which wins:

- **ranks**: a Friedman test over the runs, an instance and a seed each, and Conover's comparison
  of each heuristic with the best, as a race (tune.py) has them.
- **anytime**: how far each heuristic's best so far is from the best any of them found on the
  instance, at a tenth, a quarter, half and the end of the budget, read from its runs'
  trajectories. A heuristic that leads early and one that ends best are what a ``Sequential``
  joins.
- **per instance**: which heuristic wins where; when the best ones differ by instance, one alone
  may not fit them all.
- **what a run did**: iterations per second, the share of moves accepted, and how far into the
  budget its best was found, which says whether a search stalls or ends early, as a descent does
  at its local optimum.

``readings`` turns that into compositions worth trying, for the agent to write as variants and
race with ``tune``. They are hints, as tune's signs are, not verdicts: the race and the
evaluation on validation still decide.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from dataclasses import dataclass, field
from typing import Any

from optopus_studio import bench
from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import RunFinished
from optopus_studio.tune import ALPHA, EARLY, friedman

# The shares of the budget the anytime profile reads the best so far at.
FRACTIONS = (0.1, 0.25, 0.5, 1.0)
# What readings() reads into a profile. Like tune's thresholds, these are this studio's proposals
# (docs/adr/0015): the share of instances on which a heuristic must lead early for that to count
# as its trait, and the gap, relative to the instance's best, by which it must lead there.
MAJORITY = 2 / 3
LEAD = 1e-3


@dataclass
class Profiled:
    """One heuristic's runs, by instance name, or why it failed."""

    label: str
    runs: dict[str, list[RunFinished]] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Profile:
    id: int
    rev: int | None
    split: bench.Split
    spec: bench.BenchSpec
    worker: str
    where: str
    instances: list[str]
    profiled: list[Profiled]
    higher_is_better: bool = False
    readings: list[str] = field(default_factory=list)

    @property
    def alive(self) -> list[Profiled]:
        return [p for p in self.profiled if p.error is None]

    def score(self, objective: float) -> float:
        return -objective if self.higher_is_better else objective

    def reference(self, instance: str) -> float:
        """The best score any heuristic reached on ``instance``."""
        return min(self.score(r.best_objective) for p in self.alive for r in p.runs[instance])

    def best_so_far(self, run: RunFinished, fraction: float) -> float:
        """The run's best score once ``fraction`` of the budget was spent: by time when the
        budget has one, by iterations otherwise."""
        if self.spec.max_duration_secs is not None:
            limit, at = fraction * self.spec.max_duration_secs, 0
        else:
            assert self.spec.max_iteration is not None
            limit, at = fraction * self.spec.max_iteration, 1
        best = self.score(run.initial_objective)
        for point in run.trajectory:
            if point[at] <= limit * (1 + bench.TIE):
                best = min(best, self.score(point[2]))
        if fraction >= 1:
            best = min(best, self.score(run.best_objective))
        return best

    def gap(self, p: Profiled, instance: str, fraction: float) -> float:
        """The mean distance of ``p``'s best so far from the instance's best, relative to it."""
        ref = self.reference(instance)
        scale = max(abs(ref), bench.TIE)
        return statistics.fmean(
            (self.best_so_far(r, fraction) - ref) / scale for r in p.runs[instance]
        )

    def anytime(self, p: Profiled) -> list[float]:
        return [
            statistics.fmean(self.gap(p, i, fraction) for i in self.instances)
            for fraction in FRACTIONS
        ]

    def ranks(self) -> tuple[float, dict[str, float], dict[str, float]]:
        """The Friedman p-value over the runs (an instance and a seed each), each heuristic's mean
        rank, and its p-value against the best by Conover's comparison."""
        alive = self.alive
        blocks = [
            [self.score(p.runs[i][k].best_objective) for p in alive]
            for i in self.instances
            for k in range(self.spec.runs)
        ]
        p, sums, compared = friedman(blocks)
        return (
            p,
            {a.label: s / len(blocks) for a, s in zip(alive, sums, strict=True)},
            {a.label: q for a, q in zip(alive, compared, strict=True)},
        )

    def found_at(self, p: Profiled) -> float | None:
        """The mean share of the budget spent when a run of ``p`` found its best: by time when
        the budget has one, by iterations otherwise."""
        if self.spec.max_duration_secs is not None:
            budget, shares = (
                self.spec.max_duration_secs,
                [r.time_to_best_secs for i in self.instances for r in p.runs[i]],
            )
        else:
            assert self.spec.max_iteration is not None
            budget, shares = (
                self.spec.max_iteration,
                [r.best_iteration for i in self.instances for r in p.runs[i]],
            )
        return min(1.0, statistics.fmean(shares) / budget) if shares else None

    def mean(self, p: Profiled, instance: str) -> float:
        return statistics.fmean(self.score(r.best_objective) for r in p.runs[instance])

    def winners(self) -> dict[str, str]:
        """The heuristic with the best mean on each instance."""
        return {
            i: min(self.alive, key=lambda p, i=i: self.mean(p, i)).label for i in self.instances
        }

    def to_json(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": self.id,
            "rev": self.rev,
            "where": self.where,
            "split": self.split,
            "worker": self.worker,
            "spec": self.spec.model_dump(mode="json"),
            "higher_is_better": self.higher_is_better,
            "instances": self.instances,
            "fractions": list(FRACTIONS),
            "p": None,
            "variants": [],
            "readings": self.readings,
        }
        if not self.alive:
            return record
        p, mean_ranks, compared = self.ranks()
        winners = self.winners()
        record["p"] = p
        for v in self.profiled:
            entry: dict[str, Any] = {"label": v.label, "error": v.error}
            if v.error is None:
                runs = [r for i in self.instances for r in v.runs[i]]
                entry |= {
                    "mean_rank": mean_ranks[v.label],
                    "p_vs_best": compared[v.label],
                    "wins": sum(1 for w in winners.values() if w == v.label),
                    "anytime": self.anytime(v),
                    "best_found_at": self.found_at(v),
                    "iterations_per_sec": bench.speed(runs),
                    "accepted": bench.acceptance(runs),
                    "objectives": {
                        i: [r.best_objective for r in v.runs[i]] for i in self.instances
                    },
                }
            record["variants"].append(entry)
        return record


async def profile(
    project: Project,
    rev: int | None = None,
    variants: list[str] | None = None,
    split: bench.Split = "train",
    progress: bench.Progress | None = None,
) -> Profile:
    """Runs each of ``variants`` (every variant by default) of revision ``rev``, or of the work
    files, on the instances of ``split``, and keeps the record in ``bench/profiles``."""
    spec = bench.load_spec(project)
    entries = bench.instances_of(spec, split)
    if not entries:
        raise ProjectError(f"the benchmark has no {split} instances; add some with bench_add")
    where = "the work files" if rev is None else f"revision {rev}"
    root = project.work if rev is None else project.rev_dir(rev)
    if not variants:
        try:
            solve = json.loads((root / "solve.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProjectError(f"{where} has no solve.json to profile: {exc}") from exc
        variants = [v.label for v in variants_of(solve)]
    first = await bench.side(root, variants[0], where)
    if len(set(variants)) < len(variants):
        raise ProjectError(f"a variant is named twice in {variants}")
    sides = [
        dataclasses.replace(first, variant=bench.pick_variant(first.solve, label, where))
        for label in variants
    ]
    if len(sides) < 2:
        raise ProjectError(
            f"{where} has one heuristic; put the ones to profile as variants of solve.json "
            '("heuristics")'
        )
    data = [(entry, bench.read_instance(project, entry)) for entry in entries]
    result = Profile(
        id=bench.next_id(bench.profiles_dir(project)),
        rev=rev,
        split=split,
        spec=spec,
        worker=first.worker,
        where=where,
        instances=[entry.name for entry, _ in data],
        profiled=[Profiled(label) for label in variants],
    )
    pairs = [(entry, p) for entry, _ in data for p in result.profiled]
    jobs = [(s, bench.request_for(s, instance, spec)) for _, instance in data for s in sides]
    summaries = await bench.solve_all(jobs, "profile", progress)
    for (entry, p), summary in zip(pairs, summaries, strict=True):
        if summary.error:
            error = summary.error
            if error.stage not in ("heuristic", "run"):
                raise ProjectError(
                    f"{where} fails on {entry.name!r} at {error.stage}: {error.message}"
                )
            p.error = p.error or f"{error.stage}: {error.message}"
            continue
        result.higher_is_better = bool(summary.higher_is_better)
        p.runs[entry.name] = summary.runs
    if not result.alive:
        raise ProjectError(f"every heuristic failed; the first: {result.profiled[0].error}")
    result.readings = readings(result)
    bench.keep_record(bench.profiles_dir(project), result.id, result.to_json())
    return result


# --- what the agent reads ----------------------------------------------------------------------


def readings(t: Profile) -> list[str]:
    """Compositions the profile suggests, each with what in the runs suggests it: hints for the
    agent's next variants, not verdicts."""
    alive = t.alive
    if len(alive) < 2:
        return []
    found = []
    p, mean_ranks, compared = t.ranks()
    leader = min(alive, key=lambda v: mean_ranks[v.label])
    if p >= ALPHA:
        found.append(
            f"the heuristics cannot be told apart (Friedman p = {p:.2g}): which one matters less "
            "here than the neighborhood, the delta or the worker; compose only after changing "
            "those, or raise the budget if every run ends at the same objective"
        )

    for fraction in FRACTIONS[:-1]:
        early = min(alive, key=lambda v, f=fraction: _mean_gap(t, v, f))
        if early is leader:
            continue
        ahead = sum(
            1 for i in t.instances if t.gap(leader, i, fraction) - t.gap(early, i, fraction) >= LEAD
        )
        if ahead >= MAJORITY * len(t.instances):
            found.append(
                f"{early.label} leads at {fraction:.0%} of the budget (gap "
                f"{gap_text(_mean_gap(t, early, fraction))} vs "
                f"{gap_text(_mean_gap(t, leader, fraction))}, ahead by {LEAD:.1%} or more on "
                f"{ahead} of {len(t.instances)} instances) but {leader.label} ends best: try "
                f"Sequential [{early.label}, {leader.label}], each step with a stop of its own, "
                "and tune the steps' shares (steps.0.stop.max_duration_secs or max_iteration) "
                "with the rest"
            )
            break

    for v in alive:
        if compared[v.label] < ALPHA:
            continue
        at = t.found_at(v)
        if at is not None and at < EARLY:
            found.append(
                f"{v.label} finds its best {at:.0%} into the budget on average and stalls or "
                "stops after: try it inside Iterated (as the search, a short RandomWalk as the "
                "perturbation) or Restart, or VariableNeighborhoodSearch with shakes of growing "
                "length"
            )

    winners = t.winners()
    if len(set(winners.values())) > 1:
        margins = {
            i: (t.mean(leader, i) - min(t.mean(v, i) for v in alive))
            / max(abs(t.mean(leader, i)), bench.TIE)
            for i in t.instances
        }
        if max(margins.values()) >= bench.WORSENING_LIMIT:
            shown = ", ".join(f"{i} {w}" for i, w in winners.items())
            found.append(
                f"instances prefer different heuristics ({shown}), by over "
                f"{bench.WORSENING_LIMIT:.0%} on some: one may not fit them all; try one that "
                "adapts within a run (ReinforcementLearningSearch, or "
                "AdaptiveLargeNeighborhoodSearch where the problem has ruin methods), a "
                "Sequential of the winners, and tell the user which kinds of instance prefer which"
            )
    return found


def gap_text(gap: float) -> str:
    """A gap as a percentage, to three significant digits: the gaps that matter can be tiny."""
    return f"{gap * 100:.3g}%"


def _mean_gap(t: Profile, v: Profiled, fraction: float) -> float:
    return statistics.fmean(t.gap(v, i, fraction) for i in t.instances)


def report(t: Profile) -> str:
    budget = bench.describe_budget(t.spec)
    lines = [
        f"profile {t.id}: {len(t.profiled)} heuristics of {t.where} ({t.worker} worker) on "
        f"{len(t.instances)} {t.split} instances, {t.spec.runs} runs each of {budget}",
    ]
    record = t.to_json()
    lines.append(
        f"Friedman p = {record['p']:.2g}; per heuristic, best first: mean rank (p against the "
        "best), instances won, gap to the best found at "
        + "/".join(f"{f:.0%}" for f in FRACTIONS)
        + " of the budget, how far into the budget its best was found, iterations/s, moves "
        "accepted"
    )
    ranked = sorted(
        (v for v in record["variants"] if v["error"] is None), key=lambda v: v["mean_rank"]
    )
    for v in ranked:
        anytime = "/".join(gap_text(g) for g in v["anytime"])
        found = "?" if v["best_found_at"] is None else f"{v['best_found_at']:.0%}"
        accepted = "?" if v["accepted"] is None else f"{v['accepted']:.0%}"
        lines.append(
            f"  {v['label']}: rank {v['mean_rank']:.2f} (p {v['p_vs_best']:.2g}), won "
            f"{v['wins']}/{len(t.instances)}, gap {anytime}, best at {found}, "
            f"{v['iterations_per_sec']:,.0f} it/s, {accepted} accepted"
        )
    for v in record["variants"]:
        if v["error"] is not None:
            lines.append(f"  {v['label']} failed: {v['error']}")
    if t.readings:
        lines.append("readings, compositions worth racing rather than verdicts:")
        lines += [f"  - {r}" for r in t.readings]
    lines.append(
        "Write the compositions as variants of solve.json, run_solver, and tune them with "
        "'spaces' alongside the best of these."
    )
    return "\n".join(lines)


def describe(project: Project) -> list[str]:
    """A line per profile, for bench_list."""
    lines = []
    for r in bench.profiles(project)[-10:]:
        ranked = sorted(
            (v for v in r["variants"] if v["error"] is None), key=lambda v: v["mean_rank"]
        )
        order = ", ".join(v["label"] for v in ranked)
        readings = f"; readings: {len(r['readings'])}" if r.get("readings") else ""
        lines.append(f"  {r['id']}: {r['where']} on {r['split']}, best first: {order}{readings}")
    return lines
