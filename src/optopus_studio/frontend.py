"""The built frontend (``frontend/dist``), which both the studio and an app serve.

Kept apart from ``app.py`` so an app's server, which has no agent, does not import it.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def mount_frontend(server: FastAPI) -> None:
    """Serves the built frontend at ``/``, when it has been built."""
    if FRONTEND.is_dir():
        with contextlib.suppress(RuntimeError):
            server.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
