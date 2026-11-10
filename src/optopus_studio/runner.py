"""Starts the worker and viewer subprocesses and reads their answers.

The worker command is the one place that knows which solver runs: ``OPTOPUS_STUDIO_WORKER``
replaces the Python worker with any program that speaks the same protocol, such as a Rust worker.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from optopus_studio.protocol import (
    Done,
    EvaluateRequest,
    LiveRun,
    ProbeRequest,
    Progress,
    RunFinished,
    RunSummary,
    SolveRequest,
    Started,
    ViewSpec,
    WorkerError,
    WorkerEvent,
)

WORKER_EVENT = TypeAdapter(WorkerEvent)
STDERR_TAIL = 4000
# A worker writes a whole solution on one line, so lines can be long.
LINE_LIMIT = 64 * 1024 * 1024


def worker_command() -> list[str]:
    """The command that starts a solver worker: ``OPTOPUS_STUDIO_WORKER``, or the Python worker.

    Returns:
        The command's arguments.
    """
    custom = os.environ.get("OPTOPUS_STUDIO_WORKER")
    if custom:
        return shlex.split(custom)
    return [sys.executable, "-m", "optopus_studio.worker"]


async def _spawn(command: list[str], cwd: Path) -> asyncio.subprocess.Process:
    """Starts a process with pipes on its stdin, stdout and stderr.

    Args:
        command: The command's arguments.
        cwd: The directory to run it in.

    Returns:
        The process.
    """
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=LINE_LIMIT,
    )


async def _kill(process: asyncio.subprocess.Process) -> None:
    """Kills a process unless it has exited, and waits for it.

    Args:
        process: The process.
    """
    if process.returncode is None:
        process.kill()
        await process.wait()


async def ignore_progress(_: RunSummary) -> None:
    """An ``on_update`` for ``run_solve`` that ignores a solve's progress.

    Args:
        _: The solve so far.
    """


async def run_solve(
    request: SolveRequest,
    rev: int,
    cwd: Path,
    on_update: Callable[[RunSummary], Awaitable[None]],
    timeout: float,
    rust_binary: Path | None = None,
) -> RunSummary:
    """Runs one solve and returns its summary, calling ``on_update`` after every event.

    The Python worker runs it unless ``rust_binary``, a built port, is given.

    Args:
        request: The solve.
        rev: The revision the solve belongs to.
        cwd: The project's directory, where the worker runs.
        on_update: Called with the summary so far after every event the worker sends.
        timeout: How long the solve may take, in seconds.
        rust_binary: The port to run instead of the Python worker, if any.

    Returns:
        The summary, with an error when the worker failed, timed out or exited early.
    """
    summary = RunSummary(
        rev=rev,
        worker="rust" if rust_binary else "python",
        heuristics=request.variants,
        seed=request.seed,
        initial_solution=request.initial_solution.key if request.initial_solution else None,
    )
    command = [str(rust_binary)] if rust_binary else worker_command()
    process = await _spawn(command, cwd)
    assert process.stdin
    assert process.stdout
    assert process.stderr
    process.stdin.write((request.model_dump_json() + "\n").encode())
    await process.stdin.drain()
    process.stdin.close()
    stderr_task = asyncio.create_task(process.stderr.read())

    async def read_events() -> None:
        """Reads the worker's events into the summary until its stdout closes."""
        assert process.stdout
        async for line in process.stdout:
            try:
                event = WORKER_EVENT.validate_json(line)
            except ValidationError as exc:
                summary.error = WorkerError(stage="run", message=f"bad worker output: {exc}")
                return
            match event:
                case Started():
                    summary.problem = event.problem
                    summary.higher_is_better = event.higher_is_better
                    summary.variants = event.variants
                    summary.native = event.native
                case Progress():
                    point = (event.elapsed_secs, event.objective)
                    if summary.live and summary.live.run == event.run:
                        summary.live.points.append(point)
                    else:
                        summary.live = LiveRun(run=event.run, variant=event.variant, points=[point])
                case RunFinished():
                    summary.live = None
                    summary.runs.append(event)
                case Done():
                    summary.best_run = event.best_run
                case WorkerError():
                    summary.error = event
            await on_update(summary)

    try:
        await asyncio.wait_for(read_events(), timeout)
    except TimeoutError:
        summary.error = WorkerError(stage="run", message=f"the solve took longer than {timeout}s")
    finally:
        await _kill(process)
    stderr = (await stderr_task).decode(errors="replace")
    if summary.best_run is None and summary.error is None:
        summary.error = WorkerError(
            stage="run",
            message=f"the worker exited with {process.returncode} before finishing",
            traceback=stderr[-STDERR_TAIL:] or None,
        )
    await on_update(summary)
    return summary


