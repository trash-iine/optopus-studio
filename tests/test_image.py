"""An app's Docker image (docs/adr/0010): what goes into it, without running Docker."""

import subprocess
import sys

import pytest

from optopus_studio import image
from optopus_studio.apps import package_manifest
from optopus_studio.projects import ProjectError
from tests.test_apps import packaged


def test_an_app_runs_without_the_agent():
    code = "import sys, optopus_studio.appserver, optopus_studio.image, optopus_studio.cli; "
    code += "print('claude_agent_sdk' in sys.modules)"
    imported = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert imported.stdout.strip() == "False", imported.stderr


def test_the_build_is_named_and_labeled_after_the_package(home, tmp_path):
    manifest = package_manifest(packaged(home, tmp_path).read_bytes())
    tag = image.default_tag(manifest)
    assert tag == f"optopus-app-{manifest['project']}:r1"
    command = image.build_command(tmp_path, manifest, tag, "linux/amd64", test=False)
    assert command[:2] == ["docker", "build"]
    assert command[-1] == str(image.REPO)
    assert f"package={tmp_path}" in command
    assert f"OPTOPUS_APP_IMAGE={tag}" in command
    assert "SELF_TEST=0" in command
    assert "org.opencontainers.image.title=Pack the bag" in command
    assert image.DOCKERFILE.is_file()


def test_no_image_is_built_without_docker(home, tmp_path, monkeypatch):
    path = packaged(home, tmp_path)
    monkeypatch.setattr(image, "docker_problem", lambda: "docker is not installed")
    with pytest.raises(ProjectError, match="docker is not installed"):
        image.build_image(path)
    with pytest.raises(ProjectError, match="not a valid image tag"):
        image.build_image(path, tag="Bad Tag")


def test_the_image_says_how_to_start_it():
    assert image.run_command("optopus-app-x:r1") == (
        "docker run -d -p 127.0.0.1:8766:8766 -v optopus-app-data:/data optopus-app-x:r1"
    )


@pytest.mark.parametrize(
    ("flag", "said"), [("--prepare", "Pack the bag: ready"), ("--self-test", "solves")]
)
def test_the_image_build_checks_the_package_through_the_cli(home, tmp_path, flag, said):
    path = packaged(home, tmp_path)
    command = [sys.executable, "-m", "optopus_studio.cli", "app", str(path), flag]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert said in done.stdout
    broken = subprocess.run([*command[:4], str(tmp_path / "none.zip"), flag], capture_output=True)
    assert broken.returncode == 1


@pytest.mark.docker
def test_an_image_serves_the_app_with_no_studio_around_it(home, tmp_path):
    import json
    import platform
    import time
    import urllib.request

    native = "linux/arm64" if platform.machine() in ("arm64", "aarch64") else "linux/amd64"
    tag = image.build_image(packaged(home, tmp_path), tag="optopus-app-test:ci", platform=native)
    run = ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::8766", tag]
    container = subprocess.run(run, capture_output=True, text=True, check=True).stdout.strip()
    try:
        ports = ["docker", "port", container, "8766"]
        bound = subprocess.run(ports, capture_output=True, text=True, check=True).stdout
        port = bound.split(":")[-1].strip()
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(f"{url}/api/app", timeout=5) as response:
                    info = json.load(response)
                break
            except OSError:
                assert time.monotonic() < deadline, "the app did not start"
                time.sleep(1)
        assert info["spec"]["title"] == "Pack the bag"
        with urllib.request.urlopen(url, timeout=5) as response:
            assert b'<div id="root">' in response.read()
        inside = subprocess.run(
            ["docker", "exec", container, "sh", "-c", "command -v cargo; echo $OPTOPUS_APP_IMAGE"],
            capture_output=True,
            text=True,
        )
        assert inside.stdout.strip() == tag
        sdk = ["docker", "exec", container, "python", "-c", "import claude_agent_sdk"]
        assert subprocess.run(sdk, capture_output=True).returncode != 0
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
