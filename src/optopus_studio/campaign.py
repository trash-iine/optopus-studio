"""An improvement campaign: the studio drives the rounds, the agent fills them (docs/adr/0019).

Left to a prompt, the loop that improves the search runs inside one turn of the agent, which
decides alone when it has tried enough, and is asked in prose to check the result and to undo
what does not hold. A campaign moves the loop's skeleton into the studio:

- **state**: ``bench/campaign.json`` holds the revision the campaign started from, the incumbent,
  the budget (rounds, minutes or both), the rounds without a gain, and a line per round.
- **rounds**: ``step`` is called after each turn of the agent. While the campaign runs it
  returns the next round's *brief*: where the campaign stands, the ledger of what was tried
  (candidates.py), the latest hints, and what a round is. The agent's session gives the agent
  a turn on it (agent.py), so a round is a turn.
- **the incumbent** moves only on evidence: a candidate that was adopted, or a change judged
  better against the incumbent and then solved into a revision. ``step`` reads that from the
  records; the agent is not asked.
- **the end** is the studio's: when the budget is spent, when ``PATIENCE`` rounds in a row
  brought nothing, or when the user stops it, the studio itself evaluates the incumbent against
  the revision the campaign started from on validation. It keeps the incumbent only on
  "better", and otherwise makes the work files the starting revision's again. A kept result is
  then measured on the test split, if there is one. The agent gets one last turn, to tell the
  user.
"""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optopus_studio import bench, candidates
from optopus_studio.projects import Project, ProjectError, variants_of
from optopus_studio.protocol import BenchCampaign, BenchCheck

# Rounds in a row without a new incumbent after which a campaign ends.
PATIENCE = 3
MAX_ROUNDS = 50
DEFAULT_ROUNDS = 5
# The paired runs below which a signed-rank test cannot reach 5% even when every pair gains.
MIN_PAIRS = 5
# The families that change how the search is built, after which its settings are tuned anew.
STRUCTURAL = ("heuristic", "composition", "neighborhood", "delta", "representation", "port")
# How the brief and the chat mark a message as the studio's.
MARK = "[studio]"


@dataclass
class Step:
    """What follows a turn of the agent while a campaign runs.

    Attributes:
        text: The studio's message, shown in the chat.
        turn: Whether the agent takes a turn on it.
    """

    text: str
    turn: bool


def path(project: Project) -> Path:
    """Where the campaign's state is kept.

    Args:
        project: The project.

    Returns:
        The path of ``bench/campaign.json``.
    """
    return project.bench / "campaign.json"


def load(project: Project) -> dict[str, Any] | None:
    """The project's latest campaign, if it had one.

    Args:
        project: The project.

    Returns:
        The campaign's state, or None.
    """
    file = path(project)
    return json.loads(file.read_text()) if file.is_file() else None


def _save(project: Project, state: dict[str, Any]) -> None:
    """Keeps the campaign's state.

    Args:
        project: The project.
        state: The state.
    """
    project.bench.mkdir(exist_ok=True)
    path(project).write_text(json.dumps(state, indent=1))


def active(state: dict[str, Any] | None) -> bool:
    """Whether a campaign still has rounds or its end ahead.

    Args:
        state: The campaign's state, or None.

    Returns:
        Whether it is running, being stopped, or waiting for its summary.
    """
    return state is not None and state["status"] in ("running", "stopping", "summarizing")


def start(project: Project, rounds: int | None = None, minutes: float | None = None) -> dict:
    """Starts a campaign from the revision the work files are.

    Args:
        project: The project.
        rounds: The rounds it may take; ``DEFAULT_ROUNDS`` when neither budget is given.
        minutes: The minutes it may take, checked between rounds.

    Returns:
        The campaign's state.

    Raises:
        ProjectError: A campaign is running, the benchmark lacks a split, or the work files are
            not a revision with one heuristic.
    """
    if active(load(project)):
        raise ProjectError("a campaign is running already; it ends on its own, or when stopped")
    if rounds is None and minutes is None:
        rounds = DEFAULT_ROUNDS
    if rounds is not None and not 1 <= rounds <= MAX_ROUNDS:
        raise ProjectError(f"a campaign takes 1 to {MAX_ROUNDS} rounds, not {rounds}")
    if minutes is not None and minutes <= 0:
        raise ProjectError("the minutes must be positive")
    spec = bench.load_spec(project)
    for split in ("train", "validation"):
        if not bench.instances_of(spec, split):
            raise ProjectError(
                f"the benchmark has no {split} instances: build it first (bench_add), train to "
                "choose on and validation to check the result on"
            )
    pairs = len(bench.instances_of(spec, "validation")) * spec.runs
    if pairs < MIN_PAIRS:
        raise ProjectError(
            f"the validation instances give {pairs} paired runs, and the final check needs "
            f"{MIN_PAIRS} or more to be able to say BETTER at all: add validation instances or "
            "raise the runs (bench_settings)"
        )
    files = bench.file_hashes(project.work)
    rev = next(
        (
            r
            for r in reversed(project.revisions())
            if bench.file_hashes(project.rev_dir(r)) == files
        ),
        None,
    )
    if rev is None:
        raise ProjectError(
            "the project files are not a revision: run_solver first, so the campaign has an "
            "incumbent to start from and to come back to"
        )
    solve = json.loads((project.rev_dir(rev) / "solve.json").read_text())
    if len(variants_of(solve)) != 1:
        raise ProjectError(
            f"revision {rev} compares several heuristics: a campaign improves one. Keep the one "
            "to start from as solve.json's only heuristic, run_solver, and start again"
        )
    state = {
        "status": "running",
        "start_rev": rev,
        "incumbent_rev": rev,
        "rounds": rounds,
        "minutes": minutes,
        "patience": PATIENCE,
        "started_at": time.time(),
        "ended_at": None,
        "round": 0,
        "idle": 0,
        "log": [],
        "reason": None,
        "final": None,
    }
    _save(project, state)
    return state


