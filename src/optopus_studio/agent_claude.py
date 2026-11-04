"""The agent on Claude: a Claude Agent SDK client, with the studio's tools as an MCP server.

The tools are an in-process MCP server (docs/adr/0003). Authentication is Claude Code's: the SDK
runs the bundled Claude Code CLI, which uses the login in ``~/.claude``. ``optopus_studio.cli``
removes ``ANTHROPIC_API_KEY`` from the environment before anything starts, so a key that happens to
be exported is not used instead.

The models to choose from are the ones the CLI lists when it connects, so a model Claude Code adds
is offered without a change here.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from optopus_studio.agent import (
    SYSTEM_PROMPT,
    AgentEvent,
    ToolSpec,
    TurnResult,
    tool_activity,
)
from optopus_studio.protocol import AssistantDelta, AssistantText, ModelChoice

SERVER = "studio"
# Claude Code's own tools the agent gets when the project lets it search the web (docs/adr/0016),
# and the names the chat shows their calls under.
WEB_TOOLS = {"WebSearch": "web_search", "WebFetch": "web_fetch"}
# The model Claude Code runs on unless told otherwise, as its list of models names it.
DEFAULT_MODEL = "default"


def env_model() -> str | None:
    """The model the environment sets for Claude, if it sets one.

    Returns:
        ``OPTOPUS_STUDIO_CLAUDE_MODEL``, else ``OPTOPUS_STUDIO_MODEL``, else None.
    """
    return (
        os.environ.get("OPTOPUS_STUDIO_CLAUDE_MODEL")
        or os.environ.get("OPTOPUS_STUDIO_MODEL")
        or None
    )


def options(
    specs: list[ToolSpec],
    cwd: Path,
    resume: str | None,
    web: bool = False,
    model: str | None = None,
    effort: str | None = None,
) -> ClaudeAgentOptions:
    """The SDK's options: the studio's tools only, plus web search when the project allows it.

    Args:
        specs: The studio's tools.
        cwd: The project's directory.
        resume: The session to resume, if any.
        web: Whether the agent may search and fetch the web (docs/adr/0016).
        model: The model the project chose, if any; else the environment's, else Claude Code's.
        effort: The effort the project chose, if any; else the model's default.

    Returns:
        The options.
    """
    tools = [tool(s.name, s.description, s.input_schema)(s.call) for s in specs]
    web_tools = list(WEB_TOOLS) if web else []
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        tools=web_tools,
        mcp_servers={SERVER: create_sdk_mcp_server(SERVER, tools=tools)},
        # Only the studio's tools: without this, the CLI also connects the MCP servers of the
        # Claude account it signs in with (claude.ai connectors), and the agent mentions them to
        # the user.
        strict_mcp_config=True,
        allowed_tools=[f"mcp__{SERVER}__{s.name}" for s in specs] + web_tools,
        setting_sources=[],
        cwd=str(cwd),
        model=model or env_model(),
        effort=effort,  # type: ignore[arg-type]
        include_partial_messages=True,
        resume=resume,
    )


class ClaudeBackend:
    """The agent's session on Claude."""

    def __init__(
        self,
        specs: list[ToolSpec],
        cwd: Path,
        resume: str | None,
        web: bool = False,
        model: str | None = None,
        effort: str | None = None,
    ):
        """Prepares a client; ``open`` connects it.

        Args:
            specs: The studio's tools.
            cwd: The project's directory.
            resume: The session to resume, if any.
            web: Whether the agent may search and fetch the web.
            model: The model the project chose, if any.
            effort: The effort the project chose, if any.
        """
        self.client = ClaudeSDKClient(options(specs, cwd, resume, web, model, effort))

    async def open(self) -> None:
        """Connects to Claude Code."""
        await self.client.connect()

    async def close(self) -> None:
        """Disconnects from Claude Code."""
        await self.client.disconnect()

    async def interrupt(self) -> None:
        """Stops the turn in progress."""
        await self.client.interrupt()

    async def turn(self, text: str) -> AsyncIterator[AgentEvent]:
        """Sends the user's message and streams the turn.

        Args:
            text: The user's message.

        Yields:
            What the chat shows of the turn, ending with the turn's result.
        """
        await self.client.query(text)
        async for message in self.client.receive_response():
            for event in events(message):
                yield event


def events(message: Any) -> list[AgentEvent]:
    """What the chat shows of one message from the SDK.

    Args:
        message: A message of the SDK's stream.

    Returns:
        Text as it streams, whole texts, tool calls and the turn's result; empty for the rest.
    """
    if isinstance(message, StreamEvent):
        event = message.event
        delta = event.get("delta") or {}
        if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
            return [AssistantDelta(text=delta["text"])]
    elif isinstance(message, AssistantMessage):
        shown: list[AgentEvent] = []
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                shown.append(AssistantText(text=block.text))
            elif isinstance(block, ToolUseBlock):
                name = WEB_TOOLS.get(block.name) or block.name.removeprefix(f"mcp__{SERVER}__")
                shown.append(tool_activity(name, block.input))
        return shown
    elif isinstance(message, ResultMessage):
        error = (message.result or message.subtype) if message.is_error else None
        return [TurnResult(session_id=message.session_id, error=error)]
    return []


async def list_models() -> list[ModelChoice]:
    """The models Claude Code offers, as the CLI lists them when it connects.

    It connects without tools, settings or a prompt, so nothing is sent to a model.

    Returns:
        The models, in the CLI's order.
    """
    with tempfile.TemporaryDirectory() as cwd:
        client = ClaudeSDKClient(
            ClaudeAgentOptions(tools=[], setting_sources=[], strict_mcp_config=True, cwd=cwd)
        )
        await client.connect()
        try:
            info = await client.get_server_info() or {}
        finally:
            await client.disconnect()
    default = env_model() or DEFAULT_MODEL
    return [model_choice(entry, default) for entry in info.get("models") or []]


def model_choice(entry: dict[str, Any], default: str) -> ModelChoice:
    """One entry of the CLI's list of models, as the studio offers it.

    Args:
        entry: The entry: ``value``, ``displayName``, ``description``, and ``supportsEffort`` and
            ``supportedEffortLevels`` for a model that takes an effort.
        default: The model the agent runs on unless the project chooses one.

    Returns:
        The model.
    """
    efforts = entry.get("supportedEffortLevels") if entry.get("supportsEffort") else None
    return ModelChoice(
        id=entry["value"],
        name=entry.get("displayName") or entry["value"],
        description=entry.get("description") or None,
        efforts=list(efforts or []),
        is_default=entry["value"] == default,
    )
