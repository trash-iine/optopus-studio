"""The modeling agent: a Claude Agent SDK session per project, and the tools it works through.

The agent has no built-in tools (no shell, no file access): it reads the optopus docs, writes the
four project files and runs solves only through the tools defined here, so everything it does
stays inside its project and shows up in the GUI.

Authentication is Claude Code's: the SDK runs the bundled Claude Code CLI, which uses the login
in ``~/.claude``. ``optopus_studio.cli`` removes ``ANTHROPIC_API_KEY`` from the environment
before anything starts, so a key that happens to be exported is not used instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import optopus
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
from pydantic import BaseModel, ValidationError

from optopus_studio.projects import PROJECT_FILES, Project, ProjectError
from optopus_studio.protocol import (
    AssistantDelta,
    AssistantText,
    ChatEntry,
    FilesChanged,
    RunSummary,
    SolveProgress,
    SolveRequest,
    SolveStarted,
    ToolActivity,
    TurnEnd,
    ViewUpdated,
)
from optopus_studio.runner import render_view, run_solve

log = logging.getLogger(__name__)

SERVER = "studio"
DOC_PAGES = (
    "problems",
    "formula",
    "python_problems",
    "heuristics",
    "heuristics_generic",
    "heuristics_composed",
    "heuristics_specific",
    "heuristics_exact",
    "running",
    "graphs_and_instances",
)
SOLUTION_PREVIEW = 3000
CHECK_SECONDS = 2.0
DEFAULT_SOLVE_TIMEOUT = 300.0

SYSTEM_PROMPT = """\
You are the modeling agent of optopus-studio. The user describes an optimization task in chat; \
you turn it into a model for optopus (a metaheuristics library, Python bindings over Rust), solve \
it, and show the result on the canvas next to the chat. Optimization is the point; the canvas \
exists to make its result clear.

## The project

Four files, written with write_file:

