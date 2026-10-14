"""The HTTP and WebSocket server the browser talks to.

GET  /api/projects          project ids, newest first
POST /api/projects          create one
WS   /api/projects/{id}/ws  ServerEvent out, ClientEvent in
/                           the built frontend (frontend/dist), when present
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, TypeAdapter, ValidationError

from optopus_studio.agent import AgentSession
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import (
    ClientEvent,
    Interrupt,
    SelectRevision,
    Snapshot,
    TurnEnd,
    UserMessage,
)

log = logging.getLogger(__name__)
CLIENT_EVENT = TypeAdapter(ClientEvent)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class Hub:
    """A project's agent session and the browsers watching it."""

    def __init__(self, project: Project):
        self.project = project
        self.sockets: set[WebSocket] = set()
        self.session = AgentSession(project, self.broadcast)

    async def broadcast(self, event: BaseModel) -> None:
        payload = event.model_dump_json()
        for socket in list(self.sockets):
            try:
                await socket.send_text(payload)
            except Exception:
                self.sockets.discard(socket)

    def snapshot(self, rev: int | None = None) -> Snapshot:
        revisions = self.project.revisions()
        files = self.project.files()
        summary = view = view_error = None
        if rev is None and revisions:
            rev = revisions[-1]
        if rev is not None:
            rev_files, summary, view, view_error = self.project.load_revision(rev)
            if rev != revisions[-1]:
                files = rev_files
        return Snapshot(
            project=self.project.id,
            chat=self.project.chat(),
            files=files,
            revisions=revisions,
            rev=rev,
            summary=summary,
            view=view,
            view_error=view_error,
            busy=self.session.busy,
        )


hubs: dict[str, Hub] = {}


def hub_for(project_id: str) -> Hub:
    if project_id not in hubs:
        hubs[project_id] = Hub(Project.open(project_id))
    return hubs[project_id]


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await asyncio.gather(*(hub.session.close() for hub in hubs.values()))


app = FastAPI(title="optopus-studio", lifespan=lifespan)


@app.get("/api/projects")
def list_projects() -> list[str]:
    return Project.list()


@app.post("/api/projects")
def create_project() -> dict[str, str]:
    return {"id": Project.create().id}


@app.websocket("/api/projects/{project_id}/ws")
async def project_socket(socket: WebSocket, project_id: str) -> None:
    try:
        hub = hub_for(project_id)
    except ProjectError as exc:
        await socket.close(code=4404, reason=str(exc))
        return
    await socket.accept()
    hub.sockets.add(socket)
    try:
        await socket.send_text(hub.snapshot().model_dump_json())
        while True:
            try:
                event = CLIENT_EVENT.validate_json(await socket.receive_text())
            except ValidationError as exc:
                await socket.send_text(TurnEnd(error=f"bad message: {exc}").model_dump_json())
                continue
            match event:
                case UserMessage():
                    if not hub.session.submit(event.text):
                        await socket.send_text(
                            TurnEnd(error="the agent is still working").model_dump_json()
                        )
                case SelectRevision():
                    try:
                        await socket.send_text(hub.snapshot(event.rev).model_dump_json())
                    except ProjectError as exc:
                        await socket.send_text(TurnEnd(error=str(exc)).model_dump_json())
                case Interrupt():
                    await hub.session.interrupt()
    except WebSocketDisconnect:
        pass
    finally:
        hub.sockets.discard(socket)


if FRONTEND.is_dir():
    with contextlib.suppress(RuntimeError):
        app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
