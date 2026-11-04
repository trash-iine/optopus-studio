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
    """Runs ``generate(seed, **params)`` of a ``generate.py`` and checks its instance.

    Args:
        path: The path of the ``generate.py`` to run.
        seed: The seed passed to ``generate``.
        params: The keyword arguments passed to ``generate``.

    Returns:
        The instance, round-tripped through JSON so that what is stored is what ``model.py`` reads.

    Raises:
        ImportError: The file cannot be loaded.
        AttributeError: The file defines no ``generate``.
        TypeError: ``generate`` returned something other than a dict, or one JSON cannot carry.
        ValueError: The instance holds a number JSON cannot carry.
        Exception: Whatever the file or ``generate`` raises; it is the project's code.
    """
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
    """Answers one request read from stdin with one JSON line on stdout.

    Returns:
        The exit status: 0 when an instance was generated, 1 when it failed.
    """
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