- instance.json — the data, one JSON object.
- model.py — `build(instance)` returns an optopus problem: a built-in one (optopus.Tsp, \
optopus.Vrp, optopus.JobShopScheduling, ...), an optopus.Formula, or a problem written in \
Python. Optional `encode_solution(instance, solution)` turns RunResult.solution into JSON \
(lists, numbers, strings, dicts); without it the solution must already be JSON-like.
- solve.json — `{"heuristic": {"kind": "<optopus heuristic class>", ...constructor arguments, \
"stop": {...StopCondition arguments}}, "runs": 3, "seed": 0}`. A nested heuristic is the same \
kind of dict (Iterated's "search", Restart's "heuristic", Sequential's "steps"), and a stop is a \
dict of max_iteration / max_duration_secs / max_failed_update.
- view.py — `to_view(instance, result)` returns `{"views": [...]}`. `result` has "problem", \
"higher_is_better", "runs" (each with best_objective, initial_objective, solution, trajectory, \
iterations, total_time_secs), "best_run", and "best" (the best run's dict, or null when the \
solve failed). The canvas already shows the objective per run and the convergence curve; \
view.py shows what the solution means in the user's terms.

model.py and view.py may import optopus and the standard library only.

## Views

Every view takes an optional "title".

- {"type": "kpi", "items": [{"label", "value", "unit"?}]} — headline numbers.
- {"type": "table", "columns": [str], "rows": [[cell]]}
- {"type": "gantt", "tasks": [{"lane", "label", "start", "end", "group"?}], "time_unit"?} — \
schedules; lanes are machines or people, a group (a job) shares a color.
- {"type": "route_map", "points": [{"id", "x", "y", "label"?, "kind": "node"|"depot"}], \
"routes": [{"path": [point ids], "label"?}], "closed": true} — tours and vehicle routes.
- {"type": "graph", "nodes": [{"id", "label"?, "group"?, "x"?, "y"?}], "edges": [{"source", \
"target", "weight"?, "highlight"?}]} — cuts, colorings, covers; group colors nodes.
- {"type": "bar", "categories": [str], "series": [{"name", "values"}], "stacked"?}
- {"type": "markdown", "text"} — a short note, such as which constraints are violated.
- {"type": "custom_html", "html", "height"?} — a whole HTML document in a sandboxed iframe, \
only when no view above can show it.

## How to work

1. Understand the task: the decisions, the objective, the constraints (hard or soft), the data. \
When something that changes the model is unclear, ask one short question with concrete options \
instead of guessing. When the user gave enough, go ahead. If they have no data, make up a small \
realistic instance and say so.
2. Choose the representation, the first that fits exactly: a built-in problem, then Formula, \
then a problem written in Python. Read the docs (read_docs) and the exact constructors \
(api_help) before writing model.py; do not guess the API.
3. Write the four files and call check_model. Fix what it reports until it passes.
4. Call run_solver. Check the solution against the constraints the user gave.
5. Reply briefly, in the user's language: what you modeled in a line or two, the result in the \
user's terms, and one or two things they could change next. Do not repeat what the canvas shows.

On later messages change only what the request needs, then run again. Every run_solver makes a \
revision the user can go back to.

- Keep a solve under about 10 seconds (stop.max_duration_secs) unless the user wants longer.
- A hard constraint the representation does not enforce becomes a penalty; size its weight so \
breaking it never pays, and have view.py report any violation.
- In a problem written in Python, give each neighborhood delta and random_neighbor, and use \
tuples so apply cannot change its input.
"""


def docs_dir() -> Path:
    configured = os.environ.get("OPTOPUS_STUDIO_DOCS")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "optopus-py" / "docs" / "source"


def read_doc_page(page: str) -> str:
    if page not in DOC_PAGES:
        raise ProjectError(f"unknown page {page!r}; expected one of {DOC_PAGES}")
    path = docs_dir() / f"{page}.md"
    if not path.is_file():
        raise ProjectError(
            f"the optopus-py docs are not at {docs_dir()}; set OPTOPUS_STUDIO_DOCS. "
            "Use api_help for the docstrings meanwhile."
        )
    return path.read_text()


def api_help(name: str) -> str:
    """The docstring and signature of an optopus class and of its public methods."""
    obj = getattr(optopus, name, None)
    if obj is None or name.startswith("_"):
        public = [n for n in dir(optopus) if not n.startswith("_") and n != "optopus"]
        raise ProjectError(f"optopus has no {name!r}; it has {public}")
    parts = [f"# optopus.{name}{getattr(obj, '__text_signature__', None) or ''}"]
    parts.append(inspect.cleandoc(obj.__doc__ or ""))
    for attr in sorted(dir(obj)):
        if attr.startswith("_"):
            continue
        member = getattr(obj, attr)
        doc = getattr(member, "__doc__", None)
        if callable(member) and doc:
            signature = getattr(member, "__text_signature__", None) or ""
            parts.append(f"## {name}.{attr}{signature}\n{inspect.cleandoc(doc)}")
    return "\n\n".join(parts)


def solve_timeout(heuristic: dict[str, Any], runs: int) -> float:
    configured = os.environ.get("OPTOPUS_STUDIO_SOLVE_TIMEOUT")
    if configured:
        return float(configured)
    seconds = (heuristic.get("stop") or {}).get("max_duration_secs")
    if isinstance(seconds, int | float):
        return min(seconds * runs + 30.0, DEFAULT_SOLVE_TIMEOUT * 4)
    return DEFAULT_SOLVE_TIMEOUT


def describe(summary: RunSummary, solution_preview: int = SOLUTION_PREVIEW) -> str:
    """What the agent reads back after a solve."""
    lines = []
    if summary.problem:
        direction = "higher" if summary.higher_is_better else "lower"
        lines.append(f"problem {summary.problem}, {direction} objective is better")
    for run in summary.runs:
        lines.append(
            f"run {run.run}: best {run.best_objective:g} (initial {run.initial_objective:g}), "
            f"{run.iterations} iterations in {run.total_time_secs:.3f}s, best found at "
            f"iteration {run.best_iteration} ({len(run.trajectory)} improvements)"
        )
    if summary.best_run is not None:
        best = summary.runs[summary.best_run]
        solution = json.dumps(best.solution)
        if len(solution) > solution_preview:
            solution = solution[:solution_preview] + f"... ({len(solution)} characters)"
        lines.append(f"best run {best.run}, solution: {solution}")
    if summary.error:
        lines.append(f"ERROR at stage '{summary.error.stage}': {summary.error.message}")
        if summary.error.traceback:
            lines.append(summary.error.traceback[-3000:])
    return "\n".join(lines)


def text_result(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "is_error": is_error}


def object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


Broadcast = Callable[[BaseModel], Awaitable[None]]


class Tools:
    """The agent's tools, bound to one project and to the GUI's broadcast."""

    def __init__(self, project: Project, broadcast: Broadcast):
        self.project = project
        self.broadcast = broadcast

    def solve_request(self, overrides: dict[str, Any]) -> SolveRequest:
        try:
            solve = json.loads(self.project.read_file("solve.json"))
            instance = json.loads(self.project.read_file("instance.json"))
        except json.JSONDecodeError as exc:
            raise ProjectError(f"invalid JSON: {exc}") from exc
        heuristic = dict(solve.get("heuristic") or {})
        if "max_duration_secs" in overrides:
            heuristic["stop"] = {
                **(heuristic.get("stop") or {}),
                "max_duration_secs": overrides["max_duration_secs"],
            }
        try:
            return SolveRequest(
                model_path=str(self.project.work / "model.py"),
                instance=instance,
                heuristic=heuristic,
                runs=overrides.get("runs", solve.get("runs", 1)),
                seed=overrides.get("seed", solve.get("seed", 0)),
            )
        except ValidationError as exc:
            raise ProjectError(f"solve.json does not describe a solve: {exc}") from exc

    async def read_docs(self, args: dict[str, Any]) -> dict[str, Any]:
        return text_result(read_doc_page(args["page"]))

    async def api_help(self, args: dict[str, Any]) -> dict[str, Any]:
        return text_result(api_help(args["name"]))

    async def read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return text_result(self.project.read_file(args["name"]))

    async def write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        self.project.write_file(args["name"], args["content"])
        await self.broadcast(FilesChanged(files=self.project.files()))
        return text_result(f"wrote {args['name']} ({len(args['content'])} characters)")

    async def check_model(self, args: dict[str, Any]) -> dict[str, Any]:
        """One short run, without a revision: does the model build, run, encode and render?"""
        request = self.solve_request({"runs": 1})
        stop = dict(request.heuristic.get("stop") or {})
        stop["max_duration_secs"] = min(stop.get("max_duration_secs") or CHECK_SECONDS, 2.0)
        request.heuristic["stop"] = stop

        async def ignore(_: RunSummary) -> None:
            pass

        summary = await run_solve(request, 0, self.project.work, ignore, 60.0)
        report = describe(summary)
        if summary.error:
            return text_result(report, is_error=True)
        view, error = await render_view(self.project.work / "view.py", request.instance, summary)
        if error:
            return text_result(f"{report}\n\nview.py failed:\n{error}", is_error=True)
        assert view is not None
        kinds = ", ".join(v.type for v in view.views)
        return text_result(f"{report}\n\nview.py ok: {kinds}. Now call run_solver.")

    async def run_solver(self, args: dict[str, Any]) -> dict[str, Any]:
        request = self.solve_request(args)
        rev = self.project.snapshot()
        rev_dir = self.project.rev_dir(rev)
        request.model_path = str(rev_dir / "model.py")
        await self.broadcast(SolveStarted(rev=rev, runs=request.runs))

        async def progress(summary: RunSummary) -> None:
            await self.broadcast(SolveProgress(rev=rev, summary=summary))

        timeout = solve_timeout(request.heuristic, request.runs)
        summary = await run_solve(request, rev, rev_dir, progress, timeout)
        self.project.save_result(rev, summary)
        view, error = await render_view(rev_dir / "view.py", request.instance, summary)
        self.project.save_view(rev, view, error)
        await self.broadcast(ViewUpdated(rev=rev, view=view, error=error))

        report = f"revision {rev}\n{describe(summary)}"
        if error:
            report += f"\n\nview.py failed:\n{error}"
        elif view:
            report += f"\n\nthe canvas shows: {', '.join(v.type for v in view.views)}"
        return text_result(report, is_error=bool(summary.error or error))

    def server(self):
        def guarded(fn):
            async def call(args: dict[str, Any]) -> dict[str, Any]:
                try:
                    return await fn(args)
                except ProjectError as exc:
                    return text_result(str(exc), is_error=True)

            return call

        page = {"type": "string", "enum": list(DOC_PAGES)}
        file_name = {"type": "string", "enum": list(PROJECT_FILES)}
        tools = [
            tool(
                "read_docs",
                "Read a page of the optopus-py user guide. 'problems' compares the built-in "
                "problems and their solution shapes; 'formula' and 'python_problems' are the two "
                "ways to write your own; 'heuristics*' say which heuristic to use and how to set "
                "it; 'running' covers stop conditions and what a run reports.",
                object_schema({"page": page}, ["page"]),
            )(guarded(self.read_docs)),
            tool(
                "api_help",
                "The docstring and constructor signature of an optopus class (e.g. 'Tsp', "
                "'Formula', 'SimulatedAnnealing') and of its methods.",
                object_schema({"name": {"type": "string"}}, ["name"]),
            )(guarded(self.api_help)),
            tool(
                "read_file",
                "Read a project file as it is now.",
                object_schema({"name": file_name}, ["name"]),
            )(guarded(self.read_file)),
            tool(
                "write_file",
                "Write a whole project file (instance.json, model.py, view.py or solve.json).",
                object_schema(
                    {"name": file_name, "content": {"type": "string"}}, ["name", "content"]
                ),
            )(guarded(self.write_file)),
            tool(
                "check_model",
                "Build the model and run it once for at most 2 seconds, then render view.py. "
                "Reports errors with tracebacks. Makes no revision and does not change the canvas.",
                object_schema({}, []),
            )(guarded(self.check_model)),
            tool(
                "run_solver",
                "Solve with solve.json, make a new revision, and show its result on the canvas. "
                "Optional overrides: runs, seed, max_duration_secs (per run).",
                object_schema(
                    {
                        "runs": {"type": "integer", "minimum": 1, "maximum": 100},
                        "seed": {"type": "integer", "minimum": 0},
                        "max_duration_secs": {"type": "number", "exclusiveMinimum": 0},
                    },
                    [],
                ),
            )(guarded(self.run_solver)),
        ]
        allowed = [f"mcp__{SERVER}__{t.name}" for t in tools]
        return create_sdk_mcp_server(SERVER, tools=tools), allowed


def tool_summary(block: ToolUseBlock) -> ToolActivity:
    name = block.name.removeprefix(f"mcp__{SERVER}__")
    detail = block.input.get("name") or block.input.get("page") or ""
    return ToolActivity(name=name, summary=str(detail))


class AgentSession:
    """One project's conversation. A single task owns the SDK client, fed by a queue."""

    def __init__(self, project: Project, broadcast: Broadcast):
        self.project = project
        self.broadcast = broadcast
        self.tools = Tools(project, broadcast)
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.busy = False
        self.client: ClaudeSDKClient | None = None
        self.task: asyncio.Task[None] | None = None

    def options(self) -> ClaudeAgentOptions:
        server, allowed = self.tools.server()
        return ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            mcp_servers={SERVER: server},
            allowed_tools=allowed,
            setting_sources=[],
            cwd=str(self.project.work),
            model=os.environ.get("OPTOPUS_STUDIO_MODEL") or None,
            include_partial_messages=True,
            resume=self.project.meta().get("session_id"),
        )

    def submit(self, text: str) -> bool:
        if self.busy:
            return False
        self.busy = True
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop())
        self.inbox.put_nowait(text)
        return True

    async def interrupt(self) -> None:
        if self.client and self.busy:
            await self.client.interrupt()

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task

    async def _loop(self) -> None:
        try:
            async with ClaudeSDKClient(self.options()) as client:
                self.client = client
                while True:
                    text = await self.inbox.get()
                    await self._turn(client, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("agent session failed")
            self.busy = False
            await self.broadcast(TurnEnd(error=f"the agent stopped: {exc}"))
        finally:
            self.client = None

    async def _turn(self, client: ClaudeSDKClient, text: str) -> None:
        self.project.append_chat(ChatEntry(role="user", text=text))
        error = None
        try:
            await client.query(text)
            async for message in client.receive_response():
                await self._handle(message)
                if isinstance(message, ResultMessage):
                    self.project.set_meta(session_id=message.session_id)
                    if message.is_error:
                        error = message.result or message.subtype
        finally:
            self.busy = False
            await self.broadcast(TurnEnd(error=error))

    async def _handle(self, message: Any) -> None:
        if isinstance(message, StreamEvent):
            event = message.event
            delta = event.get("delta") or {}
            if event.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                await self.broadcast(AssistantDelta(text=delta["text"]))
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    self.project.append_chat(ChatEntry(role="assistant", text=block.text))
                    await self.broadcast(AssistantText(text=block.text))
                elif isinstance(block, ToolUseBlock):
                    activity = tool_summary(block)
                    label = f"{activity.name} {activity.summary}".strip()
                    self.project.append_chat(ChatEntry(role="tool", text=label))
                    await self.broadcast(activity)