def request_stop(project: Project) -> bool:
    """Asks a running campaign to end after the turn in progress.

    Args:
        project: The project.

    Returns:
        Whether a campaign was running.
    """
    state = load(project)
    if state is None or state["status"] != "running":
        return False
    state["status"] = "stopping"
    _save(project, state)
    return True


def abandon(project: Project) -> None:
    """Ends a campaign as it is, without its final check: the work files stay as they are.

    Args:
        project: The project.
    """
    state = load(project)
    if active(state):
        assert state is not None
        state["status"] = "stopped"
        state["reason"] = state["reason"] or "stopped before its final check"
        state["ended_at"] = time.time()
        _save(project, state)


def advance(project: Project, incumbent: int) -> int:
    """The incumbent now: the revision the evidence moved it to since ``incumbent``.

    It moves to a revision a candidate was adopted as, or one that holds the files of a change
    judged better against the incumbent (an evaluation, or a tuning's check), and so on from
    there.

    Args:
        project: The project.
        incumbent: The incumbent before.

    Returns:
        The incumbent's revision.
    """
    records = bench.history(project)
    kept = bench.kept_revisions(project, records) | bench.adopted_revisions(project, records)
    while True:
        moved = next(
            (
                kept[r["id"]]
                for r in records
                if r["verdict"] == "better"
                and r["baseline"]["rev"] == incumbent
                and kept.get(r["id"], 0) > incumbent
            ),
            None,
        )
        if moved is None:
            return incumbent
        incumbent = moved


def _elapsed(state: dict[str, Any]) -> float:
    """The minutes since the campaign started.

    Args:
        state: The campaign's state.

    Returns:
        The minutes, up to its end if it ended.
    """
    return ((state["ended_at"] or time.time()) - state["started_at"]) / 60


def _why_end(state: dict[str, Any]) -> str | None:
    """Why the campaign ends now, if it does.

    Args:
        state: The campaign's state, after its last round was read.

    Returns:
        The reason in words, or None to go on.
    """
    if state["status"] == "stopping":
        return "stopped by the user"
    if state["rounds"] is not None and state["round"] >= state["rounds"]:
        return f"its {state['rounds']} rounds are spent"
    if state["minutes"] is not None and _elapsed(state) >= state["minutes"]:
        return f"its {state['minutes']:g} minutes are spent"
    if state["idle"] >= state["patience"]:
        return f"{state['idle']} rounds in a row brought no better candidate"
    return None


async def step(project: Project, progress: bench.Progress | None = None) -> Step | None:
    """What follows the turn that just ended: the next round, the campaign's end, or nothing.

    Args:
        project: The project.
        progress: Called as the final check's solves finish, if given.

    Returns:
        The studio's message and whether the agent takes a turn on it; None when no campaign
        is under way.
    """
    state = load(project)
    if state is None or not active(state):
        return None
    if state["status"] == "summarizing":
        # The turn that just ended was the agent's summary.
        state["status"] = "finished"
        _save(project, state)
        return None
    before = state["incumbent_rev"]
    state["incumbent_rev"] = advance(project, before)
    if state["round"] > 0:
        state["log"][-1]["incumbent_after"] = state["incumbent_rev"]
        state["idle"] = 0 if state["incumbent_rev"] != before else state["idle"] + 1
    reason = _why_end(state)
    if reason is None:
        state["round"] += 1
        state["log"].append({"round": state["round"], "incumbent": state["incumbent_rev"]})
        _save(project, state)
        return Step(round_brief(project, state), turn=True)
    stopped = state["status"] == "stopping"
    state["reason"] = reason
    _save(project, state)
    await finish(project, state, progress)
    state["status"] = "stopped" if stopped else "summarizing"
    state["ended_at"] = time.time()
    _save(project, state)
    return Step(final_brief(project, state, summarize=not stopped), turn=not stopped)


