"""The agent on Claude: a Claude Agent SDK client, with the studio's tools as an in-process MCP
server (docs/adr/0003).

Authentication is Claude Code's: the SDK runs the bundled Claude Code CLI, which uses the login
in ``~/.claude``. ``optopus_studio.cli`` removes ``ANTHROPIC_API_KEY`` from the environment
before anything starts, so a key that happens to be exported is not used instead.
"""

from __future__ import annotations

import os
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
from optopus_studio.protocol import AssistantDelta, AssistantText

SERVER = "studio"


def options(specs: list[ToolSpec], cwd: Path, resume: str | None) -> ClaudeAgentOptions:
    tools = [tool(s.name, s.description, s.input_schema)(s.call) for s in specs]
    return ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        mcp_servers={SERVER: create_sdk_mcp_server(SERVER, tools=tools)},
        # Only the studio's tools: without this, the CLI also connects the MCP servers of the
        # Claude account it signs in with (claude.ai connectors), and the agent mentions them to
        # the user.
        strict_mcp_config=True,
        allowed_tools=[f"mcp__{SERVER}__{s.name}" for s in specs],
        setting_sources=[],
        cwd=str(cwd),
        model=os.environ.get("OPTOPUS_STUDIO_CLAUDE_MODEL")
        or os.environ.get("OPTOPUS_STUDIO_MODEL")
        or None,
        include_partial_messages=True,
        resume=resume,
    )


class ClaudeBackend:
    def __init__(self, specs: list[ToolSpec], cwd: Path, resume: str | None):
        self.client = ClaudeSDKClient(options(specs, cwd, resume))

    async def open(self) -> None:
        await self.client.connect()

    async def close(self) -> None:
        await self.client.disconnect()

    async def interrupt(self) -> None:
        await self.client.interrupt()

    async def turn(self, text: str) -> AsyncIterator[AgentEvent]:
        await self.client.query(text)
        async for message in self.client.receive_response():
            for event in events(message):
                yield event


def events(message: Any) -> list[AgentEvent]:
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
                shown.append(
                    tool_activity(block.name.removeprefix(f"mcp__{SERVER}__"), block.input)
                )
        return shown
    elif isinstance(message, ResultMessage):
        error = (message.result or message.subtype) if message.is_error else None
        return [TurnResult(session_id=message.session_id, error=error)]
    return []
