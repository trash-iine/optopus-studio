"""The optopus-py user guide the agent reads, at the commit of the installed optopus.

uv builds optopus from a commit of optopus-py (docs/adr/0008), and the wheel leaves the docs out.
A page is fetched from GitHub at that commit the first time it is read and kept under
``<home>/docs/<commit>/``, so the agent reads the guide of the code it runs. ``OPTOPUS_STUDIO_DOCS``
points at a ``docs/source`` directory instead, such as an optopus-py checkout being worked on.
"""

from __future__ import annotations

import json
import os
import urllib.request
from importlib import metadata
from pathlib import Path

from optopus_studio.projects import ProjectError, studio_home

RAW = "https://raw.githubusercontent.com/trash-iine/optopus-py"
FETCH_TIMEOUT = 15.0


def installed_commit() -> str | None:
    """The optopus-py commit uv built the installed optopus from, if it came from git."""
    try:
        recorded = metadata.distribution("optopus").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    vcs = (json.loads(recorded) if recorded else {}).get("vcs_info") or {}
    return vcs.get("commit_id")


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
        return response.read().decode()


def read_page(page: str) -> str:
    configured = os.environ.get("OPTOPUS_STUDIO_DOCS")
    if configured:
        path = Path(configured) / f"{page}.md"
        if not path.is_file():
            raise ProjectError(
                f"{path} does not exist; OPTOPUS_STUDIO_DOCS should be optopus-py's docs/source"
            )
        return path.read_text()
    commit = installed_commit()
    if commit is None:
        raise ProjectError(
            "the installed optopus was not built from a git commit, so its docs are unknown; set "
            "OPTOPUS_STUDIO_DOCS to optopus-py's docs/source. Use api_help meanwhile."
        )
    cached = studio_home() / "docs" / commit / f"{page}.md"
    if cached.is_file():
        return cached.read_text()
    try:
        text = fetch(f"{RAW}/{commit}/docs/source/{page}.md")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProjectError(
            f"could not fetch the docs page {page!r} of optopus-py {commit[:12]}: {exc}. "
            "Use api_help meanwhile."
        ) from exc
    cached.parent.mkdir(parents=True, exist_ok=True)
    partial = cached.with_suffix(".part")
    partial.write_text(text)
    partial.replace(cached)
    return text