async def finish(
    project: Project, state: dict[str, Any], progress: bench.Progress | None = None
) -> None:
    """Checks the incumbent against the starting revision, and keeps it or goes back.

    Sets ``state["final"]``: the check on validation, the measure on test, whether the incumbent
    was kept, and why the check could not be made if it could not. The work files become the
    kept revision's.

    Args:
        project: The project.
        state: The campaign's state.
        progress: Called as solves finish, if given.
    """
    start_rev, incumbent = state["start_rev"], state["incumbent_rev"]
    final: dict[str, Any] = {"validation": None, "test": None, "kept": False, "error": None}
    state["final"] = final
    if incumbent == start_rev:
        project.restore(start_rev)
        return
    note = f"campaign: revision {incumbent} against revision {start_rev}, where it started"
    try:
        checked = await bench.evaluate(
            project, start_rev, "validation", candidate_rev=incumbent, note=note, progress=progress
        )
        final["validation"] = _check(checked)
        final["kept"] = checked.verdict == "better"
        if final["kept"] and bench.instances_of(bench.load_spec(project), "test"):
            measured = await bench.evaluate(
                project, start_rev, "test", candidate_rev=incumbent, note=note, progress=progress
            )
            final["test"] = _check(measured)
    except ProjectError as exc:
        final["error"] = str(exc)
    project.restore(incumbent if final["kept"] else start_rev)


def _check(evaluation: bench.Evaluation) -> dict[str, Any]:
    """An evaluation as the campaign's state keeps it.

    Args:
        evaluation: The evaluation.

    Returns:
        Its number, verdict and mean gain.
    """
    return {
        "evaluation": evaluation.id,
        "verdict": evaluation.verdict,
        "gain": statistics.fmean(evaluation.gains) if evaluation.judged else None,
    }


# --- what the agent reads ----------------------------------------------------------------------


def _budget_left(state: dict[str, Any]) -> str:
    """What is left of the campaign's budget, in words.

    Args:
        state: The campaign's state.

    Returns:
        The rounds and minutes left.
    """
    parts = []
    if state["rounds"] is not None:
        parts.append(f"round {state['round']} of {state['rounds']}")
    else:
        parts.append(f"round {state['round']}")
    if state["minutes"] is not None:
        left = max(0.0, state["minutes"] - _elapsed(state))
        parts.append(f"about {left:.0f} of {state['minutes']:g} minutes left")
    return ", ".join(parts)


def _hints(project: Project, state: dict[str, Any]) -> list[str]:
    """What the records suggest for the round, as lines of the brief.

    Args:
        project: The project.
        state: The campaign's state.

    Returns:
        The lines.
    """
    incumbent = state["incumbent_rev"]
    lines = []
    profiles, tunings = bench.profiles(project), bench.tunings(project)
    if not profiles and state["round"] == 1:
        lines.append(
            "- No heuristics were profiled yet: choose the structure from evidence first (step 3 "
            'of "Improving the algorithm": recipes, profile, compose), then save the compositions '
            "worth it as candidates."
        )
    adopted = [c for c in bench.candidate_records(project) if c["adopted"] == incumbent]
    tuned = any(t["rev"] == incumbent for t in tunings)
    if adopted and adopted[-1]["family"] in STRUCTURAL and not tuned:
        lines.append(
            f"- Revision {incumbent} changed how the search is built "
            f"([{adopted[-1]['family']}]) and its settings were not tuned since: tune it first, "
            "so the next structures are compared with a tuned one."
        )
    if profiles and profiles[-1]["readings"]:
        lines.append(f"- Profile {profiles[-1]['id']} read:")
        lines += [f"    {r}" for r in profiles[-1]["readings"][:3]]
    if tunings and tunings[-1]["signs"]:
        lines.append(f"- Tuning {tunings[-1]['id']} showed:")
        lines += [f"    {s}" for s in tunings[-1]["signs"][:3]]
    return lines


