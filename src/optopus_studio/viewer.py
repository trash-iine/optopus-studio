"""Runs a project's ``view.py``: ``python -m optopus_studio.viewer``.

Reads ``{"view_path", "instance", "result"}`` as one JSON line on stdin, where ``result`` is a
``RunSummary`` with ``best`` added (the best run's ``run_finished`` event, or null). Calls
``to_view(instance, result)``, checks the answer against ``ViewSpec``, and writes
``{"view": ...}`` or ``{"error": ...}`` as one JSON line on stdout.

This runs in its own process because ``view.py`` is generated code: an exception, a hang or a
crash in it must not take the backend down.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback

from pydantic import ValidationError

from optopus_studio.protocol import ViewSpec


def render(view_path: str, instance: dict, result: dict) -> ViewSpec:
    """Runs ``to_view(instance, result)`` of a ``view.py`` and checks its answer.

    Args:
        view_path: The path of the ``view.py`` to run.
        instance: The instance the solve read.
        result: The solve's ``RunSummary``, with ``best`` added.

    Returns:
        The view the canvas draws.

    Raises:
        ImportError: The file cannot be loaded.
        AttributeError: The file defines no ``to_view``.
        pydantic.ValidationError: ``to_view`` returned something that is not a ``ViewSpec``.
    """
    spec = importlib.util.spec_from_file_location("studio_view", view_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {view_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    to_view = getattr(module, "to_view", None)
    if not callable(to_view):
        raise AttributeError("view.py must define to_view(instance, result)")
    return ViewSpec.model_validate(to_view(instance, result))


def main() -> int:
    """Answers one request read from stdin with one JSON line on stdout.

    Returns:
        The exit status: 0 when a view was drawn, 1 when it failed.
    """
    out = sys.stdout
    sys.stdout = sys.stderr
    try:
        request = json.loads(sys.stdin.readline())
        view = render(request["view_path"], request["instance"], request["result"])
        answer = {"view": view.model_dump(mode="json")}
    except ValidationError as exc:
        answer = {"error": f"to_view returned an invalid ViewSpec:\n{exc}"}
    except Exception:
        answer = {"error": traceback.format_exc()}
    out.write(json.dumps(answer) + "\n")
    out.flush()
    return 0 if "view" in answer else 1


if __name__ == "__main__":
    sys.exit(main())
