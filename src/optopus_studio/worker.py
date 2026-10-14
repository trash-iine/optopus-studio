"""The Python solver worker: ``python -m optopus_studio.worker``.

Reads one ``SolveRequest`` as a JSON line on stdin, builds the problem with the project's
``model.py``, runs every variant's heuristic ``runs`` times, and writes ``WorkerEvent`` JSON lines
on stdout: ``started``, one ``run_finished`` per run, then ``done``, or an ``error`` at the stage
that failed.

A model's own ``print`` goes to stderr, so it cannot break the protocol.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import traceback
from types import ModuleType
from typing import Any, TextIO

import optopus
from pydantic import ValidationError

from optopus_studio.protocol import (
    Done,
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
TUPLE_ARGUMENTS = frozenset({"tabu_tenure"})
STOP_ARGUMENTS = frozenset({"stop", "restart"})

# The built-in problems whose report ranks higher values first. A Formula reports
# higher-is-better whichever way it optimizes.
HIGHER_IS_BETTER = frozenset({"MaxCut", "Sat", "Formula"})

MASK_64 = (1 << 64) - 1


class StageError(Exception):
    def __init__(self, stage: str, message: str, tb: str | None = None):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.tb = tb


def build_heuristic(spec: dict[str, Any]) -> Any:
    """Builds an optopus heuristic from ``{'kind': <class name>, **constructor arguments}``."""
    spec = dict(spec)
    kind = spec.pop("kind", None)
    if kind not in HEURISTICS:
        raise ValueError(f"unknown heuristic kind {kind!r}; expected one of {sorted(HEURISTICS)}")
    kwargs = {key: _argument(key, value) for key, value in spec.items()}
    return getattr(optopus, kind)(**kwargs)


def _argument(key: str, value: Any) -> Any:
    if key in STOP_ARGUMENTS and isinstance(value, dict):
        return optopus.StopCondition(**value)
    if isinstance(value, dict) and "kind" in value:
        return build_heuristic(value)
    if isinstance(value, list):
        items = [_argument("", item) for item in value]
        return tuple(items) if key in TUPLE_ARGUMENTS else items
    return value


def derive_seed(master: int, run_index: int) -> int:
    """The per-run seed optopus derives from a master seed, so that run ``i`` here matches run
    ``i`` of ``run(problem, runs=N, seed=master)``."""
    return (master + run_index * 0x9E37_79B9_7F4A_7C15) & MASK_64


def load_model(path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location("studio_model", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "build", None)):
        raise AttributeError("model.py must define build(instance)")
    return module


def is_builtin(problem: Any) -> bool:
    name = type(problem).__name__
    return type(problem) is getattr(optopus, name, None)


def higher_is_better(problem: Any) -> bool:
    name = type(problem).__name__
    if type(problem) is getattr(optopus, name, None):
        return name in HIGHER_IS_BETTER
    return not bool(problem.minimize)


def encode(model: ModuleType, instance: dict[str, Any], solution: Any) -> Any:
    encoder = getattr(model, "encode_solution", None)
    value = encoder(instance, solution) if callable(encoder) else solution
    if isinstance(value, tuple):
        value = list(value)
    json.dumps(value, allow_nan=False)
    return value


def watches_runs(heuristic: Any) -> bool:
    """Whether this optopus reports improvements during a run (``on_improvement``)."""
    return "on_improvement" in (getattr(heuristic.run, "__text_signature__", None) or "")


def solve(request: SolveRequest, emit) -> None:
    def stage(name: str, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            raise StageError(name, f"{type(exc).__name__}: {exc}", traceback.format_exc()) from exc

    model = stage("build", load_model, request.model_path)
    problem = stage("build", model.build, request.instance)
    direction = stage("build", higher_is_better, problem)
    heuristics = [stage("heuristic", build_heuristic, v.heuristic) for v in request.variants]
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
                    emit(
                        Progress(
                            run=index, variant=variant, elapsed_secs=elapsed, objective=objective
                        )
                    )

                args = (*args, progress)
            report = stage("run", heuristic.run, *args)
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


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    out = stdout
    sys.stdout = sys.stderr
    # Progress can arrive from optopus's ticker thread while the main thread writes.
    lock = threading.Lock()

    def emit(event) -> None:
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
