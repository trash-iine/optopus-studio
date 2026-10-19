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
    LiveRun,
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
    custom = os.environ.get("OPTOPUS_STUDIO_WORKER")
    if custom:
        return shlex.split(custom)
    return [sys.executable, "-m", "optopus_studio.worker"]


async def _spawn(command: list[str], cwd: Path) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=LINE_LIMIT,
    )


async def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
        await process.wait()


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
    result = summary.model_dump(mode="json")
    best = summary.runs[summary.best_run] if summary.best_run is not None else None
    result["best"] = best.model_dump(mode="json") if best else None
    return result


async def render_view(
    view_path: Path, instance: dict[str, Any], summary: RunSummary, timeout: float = 30.0
) -> tuple[ViewSpec | None, str | None]:
    """Runs ``view.py`` on a solve's summary, returning the view or the error."""
    process = await _spawn([sys.executable, "-m", "optopus_studio.viewer"], view_path.parent)
    request = {"view_path": str(view_path), "instance": instance, "result": view_input(summary)}
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate((json.dumps(request) + "\n").encode()), timeout
        )
    except TimeoutError:
        await _kill(process)
        return None, f"view.py took longer than {timeout}s"
    try:
        answer = json.loads(stdout.decode().strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None, f"view.py crashed:\n{stderr.decode(errors='replace')[-STDERR_TAIL:]}"
    if "view" in answer:
        return ViewSpec.model_validate(answer["view"]), None
    return None, answer.get("error", "view.py failed")
