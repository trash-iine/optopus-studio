"""The diagnosis probe: ``python -m optopus_studio.probe`` (docs/adr/0020).

Reads one ``ProbeRequest`` as a JSON line on stdin and answers with one JSON line: what a
heuristic's runs on one instance show beyond their objectives, for ``diagnosis.py`` to read.

- **runs**: the heuristic's runs as a solve makes them, with the same seeds, each with its best
  solution.
- **probes**: from each run's best solution, a short best-improving descent in each neighborhood
  named. A descent that still improves says the solution is not a local optimum of that
  neighborhood.
- **terms**: what the model's optional ``explain(instance, solution)`` says each best solution's
  objective is made of.
- **calls**: for a problem written in Python, one more run with the problem's neighborhoods and
  its ``objective`` wrapped to count their calls and time, and how many of the deltas computed
  would improve. The wrapping slows the run, so it is apart from the runs above.

It always runs the project's ``model.py``, also when solve.json asks for the Rust worker: the
model is the reference a port mirrors (docs/adr/0005), and only it can be wrapped. Like the
worker, the model's own ``print`` goes to stderr.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from typing import Any, TextIO

from optopus_studio import worker
from optopus_studio.protocol import ProbeRequest

# The stop of a probe's descent: enough steps to show a solution improves, not to finish it.
PROBE_STOP = {"max_iteration": 20, "max_duration_secs": 0.5}
# What a problem's neighborhood may define; the rest is passed through unwrapped.
METHODS = ("neighbors", "random_neighbor", "apply", "delta", "tabu_keys")


class Counted:
    """A neighborhood, or any object, whose methods count their calls and time.

    Every public attribute of the wrapped object is an attribute of this one, so what the
    object lacks (a ``delta``, say) this lacks too, and optopus treats it the same.

    Attributes:
        calls: By method name, the calls made and the seconds they took.
        deltas: The deltas computed, and how many of them would improve the objective.
    """

    def __init__(self, inner: Any, lower_is_better: bool):
        """Wraps an object.

        Args:
            inner: The object.
            lower_is_better: Whether a negative delta improves.
        """
        self.calls: dict[str, list[float]] = {}
        self.deltas = [0, 0]
        for name in dir(inner):
            if name.startswith("_"):
                continue
            value = getattr(inner, name)
            wrapped = self._timed(name, value, lower_is_better) if name in METHODS else value
            setattr(self, name, wrapped)

    def _timed(self, name: str, method: Callable[..., Any], lower_is_better: bool) -> Any:
        """A method that counts its calls and time, and reads the sign of a delta.

        Args:
            name: The method's name.
            method: The method.
            lower_is_better: Whether a negative delta improves.

        Returns:
            The counting method.
        """
        count = self.calls.setdefault(name, [0, 0.0])

        def call(*args: Any) -> Any:
            """Calls the method and counts it.

            Args:
                *args: The method's arguments.

            Returns:
                What the method returned.
            """
            started = time.perf_counter()
            try:
                result = method(*args)
            finally:
                count[0] += 1
                count[1] += time.perf_counter() - started
            if name == "delta" and isinstance(result, int | float):
                self.deltas[0] += 1
                self.deltas[1] += result < 0 if lower_is_better else result > 0
            return result

        return call


def neighbors_of(heuristic: Any) -> list[str]:
    """The neighborhoods a heuristic's dict names, itself and the heuristics inside it.

    Args:
        heuristic: The heuristic's dict, or a part of it.

    Returns:
        The names, in the order met, each once.
    """
    found: list[str] = []
    if isinstance(heuristic, dict):
        name = heuristic.get("neighbor")
        if isinstance(name, str):
            found.append(name)
        for value in heuristic.values():
            found += neighbors_of(value)
    elif isinstance(heuristic, list):
        for item in heuristic:
            found += neighbors_of(item)
    return list(dict.fromkeys(found))


def probe(request: ProbeRequest) -> dict[str, Any]:
    """Runs the heuristic and reads what its runs show.

    Args:
        request: The model, the instance, the heuristic and what to probe.

    Returns:
        The answer, as this module's docstring describes it.
    """
    model = worker.load_model(request.model_path)
    problem = model.build(request.instance)
    higher = worker.higher_is_better(problem)
    native = worker.is_builtin(problem)
    start = {}
    if request.initial_solution is not None:
        solution = request.initial_solution.solution
        start["initial_solution"] = worker.decode(model, request.instance, solution)
    own = [] if native else list(getattr(problem, "neighborhoods", {}) or {})
    names = request.neighbors or own or neighbors_of(request.heuristic)
    explain = getattr(model, "explain", None)

    heuristic = worker.build_heuristic(request.heuristic)
    runs, explain_error, probe_errors = [], None, {}
    for index in range(request.runs):
        seed = worker.derive_seed(request.seed, index)
        run = heuristic.run(problem, 1, seed, **start).runs[0]
        terms = None
        if callable(explain) and explain_error is None:
            try:
                terms = {
                    str(k): float(v) for k, v in explain(request.instance, run.solution).items()
                }
            except Exception as exc:
                explain_error = f"{type(exc).__name__}: {exc}"
        probes: dict[str, float | None] = {}
        for name in names:
            if name in probe_errors:
                continue
            descent = worker.build_heuristic(
                {"kind": "LocalSearch", "neighbor": name, "stop": PROBE_STOP}
            )
            try:
                found = descent.run(problem, 1, 0, initial_solution=run.solution).runs[0]
                probes[name] = found.best_objective
            except (KeyboardInterrupt, SystemExit):
                raise
            # As in the worker: a panic in optopus is a BaseException.
            except BaseException as exc:
                probe_errors[name] = f"{type(exc).__name__}: {exc}"
        runs.append(
            {
                "seed": seed,
                "best_objective": run.best_objective,
                "initial_objective": run.initial_objective,
                "iterations": run.iterations,
                "best_iteration": run.best_iteration,
                "time_to_best_secs": run.time_to_best_secs,
                "total_time_secs": run.total_time_secs,
                "n_accepted": run.n_accepted,
                "n_rejected": run.n_rejected,
                "solution": worker.encode(model, request.instance, run.solution),
                "terms": terms,
                "probes": probes,
            }
        )
    answer = {
        "problem": type(problem).__name__,
        "native": native,
        "higher_is_better": higher,
        "runs": runs,
        "probe_errors": probe_errors,
        "explain_error": explain_error,
        "calls": None,
    }
    if own:
        answer["calls"] = counted_run(problem, heuristic, request, start, not higher)
    return answer


def counted_run(
    problem: Any, heuristic: Any, request: ProbeRequest, start: dict[str, Any], lower: bool
) -> dict[str, Any]:
    """One more run, with the problem's neighborhoods and objective counting their calls.

    Args:
        problem: The problem, written in Python.
        heuristic: The heuristic.
        request: The probe's request.
        start: The solution the runs start from, if any, as ``run`` takes it.
        lower: Whether lower objectives are better.

    Returns:
        The run's iterations and seconds, each neighborhood's calls and deltas, and the
        objective's calls.
    """
    wrapped = {name: Counted(inner, lower) for name, inner in problem.neighborhoods.items()}
    problem.neighborhoods = wrapped
    objective = [0, 0.0]
    scored = problem.objective

    def counting(solution: Any) -> Any:
        """Scores a solution and counts the call.

        Args:
            solution: The solution.

        Returns:
            Its objective.
        """
        started = time.perf_counter()
        try:
            return scored(solution)
        finally:
            objective[0] += 1
            objective[1] += time.perf_counter() - started

    problem.objective = counting
    run = heuristic.run(problem, 1, worker.derive_seed(request.seed, 0), **start).runs[0]
    return {
        "iterations": run.iterations,
        "seconds": run.total_time_secs,
        "objective": objective,
        "neighborhoods": {
            name: {"calls": c.calls, "deltas": c.deltas[0], "improving": c.deltas[1]}
            for name, c in wrapped.items()
        },
    }


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """Answers one ``ProbeRequest`` read from stdin with one JSON line.

    Args:
        stdin: Where the request is read from.
        stdout: Where the answer is written.

    Returns:
        The exit status: 0 when the probe ran, 1 when it failed.
    """
    out = stdout
    sys.stdout = sys.stderr
    try:
        request = ProbeRequest.model_validate_json(stdin.readline())
        answer = probe(request)
        text = json.dumps(answer)
    except (KeyboardInterrupt, SystemExit):
        raise
    # As in the worker: a panic in optopus is a BaseException.
    except BaseException as exc:
        answer = {"error": f"{type(exc).__name__}: {exc}"}
        text = json.dumps(answer)
    finally:
        sys.stdout = out
    out.write(text + "\n")
    out.flush()
    return 0 if "error" not in answer else 1


if __name__ == "__main__":
    sys.exit(main())
