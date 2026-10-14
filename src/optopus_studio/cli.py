"""``optopus-studio``: start the server on localhost."""

from __future__ import annotations

import argparse
import logging
import os

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
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    dropped = use_claude_code_login()
    if dropped:
        logging.info("ignoring %s; the agent uses the Claude Code login", ", ".join(dropped))

    import uvicorn

    uvicorn.run("optopus_studio.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
