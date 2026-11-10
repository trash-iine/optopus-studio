"""Saved candidates, raced several at once against the incumbent (docs/adr/0018).

``evaluate`` (bench.py) judges one change at a time, and the work files hold only one. Here a
change becomes a *candidate*: ``save`` copies the work files that make the algorithm into
``bench/candidates/<n>/`` with the hypothesis they test, and puts the work files back to the
revision the candidate changes, so the next candidate starts from the same incumbent.

- **gates**: a candidate is refused before it runs when it is one already saved, changes nothing,
  does not build, or scores the incumbent's own solution otherwise than the incumbent does: it
  changed the objective, not the search.
- **race**: the candidates and the baseline revision solve the train instances with the same
  seeds and budget. The baseline runs once and every candidate is paired with it, so each gets
  the evaluation ``evaluate`` would have made of it (bench.compare), and a Friedman test ranks
  them all.
- **adopt**: only a candidate judged better than its baseline becomes the work files, to be
  solved into a revision; the caller solves it (agent.py).
- **ledger**: a candidate's record keeps its hypothesis, family and evidence, and the lesson the
  agent drew; its verdict is read from its evaluation, so the ledger cannot disagree with it.
"""

from __future__ import annotations

import json
import math
import shutil
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, get_args

from optopus_studio import bench
from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import EvaluateRequest, Family, RunSummary
from optopus_studio.runner import evaluate_solutions, worker_command
from optopus_studio.tune import friedman

FAMILIES: tuple[str, ...] = get_args(Family)
# A race's candidates: each adds a side to every instance's solves.
MAX_RACED = 8
# The incumbent's solutions a candidate's model scores before it may run.
GATE_SOLUTIONS = 3


def files_dir(project: Project, id: int) -> Path:
    """Where a candidate's files are kept.

    Args:
        project: The project.
        id: The candidate's number.

    Returns:
        The directory's path.
    """
    return bench.candidates_dir(project) / str(id)


def load(project: Project, id: int) -> dict[str, Any]:
    """A candidate's record.

    Args:
        project: The project.
        id: The candidate's number.

    Returns:
        The record.

    Raises:
        ProjectError: There is no such candidate.
    """
    path = bench.candidates_dir(project) / f"{id}.json"
    if not path.is_file():
        raise ProjectError(f"no candidate {id}; candidate_save makes one")
    return json.loads(path.read_text())


def _write(project: Project, record: dict[str, Any]) -> None:
    """Keeps a candidate's record.

    Args:
        project: The project.
        record: The record.
    """
    bench.keep_record(bench.candidates_dir(project), record["id"], record)


def where(id: int) -> str:
    """A candidate in words, as its evaluations name it.

    Args:
        id: The candidate's number.

    Returns:
        The words.
    """
    return f"candidate {id}"


async def save(
    project: Project,
    baseline_rev: int,
    hypothesis: str,
    family: str,
    evidence: str = "",
    variant: str | None = None,
) -> dict[str, Any]:
    """Saves the work files as a candidate, and makes them revision ``baseline_rev``'s again.

    Args:
        project: The project.
        baseline_rev: The revision the candidate changes, which it will be judged against.
        hypothesis: What it changes and why that should help.
        family: The kind of change, one of ``FAMILIES``.
        evidence: What suggested it.
        variant: The heuristic of its solve.json it runs; None when there is only one.

    Returns:
        The candidate's record.

    Raises:
        ProjectError: The candidate fails a gate; the work files are then left as they are.
    """
    if family not in FAMILIES:
        raise ProjectError(f"unknown family {family!r}; expected one of {list(FAMILIES)}")
    if not hypothesis.strip():
        raise ProjectError("say what the candidate changes and why it should help ('hypothesis')")
    base_dir = project.rev_dir(baseline_rev)
    id = bench.next_id(bench.candidates_dir(project))
    root = files_dir(project, id)
    for name in bench.ALGORITHM_FILES:
        if (project.work / name).is_file():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project.work / name, root / name)
    try:
        side = await bench.side(root, variant, "the work files")
        files = bench.file_hashes(root)
        for other in bench.candidate_records(project):
            if other["files"] == files and other["variant"] == side.variant.label:
                raise ProjectError(
                    f"these files are candidate {other['id']} already "
                    f"([{other['family']}] {other['hypothesis']}); bench_list shows what became "
                    "of it"
                )
        if files == bench.file_hashes(base_dir) and len(_variants(base_dir)) == 1:
            raise ProjectError(
                f"the work files are revision {baseline_rev}'s: there is no change to save"
            )
        await _check_objective(base_dir, baseline_rev, side)
    except ProjectError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    record = {
        "id": id,
        "baseline_rev": baseline_rev,
        "family": family,
        "hypothesis": hypothesis.strip(),
        "evidence": evidence.strip(),
        "variant": side.variant.label,
        "worker": side.worker,
        "files": files,
        "adopted": None,
        "lesson": "",
    }
    _write(project, record)
    project.restore(baseline_rev)
    return record


