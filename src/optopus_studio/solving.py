"""From a model's files to a solve: the request, the worker, the time it may take.

The agent solves the project it edits; an app (docs/adr/0009) solves the revision it packages
with its user's data. Both go through these.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from optopus_studio import rust
from optopus_studio.projects import ProjectError, variants_of
from optopus_studio.protocol import InitialSolution, SolveRequest

DEFAULT_SOLVE_TIMEOUT = 300.0


def with_stop(heuristic: dict[str, Any], **stop: Any) -> dict[str, Any]:
    """A heuristic with some of its stop condition replaced.

    Args:
        heuristic: The heuristic's dict.
        **stop: The stop condition's arguments to set.

    Returns:
        A copy of the heuristic with the arguments set.
    """
    return {**heuristic, "stop": {**(heuristic.get("stop") or {}), **stop}}


def solve_request(
    solve: dict[str, Any], instance: Any, model_path: Path, overrides: dict[str, Any]
) -> SolveRequest:
    """The request solve.json describes, with some of its settings replaced.

    Args:
        solve: solve.json's content.
        instance: instance.json's content.
        model_path: The ``model.py`` the worker imports.
        overrides: ``max_duration_secs``, ``runs`` or ``seed`` to use instead of solve.json's.

    Returns:
        The solve request.

    Raises:
        ProjectError: solve.json does not describe a solve.
    """
    start = initial_solution(solve, instance)
    try:
        variants = variants_of(solve)
        if "max_duration_secs" in overrides:
            seconds = overrides["max_duration_secs"]
            for v in variants:
                v.heuristic = with_stop(v.heuristic, max_duration_secs=seconds)
        return SolveRequest(
            model_path=str(model_path),
            instance=instance,
            variants=variants,
            runs=overrides.get("runs", solve.get("runs", 1)),
            seed=overrides.get("seed", solve.get("seed", 0)),
            initial_solution=start,
        )
    except ValidationError as exc:
        raise ProjectError(f"solve.json does not describe a solve: {exc}") from exc


def initial_solution(solve: dict[str, Any], instance: Any) -> InitialSolution | None:
    """The solution solve.json's "initial_solution" names.

    It is a key of instance.json, so the data a revision starts from is in its own files
    (docs/adr/0011).

    Args:
        solve: solve.json's content.
        instance: instance.json's content.

    Returns:
        The solution under that key, or None when solve.json names none.

    Raises:
        ProjectError: The name is not a string, or instance.json has no such key.
    """
    key = solve.get("initial_solution")
    if key is None:
        return None
    if not isinstance(key, str):
        raise ProjectError('"initial_solution" must be the key of instance.json that holds it')
    if not isinstance(instance, dict) or key not in instance:
        raise ProjectError(
            f'solve.json starts from instance["{key}"], but instance.json has no such key'
        )
    return InitialSolution(key=key, solution=instance[key])


def worker_of(solve: dict[str, Any]) -> str:
    """The worker solve.json asks for: "python" (the default) or "rust".

    Args:
        solve: solve.json's content.

    Returns:
        The worker's name.

    Raises:
        ProjectError: solve.json names another worker.
    """
    worker = solve.get("worker", "python")
    if worker not in ("python", "rust"):
        raise ProjectError(f'"worker" must be "python" or "rust", not {worker!r}')
    return worker


async def rust_binary(solve: dict[str, Any], main_rs: str | None) -> Path | None:
    """The built port when solve.json asks for the Rust worker, else None.

    Args:
        solve: solve.json's content.
        main_rs: The port's source, or None when the project has none.

    Returns:
        The port's binary, or None for the Python worker.

    Raises:
        ProjectError: The Rust worker is asked for, but there is no port or it does not build.
    """
    if worker_of(solve) != "rust":
        return None
    if main_rs is None:
        raise ProjectError(
            f'solve.json asks for "worker": "rust", but there is no {rust.RUST_FILE}'
        )
    built = await rust.build(main_rs)
    if not built.ok:
        raise ProjectError(f"{rust.RUST_FILE} does not build:\n{built.log}")
    return built.binary


def solve_timeout(request: SolveRequest) -> float:
    """How long a solve may take before it is stopped.

    ``OPTOPUS_STUDIO_SOLVE_TIMEOUT`` when set; otherwise every run's time limit plus 30 seconds,
    capped at four times ``DEFAULT_SOLVE_TIMEOUT``, or ``DEFAULT_SOLVE_TIMEOUT`` itself when some
    heuristic has no time limit.

    Args:
        request: The solve.

    Returns:
        The timeout in seconds.
    """
    configured = os.environ.get("OPTOPUS_STUDIO_SOLVE_TIMEOUT")
    if configured:
        return float(configured)
    total = 0.0
    for variant in request.variants:
        seconds = (variant.heuristic.get("stop") or {}).get("max_duration_secs")
        if not isinstance(seconds, int | float):
            return DEFAULT_SOLVE_TIMEOUT
        total += seconds * request.runs
    return min(total + 30.0, DEFAULT_SOLVE_TIMEOUT * 4)
