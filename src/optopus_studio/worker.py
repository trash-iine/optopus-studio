"""The Python solver worker: ``python -m optopus_studio.worker``.

Reads one ``SolveRequest`` as a JSON line on stdin, builds the problem with the project's
``model.py``, runs every variant's heuristic ``runs`` times, and writes ``WorkerEvent`` JSON lines
on stdout: ``started``, one ``run_finished`` per run, then ``done``, or an ``error`` at the stage
that failed. With ``--evaluate`` it reads an ``EvaluateRequest`` instead and scores its solutions.

A model's own ``print`` goes to stderr, so it cannot break the protocol.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import threading
import traceback
from functools import partial
from types import ModuleType
from typing import Any, TextIO

import optopus
from pydantic import ValidationError

from optopus_studio.protocol import (
    Done,
    EvaluateRequest,
    Progress,
    RunFinished,
    SolveRequest,
    Started,
    WorkerError,
)

HEURISTICS = frozenset(
    {
        "AdaptiveLargeNeighborhoodSearch",
        "BangBangSimulatedAnnealing",
        "BeamSearch",
        "BranchAndBound",
        "BreakoutLocalSearch",
        "GeneticAlgorithm",
        "GreedyRandomizedConstruction",
        "HybridGeneticSearch",
        "Iterated",
        "IteratedGreedy",
        "LateAcceptanceHillClimbing",
        "LinKernighanHelsgaun",
        "LocalSearch",
        "ParallelTempering",
        "PopulationAnnealing",
        "RandomWalk",
        "ReinforcementLearningSearch",
        "Restart",
        "Sequential",
        "SimulatedAnnealing",
        "TabuSearch",
        "VariableNeighborhoodSearch",
        "WalkSat",
    }
)

# Arguments the binding takes as a tuple, which JSON can only spell as a list.
TUPLE_ARGUMENTS = frozenset({"tabu_tenure", "scores", "penalty_adaptation", "initial_population"})
STOP_ARGUMENTS = frozenset({"stop", "restart"})
# The optopus classes a heuristic takes as an argument other than a heuristic, by argument name.
ARGUMENT_CLASSES = {"relaxation": frozenset({"EigenvalueRelaxation"})}

# The built-in problems whose report ranks higher values first. A Formula reports
# higher-is-better whichever way it optimizes.
HIGHER_IS_BETTER = frozenset({"MaxCut", "Sat", "Formula"})

MASK_64 = (1 << 64) - 1

# How optopus-py's ValueError for an initial_solution that does not fit the problem begins.
UNFIT_START = "'initial_solution' does not fit the problem"


class StageError(Exception):
    """A failure at one stage of a solve: build, heuristic, start, run or encode."""

    def __init__(self, stage: str, message: str, tb: str | None = None):
        """Records where the solve failed and why.

        Args:
            stage: The stage that failed.
            message: The exception's type and message.
            tb: The traceback, if any.
        """
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.tb = tb


def build_heuristic(spec: dict[str, Any]) -> Any:
    """Builds an optopus heuristic from ``{'kind': <class name>, **constructor arguments}``.

    Args:
        spec: The heuristic's dict; a nested heuristic is another such dict.

    Returns:
        The heuristic.

    Raises:
        ValueError: The kind is not an optopus heuristic.
    """
    spec = dict(spec)
    kind = spec.pop("kind", None)
    if kind not in HEURISTICS:
        raise ValueError(f"unknown heuristic kind {kind!r}; expected one of {sorted(HEURISTICS)}")
    kwargs = {key: _argument(key, value) for key, value in spec.items()}
    return getattr(optopus, kind)(**kwargs)


def _argument(key: str, value: Any) -> Any:
    """A heuristic's argument as the binding takes it.

    Stop conditions become ``StopCondition``, nested heuristics and argument classes are built, and
    lists become tuples where the binding wants a tuple.

    Args:
        key: The argument's name; empty for an item of a list.
        value: The argument's value as JSON holds it.

    Returns:
        The value to pass.
    """
    if key in STOP_ARGUMENTS and isinstance(value, dict):
        return optopus.StopCondition(**value)
    if isinstance(value, dict) and value.get("kind") in ARGUMENT_CLASSES.get(key, ()):
        kwargs = dict(value)
        return getattr(optopus, kwargs.pop("kind"))(**kwargs)
    if isinstance(value, dict) and "kind" in value:
        return build_heuristic(value)
    if isinstance(value, list):
        items = [_argument("", item) for item in value]
        return tuple(items) if key in TUPLE_ARGUMENTS else items
    return value


def derive_seed(master: int, run_index: int) -> int:
    """The per-run seed optopus derives from a master seed.

    Run ``i`` here thus matches run ``i`` of ``run(problem, runs=N, seed=master)``.

    Args:
        master: The solve's seed.
        run_index: The run's index among a heuristic's runs.

    Returns:
        The run's seed.
    """
    return (master + run_index * 0x9E37_79B9_7F4A_7C15) & MASK_64


def load_model(path: str) -> ModuleType:
    """Imports a project's ``model.py``.

    Args:
        path: The file's path.

    Returns:
        The module.

    Raises:
        ImportError: The file cannot be loaded.
        AttributeError: The file defines no ``build``.
        Exception: Whatever the file raises as it runs; it is the project's code.
    """
    spec = importlib.util.spec_from_file_location("studio_model", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise AttributeError("model.py must define build(instance)")
    return module


def is_builtin(problem: Any) -> bool:
    """Whether a problem is one of optopus's built-in classes rather than written in Python.

    Args:
        problem: The problem ``build`` returned.

    Returns:
        True for a built-in problem.
    """
    name = type(problem).__name__
    return type(problem) is getattr(optopus, name, None)


def higher_is_better(problem: Any) -> bool:
    """Whether the problem's report ranks higher objectives first.

    Args:
        problem: The problem ``build`` returned.

    Returns:
        True when higher is better.
    """
    name = type(problem).__name__
    if type(problem) is getattr(optopus, name, None):
        return name in HIGHER_IS_BETTER
    return not bool(problem.minimize)


def encode(model: ModuleType, instance: dict[str, Any], solution: Any) -> Any:
    """A solution as JSON can carry it: through the model's ``encode_solution``, if it has one.

    Args:
        model: The project's model module.
        instance: The instance the problem was built from.
        solution: The problem's own solution.

    Returns:
        The solution as a JSON value.

    Raises:
        ValueError: The value holds a number JSON cannot carry.
        TypeError: The value is not JSON.
    """
    encoder = getattr(model, "encode_solution", None)
    value = encoder(instance, solution) if callable(encoder) else solution
    if isinstance(value, tuple):
        value = list(value)
    json.dumps(value, allow_nan=False)
    return value


def decode(model: ModuleType, instance: dict[str, Any], value: Any) -> Any:
    """The problem's own solution for ``value``, which is in the form ``encode`` gives.

    Args:
        model: The project's model module.
        instance: The instance the problem was built from.
        value: The solution as JSON holds it.

    Returns:
        The solution, through the model's ``decode_solution`` if it has one.
    """
    decoder = getattr(model, "decode_solution", None)
    return decoder(instance, value) if callable(decoder) else value


def finite(value: float | None) -> float | None:
    """``value``, or None when it is not a finite number, which JSON cannot carry.

    Args:
        value: A number, or None.

    Returns:
        The number when it is finite, else None.
    """
    return value if value is not None and math.isfinite(value) else None


def watches_runs(heuristic: Any) -> bool:
    """Whether this optopus reports improvements during a run (``on_improvement``).

    Args:
        heuristic: A built heuristic.

    Returns:
        True when its ``run`` takes ``on_improvement``.
    """
    return "on_improvement" in (getattr(heuristic.run, "__text_signature__", None) or "")


def solve(request: SolveRequest, emit) -> None:
    """Runs every variant's heuristic ``runs`` times and emits the events of the solve.

    Args:
        request: The solve.
        emit: Called with each event, in order: started, progress, run_finished, done.

    Raises:
        StageError: A stage failed.
    """

    def stage(name: str, fn, *args):
        """Runs one step of a stage, turning any failure into the stage's error.

        Args:
            name: The stage.
            fn: The step.
            *args: The step's arguments.

        Returns:
            What the step returned.

        Raises:
            StageError: The step failed, a panic in optopus included.
        """
        try:
            return fn(*args)
        except (KeyboardInterrupt, SystemExit):
            raise
        # BaseException: a panic in optopus arrives as pyo3's PanicException, which is not an
        # Exception, and is a failure of the stage like any other.
        except BaseException as exc:
            raise StageError(name, f"{type(exc).__name__}: {exc}", traceback.format_exc()) from exc

    model = stage("build", load_model, request.model_path)
    problem = stage("build", model.build, request.instance)
    direction = stage("build", higher_is_better, problem)
    heuristics = [stage("heuristic", build_heuristic, v.heuristic) for v in request.variants]
    # Every run starts from the same solution, so it is decoded once.
    start = {}
    if request.initial_solution is not None:
        solution = request.initial_solution.solution
        start["initial_solution"] = stage("start", decode, model, request.instance, solution)
    emit(
        Started(
            runs=request.runs,
            variants=[v.label for v in request.variants],
            higher_is_better=direction,
            problem=type(problem).__name__,
            native=is_builtin(problem),
        )
    )

    best: tuple[int, float] | None = None
    index = 0
    for variant, heuristic in enumerate(heuristics):
        for run_index in range(request.runs):
            seed = None if request.seed is None else derive_seed(request.seed, run_index)
            args = (problem, 1, seed)
            if watches_runs(heuristic):

                def progress(_run, elapsed, objective, index=index, variant=variant):
                    """Emits a run's new best as it is found.

                    Args:
                        _run: The run's index within the call, always 0.
                        elapsed: The seconds since the run began.
                        objective: The new best objective.
                        index: The run's index in the solve.
                        variant: The run's heuristic.
                    """
                    emit(
                        Progress(
                            run=index, variant=variant, elapsed_secs=elapsed, objective=objective
                        )
                    )

                args = (*args, progress)
            try:
                report = stage("run", partial(heuristic.run, **start), *args)
            except StageError as exc:
                # optopus checks the solution a run starts from as the run begins.
                if start and exc.message.startswith(f"ValueError: {UNFIT_START}"):
                    exc.stage = "start"
                raise
            run = report.runs[0]
            solution = stage("encode", encode, model, request.instance, run.solution)
            emit(
                RunFinished(
                    run=index,
                    variant=variant,
                    seed=seed,
                    best_objective=run.best_objective,
                    initial_objective=run.initial_objective,
                    solution=solution,
                    trajectory=run.trajectory,
                    iterations=run.iterations,
                    best_iteration=run.best_iteration,
                    time_to_best_secs=run.time_to_best_secs,
                    total_time_secs=run.total_time_secs,
                    proven_optimal=run.proven_optimal,
                    dual_bound=finite(run.dual_bound),
                    n_accepted=run.n_accepted,
                    n_rejected=run.n_rejected,
                )
            )
            better = best is None or (
                run.best_objective > best[1] if direction else run.best_objective < best[1]
            )
            if better:
                best = (index, run.best_objective)
            index += 1
    assert best is not None
    emit(Done(best_run=best[0], best_objective=best[1]))


def evaluate(request: EvaluateRequest) -> list[float]:
    """Each solution's objective, as a run starting from it reports it before its first move.

    Args:
        request: The model, the instance, the solutions, and a heuristic to run them through.

    Returns:
        Each solution's objective, in order.
    """
    model = load_model(request.model_path)
    problem = model.build(request.instance)
    heuristic = build_heuristic({**request.heuristic, "stop": {"max_iteration": 0}})
    objectives = []
    for value in request.solutions:
        start = decode(model, request.instance, value)
        report = heuristic.run(problem, 1, 0, initial_solution=start)
        objectives.append(report.runs[0].initial_objective)
    return objectives


def main_evaluate(stdin: TextIO, out: TextIO) -> int:
    """Answers one ``EvaluateRequest`` read from stdin with one JSON line.

    Args:
        stdin: Where the request is read from.
        out: Where the answer is written.

    Returns:
        The exit status: 0 when the solutions were scored, 1 when it failed.
    """
    try:
        request = EvaluateRequest.model_validate_json(stdin.readline())
        answer: dict[str, Any] = {"objectives": evaluate(request)}
    except (KeyboardInterrupt, SystemExit):
        raise
    # As in solve: a panic in optopus is a BaseException.
    except BaseException as exc:
        answer = {"error": f"{type(exc).__name__}: {exc}"}
    out.write(json.dumps(answer) + "\n")
    out.flush()
    return 0 if "objectives" in answer else 1


def main(
    stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, args: list[str] | None = None
) -> int:
    """Answers one request from stdin: the solve's events, or with ``--evaluate`` the scores.

    Args:
        stdin: Where the request is read from.
        stdout: Where the events are written.
        args: The command line's arguments; ``sys.argv[1:]`` when None.

    Returns:
        The exit status: 0 on success, 1 when a stage failed, 2 for a bad request.
    """
    out = stdout
    sys.stdout = sys.stderr
    if "--evaluate" in (sys.argv[1:] if args is None else args):
        try:
            return main_evaluate(stdin, out)
        finally:
            sys.stdout = out
    # Progress can arrive from optopus's ticker thread while the main thread writes.
    lock = threading.Lock()

    def emit(event) -> None:
        """Writes one event as a JSON line, one thread at a time.

        Args:
            event: The event.
        """
        line = event.model_dump_json() + "\n"
        with lock:
            out.write(line)
            out.flush()

    try:
        request = SolveRequest.model_validate_json(stdin.readline())
    except ValidationError as exc:
        emit(WorkerError(stage="request", message=str(exc)))
        return 2
    try:
        solve(request, emit)
    except StageError as exc:
        emit(WorkerError(stage=exc.stage, message=exc.message, traceback=exc.tb))
        return 1
    finally:
        sys.stdout = out
    return 0


if __name__ == "__main__":
    sys.exit(main())
