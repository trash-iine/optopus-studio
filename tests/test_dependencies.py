"""The optopus the Python worker is built from and the one the Rust worker links are the same."""

import json
import os
import tomllib
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def pinned() -> tuple[str, str]:
    python = tomllib.loads((ROOT / "pyproject.toml").read_text())
    rust = tomllib.loads((ROOT / "workers" / "rust" / "Cargo.toml").read_text())
    return python["tool"]["uv"]["sources"]["optopus"]["rev"], rust["dependencies"]["optopus"]["rev"]


@pytest.mark.network
def test_the_rust_worker_links_the_core_the_python_binding_vendors():
    binding, core = pinned()
    url = (
        f"https://api.github.com/repos/trash-iine/optopus-py/contents/vendor/optopus?ref={binding}"
    )
    # CI passes its token: unauthenticated API calls are rate-limited per address.
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=15
    ) as response:
        submodule = json.load(response)
    assert submodule["type"] == "submodule"
    assert submodule["sha"] == core, "move workers/rust/Cargo.toml to the core optopus-py vendors"
