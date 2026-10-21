"""The agent on Codex: a ``codex app-server`` per session, spoken to as JSON-RPC over its stdin
and stdout, with the studio's tools as dynamic tools (docs/adr/0012).

Codex calls a dynamic tool by asking the client (``item/tool/call``), so the tools run here, in
the studio's process, as they do for Claude. Its own tools (shell, apply_patch, web search, MCP,
images, plugins) are turned off with ``-c`` overrides, and the thread runs read-only with no
approvals; a request for one is answered with an error.

Authentication is the Codex login (``codex login``, kept in ``$CODEX_HOME``). The app-server
starts without ``OPENAI_API_KEY`` and ``CODEX_API_KEY``, so an exported key is not used instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib.metadata
import json
import logging
import os
import re
import shutil
import subprocess
import tomllib
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from optopus_studio.agent import (
    SYSTEM_PROMPT,
    AgentError,
    AgentEvent,
    SessionLost,
    ToolSpec,
    TurnResult,
    text_result,
    tool_activity,
)
from optopus_studio.protocol import AssistantDelta, AssistantText

log = logging.getLogger(__name__)

# The release the studio was built and checked against; dynamic tools are an experimental part
# of the app-server protocol, so older ones may lack what it needs.
MIN_VERSION = (0, 153, 0)
CREDENTIAL_VARIABLES = ("OPENAI_API_KEY", "CODEX_API_KEY")
# Codex's own tools and the instructions that come with them, none of which the agent may use.
FEATURES_OFF = (
    "shell_tool",
    "unified_exec",
    "view_image",
    "apps",
    "plugins",
    "multi_agent",
    "image_generation",
    "browser_use",
    "computer_use",
    "memories",
    "sleep_tool",
    "goals",
    "tool_suggest",
    "skill_search",
)
SETTINGS = (
    'web_search="disabled"',
    "skills.include_instructions=false",
    "skills.bundled.enabled=false",
    "project_doc_max_bytes=0",
    "include_permissions_instructions=false",
    "include_environment_context=false",
    "include_apps_instructions=false",
    "include_collaboration_mode_instructions=false",
)
LINE_LIMIT = 64 * 1024 * 1024
UNSUPPORTED = "optopus-studio does not offer this; ask the user in your reply instead"


def codex_binary() -> str | None:
    return shutil.which(os.environ.get("OPTOPUS_STUDIO_CODEX") or "codex")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


@functools.cache
def version_of(binary: str) -> tuple[int, ...] | str:
    """``codex --version`` as numbers, or why it could not be read."""
    try:
        out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"`{binary} --version` failed: {exc}"
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", out.stdout)
    if found is None:
        return f"`{binary} --version` printed no version: {out.stdout or out.stderr}".strip()
    return tuple(int(part) for part in found.groups())


def codex_unavailable() -> str | None:
    """Why the agent cannot run on Codex here, or None when it can."""
    binary = codex_binary()
    if binary is None:
        named = os.environ.get("OPTOPUS_STUDIO_CODEX")
        if named:
            return f"OPTOPUS_STUDIO_CODEX={named} is not an executable"
        return "Codex is not installed: see https://developers.openai.com/codex/cli"
    version = version_of(binary)
    if isinstance(version, str):
        return version
    if version < MIN_VERSION:
        found, need = (".".join(map(str, v)) for v in (version, MIN_VERSION))
        return f"Codex {found} is too old, the studio needs {need} or later: run `codex update`"
    return None


def configured_mcp_servers(home: Path) -> list[str]:
    try:
        config = tomllib.loads((home / "config.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    servers = config.get("mcp_servers")
    return list(servers) if isinstance(servers, dict) else []


def config_overrides(home: Path) -> list[str]:
    """The ``-c`` overrides: Codex's own tools off, and the MCP servers of its config too."""
    overrides = [f"features.{name}=false" for name in FEATURES_OFF] + list(SETTINGS)
    overrides += [
        f"mcp_servers.{json.dumps(n)}.enabled=false" for n in configured_mcp_servers(home)
    ]
    return overrides


def dynamic_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "inputSchema": spec.input_schema,
    }


def thread_params(cwd: Path) -> dict[str, Any]:
    params: dict[str, Any] = {
        "baseInstructions": SYSTEM_PROMPT,
        "cwd": str(cwd),
        "sandbox": "read-only",
        "approvalPolicy": "never",
    }
    if model := os.environ.get("OPTOPUS_STUDIO_CODEX_MODEL"):
        params["model"] = model
    return params


def studio_version() -> str:
    try:
        return importlib.metadata.version("optopus-studio")
    except importlib.metadata.PackageNotFoundError:
        return "0"


class RpcError(Exception):
    pass


