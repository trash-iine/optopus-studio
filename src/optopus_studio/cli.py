"""``optopus-studio``: start the studio on localhost; ``optopus-studio app <package>`` runs a
packaged app instead, and ``optopus-studio image <package>`` builds the app's Docker image."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

# The agent on Claude signs in with Claude Code's login. An exported key would take precedence in
# the Claude Code CLI the SDK starts, so drop it before anything reads the environment. (The agent
# on Codex starts its app-server without OpenAI's keys: agent_codex.py.)
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def use_claude_code_login() -> list[str]:
    return [name for name in CREDENTIAL_VARIABLES if os.environ.pop(name, None) is not None]


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat-driven optimization studio on optopus.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="restart on source changes")
    parser.add_argument(
        "--agent",
        choices=("claude", "codex"),
        help="the agent a new project starts on (each project can switch in the chat); the "
        "first available by default",
    )
    commands = parser.add_subparsers(dest="command")
    run_app = commands.add_parser(
        "app", help="run a packaged app, without the agent (docs/adr/0009)"
    )
    run_app.add_argument(
        "package",
        type=Path,
        help="a zip the studio's Package button made, or the folder it unpacked into",
    )
    run_app.add_argument("--host", default="127.0.0.1")
    run_app.add_argument("--port", type=int, default=8766)
    checks = run_app.add_mutually_exclusive_group()
    checks.add_argument(
        "--prepare",
        action="store_true",
        help="check the package and build its Rust port, then exit",
    )
    checks.add_argument(
        "--self-test", action="store_true", help="solve the packaged data once, then exit"
    )
    image = commands.add_parser(
        "image", help="build a packaged app's Docker image, to hand over (docs/adr/0010)"
    )
    image.add_argument(
        "package",
        type=Path,
        help="a zip the studio's Package button made, or the folder it unpacked into",
    )
    image.add_argument("--tag", help="the image's tag; optopus-app-<project>:r<rev> by default")
    image.add_argument("--platform", help="the platform to build for; linux/amd64 by default")
    image.add_argument("--save", type=Path, help="also write the image to this tar file")
    image.add_argument(
        "--no-test", action="store_true", help="skip solving the packaged data in the image"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    import uvicorn

    if args.command == "image":
        build_image(parser, args)
        return
    if args.command == "app":
        if args.prepare or args.self_test:
            check_app(parser, args.package, args.self_test)
            return
        from optopus_studio.appserver import create_app
        from optopus_studio.projects import ProjectError

        try:
            server = create_app(args.package)
        except (OSError, ProjectError) as exc:
            parser.error(f"cannot open {args.package}: {exc}")
        uvicorn.run(server, host=args.host, port=args.port)
        return

    from optopus_studio.agent import agent_choices

    if args.agent:
        os.environ["OPTOPUS_STUDIO_AGENT"] = args.agent
    choices = {c.name: c for c in agent_choices()}
    named = os.environ.get("OPTOPUS_STUDIO_AGENT")
    if named and named not in choices:
        parser.error(f"OPTOPUS_STUDIO_AGENT={named}: expected one of {', '.join(choices)}")
    if named and not choices[named].available:
        parser.error(f"the agent cannot run on {named}: {choices[named].reason}")
    if not any(c.available for c in choices.values()):
        reasons = "; ".join(f"{c.name}: {c.reason}" for c in choices.values())
        parser.error(f"the studio needs an agent, and none can run here ({reasons})")

    dropped = use_claude_code_login()
    if dropped:
        names = ", ".join(dropped)
        logging.info("ignoring %s; the agent on Claude uses the Claude Code login", names)
    uvicorn.run("optopus_studio.app:app", host=args.host, port=args.port, reload=args.reload)


def check_app(parser: argparse.ArgumentParser, package: Path, self_test: bool) -> None:
    """What an app's image runs while it is built (docker/app.Dockerfile)."""
    from optopus_studio.apps import App
    from optopus_studio.projects import ProjectError

    try:
        app = App.open_package(package)
        if self_test:
            summary = asyncio.run(app.self_test())
            best = summary.runs[summary.best_run].best_objective if summary.runs else None
            print(f"{app.spec.title}: the packaged data solves (best objective {best})")
        else:
            binary = asyncio.run(app.prebuild())
            print(f"{app.spec.title}: ready" + (f", Rust port at {binary}" if binary else ""))
    except (OSError, ProjectError) as exc:
        parser.exit(1, f"{package}: {exc}\n")


def build_image(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    from optopus_studio.image import DEFAULT_PLATFORM, build_image, run_command
    from optopus_studio.projects import ProjectError

    try:
        tag = build_image(
            args.package,
            tag=args.tag,
            platform=args.platform or DEFAULT_PLATFORM,
            save=args.save,
            test=not args.no_test,
        )
    except (OSError, ProjectError) as exc:
        parser.exit(1, f"{args.package}: {exc}\n")
    steps = [f"docker load -i {args.save.name}"] if args.save else []
    steps += [run_command(tag), "then open http://127.0.0.1:8766"]
    print(f"built {tag}" + (f" and saved it to {args.save}" if args.save else ""))
    print("whoever runs it:\n" + "\n".join(f"  {step}" for step in steps))


if __name__ == "__main__":
    main()