def round_brief(project: Project, state: dict[str, Any]) -> str:
    """The brief of a round: where the campaign stands and what a round is.

    Args:
        project: The project.
        state: The campaign's state, the round already counted.

    Returns:
        The brief's text.
    """
    incumbent = state["incumbent_rev"]
    lines = [
        f"{MARK} Improvement campaign, {_budget_left(state)}. The incumbent is revision "
        f"{incumbent} (the campaign started from revision {state['start_rev']}); "
        f"{state['idle']} of the last rounds brought nothing, and the campaign ends after "
        f"{state['patience']} in a row.",
    ]
    ledger = candidates.describe(project)
    if ledger:
        lines.append("The ledger so far:")
        lines += ledger
    hints = _hints(project, state)
    if hints:
        lines.append("What the records suggest:")
        lines += hints
    lines += [
        "This round:",
        f"- Save three or four candidates on revision {incumbent} (candidate_save), each one "
        "change with its hypothesis, of different families, a family not tried before a third "
        "variation of one that lost. Read the instance lines, signs and readings for them.",
        "- race them, adopt the winner if there is one, and give the others a lesson "
        "(candidate_lesson). A tuning whose check on validation is BETTER is kept with "
        "run_solver.",
        "- Then end your turn with one line on what the round tried and found. Ask the user "
        "nothing and write no summary: the studio starts the next round, and at the end checks "
        "the result on validation itself.",
    ]
    return "\n".join(lines)


def _check_line(name: str, check: dict[str, Any] | None) -> str | None:
    """A check of the final result in words.

    Args:
        name: The split.
        check: The check as the state keeps it, or None.

    Returns:
        The line, or None when there was no check.
    """
    if check is None:
        return None
    # Rounded first, so a gain of rounding noise does not read as "-0.000%".
    gain = f", mean gain {round(check['gain'], 9) + 0.0:+.3%}" if check["gain"] is not None else ""
    return f"on {name}: {check['verdict'].upper()}{gain} (evaluation {check['evaluation']})"


def final_brief(project: Project, state: dict[str, Any], summarize: bool) -> str:
    """What the studio says when a campaign ends, and asks of the agent's last turn.

    Args:
        project: The project.
        state: The campaign's state, its final check made.
        summarize: Whether the agent is asked to tell the user.

    Returns:
        The text.
    """
    final, start_rev, incumbent = state["final"], state["start_rev"], state["incumbent_rev"]
    saved = [c for c in bench.candidate_records(project) if c["baseline_rev"] >= start_rev]
    lines = [
        f"{MARK} The campaign ended after {state['round']} rounds and {_elapsed(state):.0f} "
        f"minutes: {state['reason']}. {len(saved)} candidates were saved, "
        f"{sum(1 for c in saved if c['adopted'])} adopted."
    ]
    if incumbent == start_rev:
        lines.append(
            f"No change was better than revision {start_rev}: the files are that revision's."
        )
    elif final["error"]:
        lines.append(
            f"Revision {incumbent} could not be checked against revision {start_rev} "
            f"({final['error']}): the files are revision {start_rev}'s again."
        )
    else:
        lines.append(f"Final check of revision {incumbent} against revision {start_rev}:")
        lines += [
            f"- {line}"
            for line in (
                _check_line("validation", final["validation"]),
                _check_line("test, which nothing was chosen on", final["test"]),
            )
            if line
        ]
        if final["kept"]:
            lines.append(f"The improvement holds: the files are revision {incumbent}'s.")
        elif final["validation"]["verdict"] in ("failed", "rejected"):
            lines.append(
                f"Revision {incumbent} could not be judged on validation (bench_list shows why), "
                f"so it is not kept: the files are revision {start_rev}'s again."
            )
        else:
            lines.append(
                f"The improvement does not hold on validation, so it fit the train instances: "
                f"the files are revision {start_rev}'s again."
            )
    if summarize:
        lines.append(
            "Tell the user now, in their language and briefly: whether the search improved and "
            "by how much (the gains above, on instances no choice was made on), which changes "
            "got it there, what did not help and why (the lessons), and what more budget could "
            "try. Make no further change."
        )
    return "\n".join(lines)


def describe(project: Project) -> BenchCampaign | None:
    """The campaign as the Improve tab shows it.

    Args:
        project: The project.

    Returns:
        The campaign, or None when the project never had one.
    """
    state = load(project)
    if state is None:
        return None
    final = state["final"] or {}

    def check(name: str) -> BenchCheck | None:
        """One of the final checks.

        Args:
            name: ``validation`` or ``test``.

        Returns:
            The check, or None when it was not made.
        """
        return BenchCheck(**final[name]) if final.get(name) else None

    return BenchCampaign(
        status={"stopping": "running", "summarizing": "finished"}.get(
            state["status"], state["status"]
        ),
        start_rev=state["start_rev"],
        incumbent_rev=state["incumbent_rev"],
        round=state["round"],
        rounds=state["rounds"],
        minutes=state["minutes"],
        elapsed_minutes=_elapsed(state),
        idle=state["idle"],
        patience=state["patience"],
        reason=state["reason"],
        validation=check("validation"),
        test=check("test"),
        kept=final.get("kept") if state["final"] else None,
        error=final.get("error"),
    )
