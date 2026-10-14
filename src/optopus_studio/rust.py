"""Building a project's Rust port (``rust/main.rs``) into a solver worker.

The port is one file; the studio wraps it in a crate that depends on ``workers/rust``
(``optopus-studio-worker``), builds it with cargo, and keeps the binary under a hash of
everything that went into it. A revision's port is therefore built once, and switching back to
an earlier revision costs nothing. All builds share one target directory, so optopus itself is
compiled only the first time.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from optopus_studio.projects import studio_home

WORKER_LIB = Path(__file__).resolve().parents[2] / "workers" / "rust"
RUST_FILE = "rust/main.rs"
BUILD_LOG_LIMIT = 8000

# Release code, but compiled for a quick turnaround: a port is rebuilt inside a chat turn.
CARGO_TOML = """\
[package]
name = "studio-model"
version = "0.1.0"
edition = "2024"
publish = false

[dependencies]
optopus-studio-worker = {{ path = "{lib}" }}

[profile.release]
opt-level = 3
codegen-units = 16
incremental = true
"""

_lock = asyncio.Lock()


@dataclass
class Build:
    binary: Path | None
    log: str
    seconds: float
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.binary is not None


def cargo() -> str | None:
    return shutil.which("cargo")


def rust_dir() -> Path:
    configured = os.environ.get("OPTOPUS_STUDIO_RUST_DIR")
    return Path(configured) if configured else studio_home() / "rust"


def _fingerprint(main_rs: str) -> str:
    digest = hashlib.sha256()
    digest.update(CARGO_TOML.encode())
    digest.update(main_rs.encode())
    lib_files = [WORKER_LIB / "Cargo.toml", *sorted((WORKER_LIB / "src").rglob("*.rs"))]
    for path in lib_files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def cached_binary(main_rs: str) -> Path | None:
    binary = rust_dir() / "bin" / _fingerprint(main_rs)
    return binary if binary.is_file() else None


async def build(main_rs: str) -> Build:
    """Builds the port, or returns the binary an identical port was built into before. An app's
    image holds that binary and no cargo (docs/adr/0010)."""
    key = _fingerprint(main_rs)
    binary = rust_dir() / "bin" / key
    if binary.is_file():
        return Build(binary, "", 0.0, cached=True)
    if cargo() is None:
        return Build(None, "cargo is not installed; see https://rustup.rs", 0.0)
    async with _lock:
        if binary.is_file():
            return Build(binary, "", 0.0, cached=True)
        crate = rust_dir() / "crates" / key
        (crate / "src").mkdir(parents=True, exist_ok=True)
        (crate / "Cargo.toml").write_text(CARGO_TOML.format(lib=WORKER_LIB.as_posix()))
        (crate / "src" / "main.rs").write_text(main_rs)
        target = rust_dir() / "target"
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            "cargo",
            "build",
            "--release",
            "--quiet",
            "--message-format=short",
            cwd=crate,
            env={**os.environ, "CARGO_TARGET_DIR": str(target)},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        seconds = time.monotonic() - started
        log = output.decode(errors="replace")
        if process.returncode != 0:
            return Build(None, log[-BUILD_LOG_LIMIT:], seconds)
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target / "release" / "studio-model", binary)
        return Build(binary, log[-BUILD_LOG_LIMIT:], seconds)