def _variants(root: Path) -> list[Any]:
    """The variants of the solve.json in a directory.

    Args:
        root: The directory.

    Returns:
        The variants; none when solve.json is missing or broken.
    """
    try:
        return variants_of(json.loads((root / "solve.json").read_text()))
    except (OSError, json.JSONDecodeError, ProjectError):
        return []


async def _check_objective(base_dir: Path, baseline_rev: int, side: bench.Side) -> None:
    """Checks that a candidate's model scores the baseline's solutions as the baseline did.

    A candidate that fails it would be rejected after its race; this refuses it before. A
    baseline that was not solved, or whose solve failed, has no solutions to check with.

    Args:
        base_dir: The baseline revision's directory.
        baseline_rev: The baseline revision.
        side: The candidate's side.

    Raises:
        ProjectError: The candidate's model cannot score a solution, or scores it otherwise.
    """
    result, instance = base_dir / "result.json", base_dir / "instance.json"
    if not result.is_file() or not instance.is_file():
        return
    summary = RunSummary.model_validate_json(result.read_text())
    if summary.error or not summary.runs:
        return
    runs = summary.runs[:GATE_SOLUTIONS]
    request = EvaluateRequest(
        model_path=str(side.root / "model.py"),
        instance=json.loads(instance.read_text()),
        solutions=[r.solution for r in runs],
        heuristic=side.variant.heuristic,
    )
    command = [str(side.binary)] if side.binary else worker_command()
    try:
        objectives = await evaluate_solutions(command, request, side.root)
    except (RuntimeError, OSError) as exc:
        raise ProjectError(
            f"the candidate's model cannot score the solutions of revision {baseline_rev}: {exc}. "
            "A candidate keeps what a solution means (encode_solution's form) and how the model "
            "is built"
        ) from exc
    for run, got in zip(runs, objectives, strict=True):
        if not math.isclose(run.best_objective, got, rel_tol=bench.AGREE, abs_tol=bench.AGREE):
            raise ProjectError(
                f"the candidate's model scores a solution of revision {baseline_rev} {got!r}, "
                f"which that revision scored {run.best_objective!r}: the candidate changes the "
                "objective, not only the search. Keep the objective, penalty weights included"
            )


# --- a race ------------------------------------------------------------------------------------


async def race(
    project: Project,
    ids: list[int],
    baseline_variant: str | None = None,
    progress: bench.Progress | None = None,
) -> tuple[dict[str, Any], list[bench.Evaluation]]:
    """Races candidates against the revision they change, on train, and keeps the race's record.

    Args:
        project: The project.
        ids: The candidates' numbers, which must all change the same revision.
        baseline_variant: The baseline's variant; None when its solve.json has only one.
        progress: Called as solves finish, if given.

    Returns:
        The race's record, and each candidate's evaluation in the order of ``ids``.

    Raises:
        ProjectError: The candidates cannot be raced together, or the baseline fails.
    """
    if not ids:
        raise ProjectError("name the candidates to race")
    if len(set(ids)) < len(ids):
        raise ProjectError(f"a candidate is named twice in {ids}")
    if len(ids) > MAX_RACED:
        raise ProjectError(f"a race takes up to {MAX_RACED} candidates, not {len(ids)}")
    records = [load(project, id) for id in ids]
    revs = sorted({r["baseline_rev"] for r in records})
    if len(revs) > 1:
        raise ProjectError(
            f"the candidates change different revisions ({revs}); race those of one revision, "
            "the incumbent's"
        )
    rev = revs[0]
    base = bench.Contender(
        await bench.side(project.rev_dir(rev), baseline_variant, f"revision {rev}"),
        f"revision {rev}",
        rev,
    )
    contenders = [
        bench.Contender(
            await bench.side(files_dir(project, r["id"]), r["variant"], where(r["id"])),
            where(r["id"]),
            note=f"[{r['family']}] {r['hypothesis']}",
            candidate_id=r["id"],
        )
        for r in records
    ]
    evaluations = await bench.compare(project, base, contenders, "train", "race", progress)

    judged = [e for e in evaluations if e.judged]
    p, base_rank, mean_ranks = _ranks(judged)
    better = [e for e in judged if e.verdict == "better"]
    winner = min(better, key=lambda e: mean_ranks[e.id], default=None)
    record = {
        "id": bench.next_id(bench.races_dir(project)),
        "baseline": base.describe(),
        "baseline_rank": base_rank,
        "p": p,
        "entries": [
            {
                "candidate": id,
                "evaluation": e.id,
                "verdict": e.verdict,
                "gain": statistics.fmean(e.gains) if e.judged else None,
                "mean_rank": mean_ranks.get(e.id),
            }
            for id, e in zip(ids, evaluations, strict=True)
        ],
        "winner": winner.candidate["candidate_id"] if winner else None,
    }
    bench.keep_record(bench.races_dir(project), record["id"], record)
    return record, evaluations


