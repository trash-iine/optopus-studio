"""``optopus-studio``: start the studio on localhost; ``optopus-studio app <package>`` runs a
packaged app instead."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

# The agent signs in with Claude Code's login. An exported key would take precedence in the
# Claude Code CLI the SDK starts, so drop it before anything reads the environment.
CREDENTIAL_VARIABLES = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def use_claude_code_login() -> list[str]:
    return [name for name in CREDENTIAL_VARIABLES if os.environ.pop(name, None) is not None]


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat-driven optimization studio on optopus.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="restart on source changes")
    commands = parser.add_subparsers(dest="command")
    run_app = commands.add_parser(
        "app", help="run a packaged app, without the agent (docs/adr/0009)"
    )
    run_app.add_argument("package", type=Path, help="a zip the studio's Package button made")
    run_app.add_argument("--host", default="127.0.0.1")
    run_app.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    import uvicorn

    if args.command == "app":
        from optopus_studio.appserver import create_app
        from optopus_studio.projects import ProjectError

        try:
            server = create_app(args.package)
        except (OSError, ProjectError) as exc:
            parser.error(f"cannot open {args.package}: {exc}")
        uvicorn.run(server, host=args.host, port=args.port)
        return

    dropped = use_claude_code_login()
    if dropped:
        logging.info("ignoring %s; the agent uses the Claude Code login", ", ".join(dropped))
    uvicorn.run("optopus_studio.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
