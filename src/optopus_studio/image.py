"""An app's Docker image (docs/adr/0010): a package with everything it runs on.

Whoever runs it needs Docker and nothing else. ``docker/app.Dockerfile`` installs the studio without
the agent, builds the frontend and the package's Rust port, and solves the packaged data once before
the image is done. ``build_image`` runs it on a package and can save the image as a tar to hand
over.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from optopus_studio.apps import IMAGE_VARIABLE, package_manifest, read_package
from optopus_studio.projects import ProjectError

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "docker" / "app.Dockerfile"
# Most customer machines, Windows ones under Docker Desktop included, run amd64 images.
DEFAULT_PLATFORM = "linux/amd64"
PORT = 8766
_TAG = re.compile(r"\A[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?\Z")


def default_tag(manifest: dict[str, Any]) -> str:
    """The image's tag when none is given: ``optopus-app-<project>:r<rev>``.

    Args:
        manifest: The package's manifest.

    Returns:
        The tag.
    """
    return f"optopus-app-{manifest['project']}:r{manifest['rev']}"


def labels(manifest: dict[str, Any]) -> dict[str, str]:
    """The OCI labels that say which project, revision and optopus an image holds.

    Args:
        manifest: The package's manifest.

    Returns:
        Each label's value, by its key.
    """
    return {
        "org.opencontainers.image.title": manifest["title"],
        "org.opencontainers.image.created": manifest["packaged_at"],
        "io.optopus-studio.project": str(manifest["project"]),
        "io.optopus-studio.rev": str(manifest["rev"]),
        "io.optopus-studio.optopus": str(manifest.get("optopus")),
    }


def build_command(
    package_dir: Path,
    manifest: dict[str, Any],
    tag: str,
    platform: str,
    test: bool,
) -> list[str]:
    """The ``docker build`` command line for a package.

    Args:
        package_dir: The build context that holds the package's zip alone.
        manifest: The package's manifest, for the labels.
        tag: The image's tag.
        platform: The platform to build for, such as ``linux/amd64``.
        test: Whether the build solves the packaged data once.

    Returns:
        The command's arguments.
    """
    command = [
        "docker",
        "build",
        "--file",
        str(DOCKERFILE),
        "--platform",
        platform,
        "--build-context",
        f"package={package_dir}",
        "--build-arg",
        f"{IMAGE_VARIABLE}={tag}",
        "--build-arg",
        f"SELF_TEST={1 if test else 0}",
        "--tag",
        tag,
    ]
    for key, value in labels(manifest).items():
        command += ["--label", f"{key}={value}"]
    return [*command, str(REPO)]


def docker_problem() -> str | None:
    """Why images cannot be built here, if they cannot.

    Returns:
        What is wrong with Docker, or None when it is installed and running.
    """
    if shutil.which("docker") is None:
        return "docker is not installed; see https://docs.docker.com/get-docker/"
    ready = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if ready.returncode != 0:
        reason = (ready.stderr.strip().splitlines() or ["docker info failed"])[-1]
        return f"docker is not running ({reason}); start Docker Desktop or the daemon"
    return None


def build_image(
    package: Path,
    tag: str | None = None,
    platform: str = DEFAULT_PLATFORM,
    save: Path | None = None,
    test: bool = True,
) -> str:
    """Builds the image of a package; with ``save``, also writes it as a tar.

    Args:
        package: The package's zip, or the folder it unpacked into.
        tag: The image's tag; ``default_tag`` when None.
        platform: The platform to build for.
        save: The tar file to write the image to, if any.
        test: Whether the build solves the packaged data once.

    Returns:
        The image's tag.

    Raises:
        ProjectError: The tag is invalid, Docker is not usable, or the build or save failed.
    """
    data = read_package(package)
    manifest = package_manifest(data)
    tag = tag or default_tag(manifest)
    if not _TAG.match(tag):
        raise ProjectError(f"{tag!r} is not a valid image tag")
    problem = docker_problem()
    if problem:
        raise ProjectError(problem)
    # The package's build context holds the package alone, not whatever sits next to it.
    with tempfile.TemporaryDirectory() as context:
        (Path(context) / "package.zip").write_bytes(data)
        command = build_command(Path(context), manifest, tag, platform, test)
        if subprocess.run(command).returncode != 0:
            raise ProjectError(f"docker build failed for {package.name}")
    saving = ["docker", "save", "--output", str(save), tag]
    if save is not None and subprocess.run(saving).returncode != 0:
        raise ProjectError(f"docker save failed for {tag}")
    return tag


def run_command(tag: str, volume: str = "optopus-app-data") -> str:
    """How the image's user starts it: on this machine only, with its cases in a volume.

    Args:
        tag: The image's tag.
        volume: The Docker volume that keeps the app's cases.

    Returns:
        The ``docker run`` command line.
    """
    return f"docker run -d -p 127.0.0.1:{PORT}:{PORT} -v {volume}:/data {tag}"