class CodexBackend:
    def __init__(self, specs: list[ToolSpec], cwd: Path, resume: str | None):
        self.specs = {spec.name: spec for spec in specs}
        self.cwd = cwd
        self.thread_id = resume
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.next_id = 0
        self.events: asyncio.Queue[AgentEvent | Exception] = asyncio.Queue()
        self.tasks: set[asyncio.Task[None]] = set()
        self.stderr: deque[str] = deque(maxlen=20)
        self.turn_id: str | None = None
        self.turn_error: str | None = None

    async def open(self) -> None:
        reason = codex_unavailable()
        binary = codex_binary()
        if reason or binary is None:
            raise AgentError(reason or "Codex is not installed")
        env = {k: v for k, v in os.environ.items() if k not in CREDENTIAL_VARIABLES}
        overrides = [arg for o in config_overrides(codex_home()) for arg in ("-c", o)]
        self.process = await asyncio.create_subprocess_exec(
            binary,
            "app-server",
            *overrides,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=self.cwd,
            limit=LINE_LIMIT,
        )
        self.spawn(self.read())
        self.spawn(self.read_stderr())
        await self.request(
            "initialize",
            {
                "clientInfo": {"name": "optopus-studio", "version": studio_version()},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.send({"method": "initialized"})
        account = await self.request("account/read", {})
        if account.get("account") is None and account.get("requiresOpenaiAuth", True):
            raise AgentError(
                "Codex is not signed in: run `codex login` in a terminal, then send the message "
                "again"
            )
        params = thread_params(self.cwd)
        if self.thread_id:
            try:
                await self.request(
                    "thread/resume", {**params, "threadId": self.thread_id, "excludeTurns": True}
                )
            except RpcError as exc:
                raise SessionLost(f"the Codex session cannot be resumed: {exc}") from exc
        else:
            started = await self.request(
                "thread/start",
                {**params, "dynamicTools": [dynamic_tool(s) for s in self.specs.values()]},
            )
            self.thread_id = started["thread"]["id"]

    async def close(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

    async def interrupt(self) -> None:
        if self.turn_id:
            await self.request(
                "turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id}
            )

    async def turn(self, text: str) -> AsyncIterator[AgentEvent]:
        # What a late notification left behind belongs to no turn; that Codex stopped still does.
        for _ in range(self.events.qsize()):
            event = self.events.get_nowait()
            self.events.task_done()
            if isinstance(event, Exception):
                self.events.put_nowait(event)
        self.turn_error = None
        started = await self.request(
            "turn/start",
            {"threadId": self.thread_id, "input": [{"type": "text", "text": text}]},
        )
        self.turn_id = started["turn"]["id"]
        try:
            while True:
                event = await self.events.get()
                try:
                    if isinstance(event, Exception):
                        raise event
                    yield event
                finally:
                    self.events.task_done()
                if isinstance(event, TurnResult):
                    return
        finally:
            self.turn_id = None

    # --- JSON-RPC ------------------------------------------------------------------------------

    def spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send(self, message: dict[str, Any]) -> None:
        assert self.process is not None
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = future
        await self.send({"id": self.next_id, "method": method, "params": params})
        return await future

    async def read(self) -> None:
        assert self.process is not None
        assert self.process.stdout is not None
        try:
            async for line in self.process.stdout:
                message = json.loads(line)
                if "method" not in message:
                    self.resolve(message)
                elif "id" in message:
                    self.spawn(self.answer(message))
                else:
                    self.notice(message["method"], message.get("params") or {})
        except Exception as exc:
            log.exception("reading codex app-server failed")
            self.stopped(AgentError(f"the agent stopped: {exc}"))
            return
        tail = "\n".join(self.stderr)
        self.stopped(AgentError(f"Codex stopped{': ' + tail if tail else ''}"))

    async def read_stderr(self) -> None:
        assert self.process is not None
        assert self.process.stderr is not None
        async for line in self.process.stderr:
            text = line.decode(errors="replace").rstrip()
            self.stderr.append(text)
            log.debug("codex: %s", text)

    def stopped(self, error: AgentError) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        self.pending.clear()
        self.events.put_nowait(error)

    def resolve(self, message: dict[str, Any]) -> None:
        future = self.pending.pop(message.get("id"), None)  # type: ignore[arg-type]
        if future is None or future.done():
            return
        if "error" in message:
            future.set_exception(RpcError(message["error"].get("message", "error")))
        else:
            future.set_result(message.get("result") or {})

    def notice(self, method: str, params: dict[str, Any]) -> None:
        if params.get("threadId") != self.thread_id:
            return
        if method == "item/agentMessage/delta":
            self.events.put_nowait(AssistantDelta(text=params["delta"]))
        elif method == "item/completed":
            item = params.get("item") or {}
            if item.get("type") == "agentMessage" and (item.get("text") or "").strip():
                self.events.put_nowait(AssistantText(text=item["text"]))
        elif method == "error" and not params.get("willRetry"):
            self.turn_error = (params.get("error") or {}).get("message")
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            error = None
            if turn.get("status") == "failed":
                error = (turn.get("error") or {}).get("message") or self.turn_error or "failed"
            self.events.put_nowait(TurnResult(session_id=self.thread_id, error=error))

    async def answer(self, message: dict[str, Any]) -> None:
        method, params = message["method"], message.get("params") or {}
        if method != "item/tool/call":
            await self.send(
                {"id": message["id"], "error": {"code": -32601, "message": UNSUPPORTED}}
            )
            return
        name, args = params.get("tool", ""), params.get("arguments") or {}
        spec = self.specs.get(name)
        if spec is None:
            result = text_result(f"no tool {name!r}", is_error=True)
        else:
            self.events.put_nowait(tool_activity(name, args))
            # The chat shows the call before what it does (FilesChanged, a solve) reaches the GUI,
            # as with Claude; a call outside a turn is not held up by it.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.events.join(), 5 if self.turn_id else 0)
            try:
                result = await spec.call(args)
            except Exception as exc:
                log.exception("tool %s failed", name)
                result = text_result(f"{name} failed: {exc}", is_error=True)
        text = "\n".join(c["text"] for c in result["content"] if c.get("type") == "text")
        with contextlib.suppress(ConnectionError):
            await self.send(
                {
                    "id": message["id"],
                    "result": {
                        "contentItems": [{"type": "inputText", "text": text}],
                        "success": not result.get("is_error", False),
                    },
                }
            )
