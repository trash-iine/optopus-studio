"""Runs a project's ``generate.py``: ``python -m optopus_studio.generator``.

Reads ``{"path", "seed", "params"}`` as one JSON line on stdin, calls
``generate(seed, **params)``, checks that it returns a JSON object, and writes
``{"instance": ...}`` or ``{"error": ...}`` as one JSON line on stdout.

This runs in its own process because ``generate.py`` is generated code, like ``view.py``
(``viewer.py``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from typing import Any


def generate(path: str, seed: int, params: dict[str, Any]) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("studio_generate", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "generate", None)
    if not callable(fn):
        raise AttributeError("generate.py must define generate(seed, **params)")
    instance = fn(seed, **params)
    if not isinstance(instance, dict):
        raise TypeError(f"generate returned a {type(instance).__name__}, not a dict")
    # Round-trips, so what is stored is what model.py will read.
    return json.loads(json.dumps(instance, allow_nan=False))


def main() -> int:
    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        request = json.loads(sys.stdin.readline())
        answer = {"instance": generate(request["path"], request["seed"], request["params"])}
    except Exception:
        answer = {"error": traceback.format_exc()}
    out.write(json.dumps(answer) + "\n")
    out.flush()
    return 0 if "instance" in answer else 1


if __name__ == "__main__":
    sys.exit(main())
