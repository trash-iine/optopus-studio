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
from optopus_studio.protocol import SolveRequest

DEFAULT_SOLVE_TIMEOUT = 300.0


def with_stop(heuristic: dict[str, Any], **stop: Any) -> dict[str, Any]:
    return {**heuristic, "stop": {**(heuristic.get("stop") or {}), **stop}}


def solve_request(
    solve: dict[str, Any], instance: Any, model_path: Path, overrides: dict[str, Any]
) -> SolveRequest:
    """The request solve.json describes, with ``max_duration_secs``, ``runs`` or ``seed``
    replaced by ``overrides``."""
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
        )
    except ValidationError as exc:
        raise ProjectError(f"solve.json does not describe a solve: {exc}") from exc


def worker_of(solve: dict[str, Any]) -> str:
    """The worker solve.json asks for: "python" (the default) or "rust"."""
    worker = solve.get("worker", "python")
    if worker not in ("python", "rust"):
        raise ProjectError(f'"worker" must be "python" or "rust", not {worker!r}')
    return worker


async def rust_binary(solve: dict[str, Any], main_rs: str | None) -> Path | None:
    """The built port when solve.json asks for the Rust worker, else None."""
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