def _ranks(judged: list[bench.Evaluation]) -> tuple[float | None, float | None, dict[int, float]]:
    """The baseline's and the judged candidates' mean ranks over the runs of a race.

    Args:
        judged: The evaluations of the candidates that were judged, which share the baseline's
            runs.

    Returns:
        The Friedman p-value, the baseline's mean rank, and each candidate's by its evaluation's
        number; None and nothing when no candidate was judged.
    """
    if not judged:
        return None, None, {}
    sign = -1.0 if judged[0].instances[0].higher_is_better else 1.0
    blocks = [
        [
            sign * judged[0].instances[n].baseline[k].best_objective,
            *(sign * e.instances[n].candidate[k].best_objective for e in judged),
        ]
        for n in range(len(judged[0].instances))
        for k in range(len(judged[0].instances[n].baseline))
    ]
    p, sums, _ = friedman(blocks)
    means = [s / len(blocks) for s in sums]
    return p, means[0], {e.id: m for e, m in zip(judged, means[1:], strict=True)}


def report(project: Project, record: dict[str, Any], evaluations: list[bench.Evaluation]) -> str:
    """What the agent reads of a race.

    Args:
        project: The project.
        record: The race's record.
        evaluations: Each candidate's evaluation, in the record's order.

    Returns:
        The report's text: the ranks, each candidate's evaluation, and what to do next.
    """
    base = record["baseline"]
    spec = evaluations[0].spec
    lines = [
        f"race {record['id']}: {len(evaluations)} candidates against {base['where']} (variant "
        f"{base['variant']}, {base['worker']} worker) on train: {spec.runs} runs per instance, "
        f"{bench.describe_budget(spec)} each, seed {spec.seed}"
    ]
    if record["p"] is not None:
        ranked = sorted(
            (e for e in record["entries"] if e["mean_rank"] is not None),
            key=lambda e: e["mean_rank"],
        )
        ranks = ", ".join(f"{where(e['candidate'])} {e['mean_rank']:.2f}" for e in ranked)
        lines.append(
            f"mean rank over the runs, 1 the best (Friedman p = {record['p']:.2g}): "
            f"{base['where']} {record['baseline_rank']:.2f}, {ranks}"
        )
    for entry, evaluation in zip(record["entries"], evaluations, strict=True):
        saved = load(project, entry["candidate"])
        lines.append(f"{where(saved['id'])} [{saved['family']}] {saved['hypothesis']}")
        # The evaluation's own report, without the line that repeats the setup.
        lines += [f"  {line}" for line in bench.report(evaluation).splitlines()[1:]]
    if record["winner"] is not None:
        lines.append(
            f"winner: {where(record['winner'])}. adopt it, which solves it into the new "
            "incumbent; save the next candidates on that revision."
        )
    else:
        lines.append(
            "no candidate is better than the baseline: none can be adopted. Give each a lesson "
            "(candidate_lesson), and read the instance lines for the next hypotheses."
        )
    return "\n".join(lines)


# --- adopting ----------------------------------------------------------------------------------


