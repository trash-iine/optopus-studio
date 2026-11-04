"""Checking a Rust port against the Python model it replaces, before the studio switches to it.

Both workers solve the same request with the same seeds. Then:

- **objective**: the port evaluates the Python worker's best solutions, and must give the same
  objectives. This is what proves the port models the same problem.
- **exact** (a built-in problem, seeded, no time limit anywhere): every run must match, seed,
  initial and best objective, iteration and accepted move counts, trajectory and solution. Both
  sides run the same core code from the same state, so any difference is a bug in the port.
- **stat** (otherwise; a problem written in Python draws its random moves through Python's
  ``random``): per heuristic, the Rust mean must not be worse than the Python mean by more than
  twice the larger spread plus 5% of the Python runs' mean improvement, the rule of optopus-py's
  port-to-rust skill.
- the project's ``view.py`` must render the Rust worker's result.

The report ends with how much faster the port searches, in iterations per second.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from optopus_studio.protocol import EvaluateRequest, RunFinished, RunSummary, SolveRequest
from optopus_studio.runner import evaluate_solutions, ignore_progress, render_view, run_solve

STAT_TOLERANCE = 0.05


@dataclass
class Verdict:
    """What a check of a port found, line by line.

    Attributes:
        ok: Whether every check passed so far.
        lines: The report's lines, failures prefixed with ``FAIL``.
    """

    ok: bool = True
    lines: list[str] = field(default_factory=list)

    def fail(self, line: str) -> None:
        """Records a failed check.

        Args:
            line: What failed.
        """
        self.ok = False
        self.lines.append(f"FAIL {line}")

    def note(self, line: str) -> None:
        """Records a passed check or a measurement.

        Args:
            line: What was found.
        """
        self.lines.append(line)

    @property
    def text(self) -> str:
        """The report: PASS or FAIL, then every line."""
        head = "PASS" if self.ok else "FAIL"
        return "\n".join([f"verification: {head}", *self.lines])


def has_time_limit(spec: Any) -> bool:
    """Whether a heuristic, or one nested in it, stops after a time limit.

    Args:
        spec: A heuristic's dict, or any value nested in one.

    Returns:
        True when some ``stop`` has a ``max_duration_secs``.
    """
    if isinstance(spec, dict):
        stop = spec.get("stop")
        if isinstance(stop, dict) and stop.get("max_duration_secs") is not None:
            return True
        return any(has_time_limit(v) for k, v in spec.items() if k != "stop")
    if isinstance(spec, list):
        return any(has_time_limit(v) for v in spec)
    return False


def _rate(runs: list[RunFinished]) -> float:
    """How many iterations the runs made per second.

    Args:
        runs: The runs to measure.

    Returns:
        The iterations per second; infinity when the runs took no time.
    """
    seconds = sum(r.total_time_secs for r in runs)
    return sum(r.iterations for r in runs) / seconds if seconds > 0 else math.inf


def _exact(py: RunSummary, rs: RunSummary, verdict: Verdict) -> None:
    """Checks that every run of the port matches the Python worker's, step for step.

    Args:
        py: The Python worker's solve.
        rs: The Rust worker's solve, with the same request and seeds.
        verdict: The verdict to record the outcome in.
    """
    for p, r in zip(py.runs, rs.runs, strict=True):
        fields = {
            "seed": (p.seed, r.seed),
            "initial_objective": (p.initial_objective, r.initial_objective),
            "best_objective": (p.best_objective, r.best_objective),
            "iterations": (p.iterations, r.iterations),
            "n_accepted": (p.n_accepted, r.n_accepted),
            "trajectory": ([t[1:] for t in p.trajectory], [t[1:] for t in r.trajectory]),
            "solution": (p.solution, r.solution),
        }
        for name, (a, b) in fields.items():
            same = math.isclose(a, b, rel_tol=1e-9) if isinstance(a, float) else a == b
            if not same:
                verdict.fail(
                    f"exact: run {p.run} differs first in {name}: python {a!r}, rust {b!r}"
                )
                return
    verdict.note(f"exact: all {len(py.runs)} runs match the Python worker's step for step")


def _stat(py: RunSummary, rs: RunSummary, verdict: Verdict) -> None:
    """Checks, per heuristic, that the port's mean objective is no worse than Python's by much.

    Args:
        py: The Python worker's solve.
        rs: The Rust worker's solve, with the same request and seeds.
        verdict: The verdict to record the outcome in.
    """
    for index, label in enumerate(py.variants):
        p_runs = [r for r in py.runs if r.variant == index]
        r_runs = [r for r in rs.runs if r.variant == index]
        p_obj = [r.best_objective for r in p_runs]
        r_obj = [r.best_objective for r in r_runs]
        p_avg, r_avg = statistics.fmean(p_obj), statistics.fmean(r_obj)
        spread = max(statistics.pstdev(p_obj), statistics.pstdev(r_obj))
        improvement = statistics.fmean(abs(r.best_objective - r.initial_objective) for r in p_runs)
        slack = 2 * spread + STAT_TOLERANCE * improvement
        worse_by = (p_avg - r_avg) if py.higher_is_better else (r_avg - p_avg)
        line = (
            f"stat {label}: mean python {p_avg:g}, rust {r_avg:g}; rust worse by {worse_by:g} "
            f"(allowed {slack:g})"
        )
        if worse_by <= slack:
            verdict.note(f"{line} -> ok")
        else:
            verdict.fail(line)


async def verify(
    request: SolveRequest, binary: Path, cwd: Path, view_path: Path, timeout: float
) -> Verdict:
    """Checks a Rust port against the Python model it replaces.

    Args:
        request: The solve both workers run.
        binary: The port's worker binary.
        cwd: The project's directory, where the workers run.
        view_path: The project's ``view.py``, which must render the port's result.
        timeout: How long each solve may take, in seconds.

    Returns:
        The verdict, with a line per check and the port's speed.
    """
    verdict = Verdict()
    py = await run_solve(request, 0, cwd, ignore_progress, timeout)
    rs = await run_solve(request, 0, cwd, ignore_progress, timeout, rust_binary=binary)
    for name, summary in (("python", py), ("rust", rs)):
        if summary.error:
            error = summary.error
            verdict.fail(f"the {name} worker failed at {error.stage}: {error.message}")
    if not verdict.ok:
        return verdict
    if (len(py.runs), py.variants) != (len(rs.runs), rs.variants):
        verdict.fail("the workers ran different runs")
        return verdict
    if py.higher_is_better != rs.higher_is_better:
        verdict.fail(
            f"direction: python says higher_is_better={py.higher_is_better}, rust "
            f"{rs.higher_is_better}"
        )
        return verdict

    try:
        scored = EvaluateRequest(
            model_path=request.model_path,
            instance=request.instance,
            solutions=[r.solution for r in py.runs],
            heuristic=request.variants[0].heuristic,
        )
        objectives = await evaluate_solutions([str(binary)], scored, binary.parent)
    except (RuntimeError, OSError) as exc:
        verdict.fail(f"objective: the port cannot evaluate the Python solutions: {exc}")
        return verdict
    mismatched = [
        (r.run, r.best_objective, got)
        for r, got in zip(py.runs, objectives, strict=True)
        if not math.isclose(r.best_objective, got, rel_tol=1e-9, abs_tol=1e-9)
    ]
    if mismatched:
        run, want, got = mismatched[0]
        verdict.fail(
            f"objective: {len(mismatched)} of {len(py.runs)} Python solutions score differently "
            f"in Rust, e.g. run {run}: python {want!r}, rust {got!r}"
        )
    else:
        verdict.note(f"objective: the port scores all {len(py.runs)} Python solutions the same")

    exact = (
        py.native
        and request.seed is not None
        and not any(has_time_limit(v.heuristic) for v in request.variants)
    )
    (_exact if exact else _stat)(py, rs, verdict)

    view, error = await render_view(view_path, request.instance, rs)
    if error:
        verdict.fail(f"view.py cannot render the Rust result:\n{error}")
    else:
        verdict.note(f"view.py renders the Rust result ({len(view.views) if view else 0} views)")

    for index, label in enumerate(py.variants):
        p_rate = _rate([r for r in py.runs if r.variant == index])
        r_rate = _rate([r for r in rs.runs if r.variant == index])
        verdict.note(
            f"speed {label}: python {p_rate:,.0f} iterations/s, rust {r_rate:,.0f} "
            f"({r_rate / p_rate:.1f}x)"
        )
    return verdict
