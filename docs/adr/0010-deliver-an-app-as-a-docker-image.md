# 0010. Deliver a packaged app as a Docker image

- Status: Accepted
- Date: 2026-10-15

## Context

A packaged app (ADR 0009) is how a model leaves the studio: a developer shapes the model with a
customer in the studio, packages a revision once it is agreed, and the customer tries it on their
own data. What they find, from data that cannot be solved to a result that does not match their
sense of the problem, comes back to the studio as cases, and a later revision is packaged again.

ADR 0009 left the person running an app needing this repository, uv, and cargo for a Rust port.
A customer has none of these, and which operating system they use is not known in advance. The
app also does not need the agent, but the studio installs the Claude Agent SDK, whose wheel holds
the Claude Code CLI (about 100 MB).

## Options

1. A Docker image per package: the runtime, the package and its built Rust port.
2. A runtime installed once (a Python package without the agent), with packages handed over as
   zips.
3. A standalone executable per operating system (PyInstaller or similar).

## Decision

Option 1.

- `optopus-studio image <package>` builds `docker/app.Dockerfile` with the package as the build
  context `package`, tags it `optopus-app-<project>:r<rev>`, and with `--save` writes it as a tar
  to hand over. The customer runs `docker load` and `docker run`; nothing else is installed.
- The image installs the studio without the `studio` dependency group, which holds the Agent
  SDK. An app's code (`appserver.py`, `apps.py`, `frontend.py`) never imports `agent.py`, and a
  test checks it.
- The package's Rust port is built while the image is built (`app --prepare`), and `rust.build`
  returns a binary it built before without asking for cargo, so the image holds no toolchain.
- Before the image is done, it solves the packaged data once, briefly (`app --self-test`), so a
  broken image is not handed over.
- The image keeps its cases in the volume `/data`. A newer image of a later revision runs on the
  same volume.
- A case carries a note, the app user's own words about it, and the image it ran in. The agent
  treats a note on a solved case as feedback on the model, not as a failure.
- The images are `linux/amd64` by default, which Docker Desktop runs on Windows, macOS and Linux.

A runtime installed once (option 2) still needs Python and uv on the customer's machine, and
updating it apart from the packages lets the two drift. Executables (option 3) need a build per
operating system and do not fit the worker and viewer subprocesses, which run `python -m`.

## Consequences

- The person running an app needs Docker, and nothing from this repository. The developer needs
  Docker to build images; on Apple Silicon an amd64 image builds optopus under emulation, which
  takes about ten minutes.
- An image is about 300 MB unpacked and a tar of about 60 MB, most of it Python and optopus;
  each revision handed over is a new image.
- ADR 0009's consequence that an app's user needs this repository installed no longer holds for
  the images. `optopus-studio app <package>` still runs a package from a checkout.