def view_input(summary: RunSummary) -> dict[str, Any]:
    """The ``result`` that ``to_view`` reads: the summary with the best run added as ``best``.

    Args:
        summary: The solve's summary.

    Returns:
        The summary as JSON.
    """
    result = summary.model_dump(mode="json")
    best = summary.runs[summary.best_run] if summary.best_run is not None else None
    result["best"] = best.model_dump(mode="json") if best else None
    return result


async def render_view(
    view_path: Path, instance: dict[str, Any], summary: RunSummary, timeout: float = 30.0
) -> tuple[ViewSpec | None, str | None]:
    """Runs ``view.py`` on a solve's summary, returning the view or the error.

    Args:
        view_path: The project's ``view.py``.
        instance: The instance the solve read.
        summary: The solve's summary.
        timeout: How long ``view.py`` may take, in seconds.

    Returns:
        The view and None, or None and what went wrong.
    """
    request = {"view_path": str(view_path), "instance": instance, "result": view_input(summary)}
    answer, error = await _ask(
        [sys.executable, "-m", "optopus_studio.viewer"], view_path.parent, request, timeout
    )
    if error:
        return None, f"view.py {error}"
    if "view" in answer:
        return ViewSpec.model_validate(answer["view"]), None
    return None, answer.get("error", "view.py failed")


async def run_generator(
    path: Path, seed: int, params: dict[str, Any], timeout: float = 60.0
) -> tuple[dict[str, Any] | None, str | None]:
    """Runs ``generate.py``, returning the instance it made or the error.

    Args:
        path: The ``generate.py`` to run.
        seed: The seed passed to ``generate``.
        params: The keyword arguments passed to ``generate``.
        timeout: How long ``generate.py`` may take, in seconds.

    Returns:
        The instance and None, or None and what went wrong.
    """
    request = {"path": str(path), "seed": seed, "params": params}
    answer, error = await _ask(
        [sys.executable, "-m", "optopus_studio.generator"], path, request, timeout
    )
    if error:
        return None, f"generate.py {error}"
    if "instance" in answer:
        return answer["instance"], None
    return None, answer.get("error", "generate.py failed")


async def evaluate_solutions(
    command: list[str], request: EvaluateRequest, cwd: Path, timeout: float = 60.0
) -> list[float]:
    """Scores solutions with a worker started with ``--evaluate`` (see ``EvaluateRequest``).

    Args:
        command: The command that starts the worker, without ``--evaluate``.
        request: The model, the instance and the solutions to score.
        cwd: The directory to run the worker in.
        timeout: How long the worker may take, in seconds.

    Returns:
        Each solution's objective, in order.

    Raises:
        RuntimeError: The worker timed out, crashed or answered with an error.
    """
    answer, error = await _ask([*command, "--evaluate"], cwd, request.model_dump(), timeout)
    if error:
        raise RuntimeError(f"the worker {error}")
    if "error" in answer:
        raise RuntimeError(answer["error"])
    return answer["objectives"]


async def run_probe(request: ProbeRequest, cwd: Path, timeout: float) -> dict[str, Any]:
    """Probes a heuristic's runs on one instance in a subprocess (probe.py).

    Args:
        request: The model, the instance, the heuristic and what to probe.
        cwd: The directory to run the probe in.
        timeout: How long the probe may take, in seconds.

    Returns:
        The probe's answer.

    Raises:
        RuntimeError: The probe timed out, crashed or answered with an error.
    """
    command = [sys.executable, "-m", "optopus_studio.probe"]
    answer, error = await _ask(command, cwd, request.model_dump(), timeout)
    if error:
        raise RuntimeError(f"the probe {error}")
    if "error" in answer:
        raise RuntimeError(answer["error"])
    return answer


async def _ask(
    command: list[str], cwd: Path, request: dict[str, Any], timeout: float
) -> tuple[dict[str, Any], str | None]:
    """Sends one JSON line to a fresh process and reads its one-line answer.

    Args:
        command: The command that starts the process.
        cwd: The directory to run it in, or a file in that directory.
        request: The request to send.
        timeout: How long the process may take, in seconds.

    Returns:
        The answer and None, or an empty answer and why there is none.
    """
    process = await _spawn(command, cwd if cwd.is_dir() else cwd.parent)
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate((json.dumps(request) + "\n").encode()), timeout
        )
    except TimeoutError:
        await _kill(process)
        return {}, f"took longer than {timeout}s"
    try:
        return json.loads(stdout.decode().strip().splitlines()[-1]), None
    except (IndexError, json.JSONDecodeError):
        return {}, f"crashed:\n{stderr.decode(errors='replace')[-STDERR_TAIL:]}"