def adoptable(project: Project, id: int) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """A candidate that may be adopted, with its latest evaluation on train.

    Args:
        project: The project.
        id: The candidate's number.

    Returns:
        The candidate's record and its evaluation's, or None when it was not judged yet.

    Raises:
        ProjectError: The candidate was adopted already, its baseline is no longer the
            incumbent, or it was judged and is not better.
    """
    record = load(project, id)
    if record["adopted"]:
        raise ProjectError(f"candidate {id} is revision {record['adopted']} already")
    for other in bench.candidate_records(project):
        if other["baseline_rev"] == record["baseline_rev"] and other["adopted"]:
            raise ProjectError(
                f"candidate {other['id']} was adopted on revision {record['baseline_rev']} as "
                f"revision {other['adopted']}, which is the incumbent now: candidate {id} was "
                "judged against the old one. Make its change on the incumbent, save it and race "
                "it again"
            )
    evaluation = bench.latest_evaluations(bench.history(project)).get(id)
    if evaluation is not None and evaluation["verdict"] != "better":
        raise ProjectError(
            f"candidate {id} was judged {evaluation['verdict'].upper()} against revision "
            f"{record['baseline_rev']} (evaluation {evaluation['id']}): only a BETTER candidate "
            "is adopted"
        )
    return record, evaluation


def write_adopted(project: Project, record: dict[str, Any]) -> None:
    """Makes the work files the candidate's: its baseline's files, with the candidate's algorithm.

    A candidate that ran one of several variants keeps only that one in solve.json: the race
    settled which to solve with.

    Args:
        project: The project.
        record: The candidate's record.
    """
    root = files_dir(project, record["id"])
    project.restore(record["baseline_rev"])
    for name in bench.ALGORITHM_FILES:
        if (root / name).is_file():
            (project.work / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, project.work / name)
        else:
            (project.work / name).unlink(missing_ok=True)
    solve = json.loads((root / "solve.json").read_text())
    if len(solve.get("heuristics") or []) > 1:
        chosen = bench.pick_variant(solve, record["variant"], where(record["id"]))
        del solve["heuristics"]
        solve["heuristic"] = chosen.heuristic
        project.write_file("solve.json", json.dumps(solve, indent=2))


def mark_adopted(project: Project, id: int, rev: int) -> None:
    """Records the revision a candidate was adopted as.

    Args:
        project: The project.
        id: The candidate's number.
        rev: The revision.
    """
    record = load(project, id)
    record["adopted"] = rev
    _write(project, record)


def set_lesson(project: Project, id: int, lesson: str) -> None:
    """Records what a candidate's result taught.

    Args:
        project: The project.
        id: The candidate's number.
        lesson: The lesson, in the agent's words.

    Raises:
        ProjectError: There is no such candidate.
    """
    record = load(project, id)
    record["lesson"] = lesson.strip()
    _write(project, record)


# --- the ledger --------------------------------------------------------------------------------


def describe(project: Project) -> list[str]:
    """The ledger, for bench_list: each candidate and what became of it, then the families.

    Args:
        project: The project.

    Returns:
        The lines; none when no candidate was saved.
    """
    records = bench.candidate_records(project)
    if not records:
        return []
    judged = bench.latest_evaluations(bench.history(project))
    lines = []
    for r in records[-30:]:
        evaluation = judged.get(r["id"])
        if r["adopted"]:
            outcome = f"adopted as revision {r['adopted']}"
        elif evaluation is None:
            outcome = "not raced yet"
        else:
            outcome = evaluation["verdict"]
        if evaluation is not None and evaluation.get("gain") is not None:
            outcome += f" (gain {evaluation['gain']:+.3%})"
        lesson = f" | lesson: {r['lesson']}" if r["lesson"] else ""
        lines.append(
            f"  {r['id']} [{r['family']}] on revision {r['baseline_rev']}: {outcome} - "
            f"{r['hypothesis']}{lesson}"
        )
    tried = Counter(r["family"] for r in records)
    adopted = Counter(r["family"] for r in records if r["adopted"])
    counts = ", ".join(
        f"{f} {tried[f]}" + (f" ({adopted[f]} adopted)" if adopted[f] else "")
        for f in FAMILIES
        if tried[f]
    )
    untried = [f for f in FAMILIES if not tried[f]]
    lines.append(
        f"  families tried: {counts}" + (f"; not yet: {', '.join(untried)}" if untried else "")
    )
    return lines
