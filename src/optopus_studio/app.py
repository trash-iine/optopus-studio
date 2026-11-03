"""The HTTP and WebSocket server the browser talks to.

GET  /api/projects                       the projects (ProjectInfo), newest first
POST /api/projects                       create one
POST /api/projects/import                create one from an exported zip, the body
GET  /api/projects/{id}/export           the project as a zip to hand to someone
GET  /api/projects/{id}/revisions/{rev}  one revision (RevisionDetail)
GET  /api/projects/{id}/revisions/{rev}/package  the revision as an app package (docs/adr/0009)
GET  /api/projects/{id}/bench            the benchmark, its evaluations and tunings (BenchState)
GET  /api/mode                           {"mode": "studio"}; an app server says "app"
POST /api/projects/{id}/uploads?name=    attach a file; the body is its content
POST /api/projects/{id}/cases            attach a case an app exported; the body is its zip
WS   /api/projects/{id}/ws               ServerEvent out, ClientEvent in
/                                        the built frontend (frontend.py), when present
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, TypeAdapter, ValidationError

from optopus_studio import apps, bench
from optopus_studio.agent import AgentSession, agent_choices
from optopus_studio.frontend import mount_frontend
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import (
    AgentSelected,
    BenchState,
    ClientEvent,
    Interrupt,
    ProjectInfo,
    RevisionDetail,
    SelectAgent,
    SelectRevision,
    SetWebSearch,
    Snapshot,
    TurnEnd,
    UserMessage,
    WebSearchChanged,
)

log = logging.getLogger(__name__)
CLIENT_EVENT = TypeAdapter(ClientEvent)


class Hub:
    """A project's agent session and the browsers watching it."""

    def __init__(self, project: Project):
        """Opens the project's agent session, with no browser watching yet.

        Args:
            project: The project.
        """
        self.project = project
        self.sockets: set[WebSocket] = set()
        self.session = AgentSession(project, self.broadcast)

    async def broadcast(self, event: BaseModel) -> None:
        """Sends an event to every browser watching, dropping those that are gone.

        Args:
            event: The event.
        """
        payload = event.model_dump_json()
        for socket in list(self.sockets):
            try:
                await socket.send_text(payload)
            except Exception:
                self.sockets.discard(socket)

    def snapshot(self, rev: int | None = None) -> Snapshot:
        """Everything a browser shows of the project, at one revision.

        Args:
            rev: The revision to show; the latest when None.

        Returns:
            The snapshot. The files are the work files at the latest revision, the revision's own at
                an
            earlier one.

        Raises:
            ProjectError: There is no such revision.
        """
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
            agent=self.session.agent,
            agents=agent_choices(),
            web_search=self.session.web_search,
        )


hubs: dict[str, Hub] = {}


def hub_for(project_id: str) -> Hub:
    """The hub of a project, opened the first time it is asked for.

    Args:
        project_id: The project's id.

    Returns:
        The hub.

    Raises:
        ProjectError: There is no such project.
    """
    if project_id not in hubs:
        hubs[project_id] = Hub(Project.open(project_id))
    return hubs[project_id]


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Closes every agent session when the server stops.

    Args:
        _: The application.

    Yields:
        Nothing; the server runs while it waits.
    """
    yield
    await asyncio.gather(*(hub.session.close() for hub in hubs.values()))


app = FastAPI(title="optopus-studio", lifespan=lifespan)


@app.get("/api/mode")
def mode() -> dict[str, str]:
    """Says that this server runs the studio, not an app.

    Returns:
        ``{"mode": "studio"}``.
    """
    return {"mode": "studio"}


@app.get("/api/projects")
def list_projects() -> list[ProjectInfo]:
    """The projects, newest first.

    Returns:
        Each project's summary.
    """
    return [Project.open(project_id).info() for project_id in Project.list()]


@app.post("/api/projects")
def create_project() -> dict[str, str]:
    """Creates an empty project.

    Returns:
        ``{"id": <the new project's id>}``.
    """
    return {"id": Project.create().id}


@app.post("/api/projects/import")
async def import_project(request: Request) -> dict[str, str]:
    """Creates a project from an exported zip, the request's body.

    Args:
        request: The request, whose body is read.

    Returns:
        ``{"id": <the new project's id>}``.

    Raises:
        HTTPException: The body is not a project's zip.
    """
    try:
        return {"id": Project.import_archive(await request.body()).id}
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def open_project(project_id: str) -> Project:
    """A project, or a 404.

    Args:
        project_id: The project's id.

    Returns:
        The project.

    Raises:
        HTTPException: There is no such project.
    """
    try:
        return Project.open(project_id)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/export")
def export_project(project_id: str) -> Response:
    """The project as a zip to hand to someone.

    Args:
        project_id: The project's id.

    Returns:
        The zip, as a download.
    """
    project = open_project(project_id)
    return Response(
        project.export(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="optopus-studio-{project.id}.zip"'},
    )


@app.get("/api/projects/{project_id}/revisions/{rev}")
def get_revision(project_id: str, rev: int) -> RevisionDetail:
    """One revision of a project.

    Args:
        project_id: The project's id.
        rev: The revision.

    Returns:
        The revision's files, solve and view.

    Raises:
        HTTPException: There is no such project or revision.
    """
    project = open_project(project_id)
    try:
        files, summary, view, view_error = project.load_revision(rev)
    except ProjectError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RevisionDetail(rev=rev, files=files, summary=summary, view=view, view_error=view_error)


@app.get("/api/projects/{project_id}/bench")
def get_bench(project_id: str) -> BenchState:
    """A project's benchmark, its evaluations, tunings and profiles.

    Args:
        project_id: The project's id.

    Returns:
        The benchmark's state.
    """
    return bench.state(open_project(project_id))


@app.get("/api/projects/{project_id}/revisions/{rev}/package")
def package_revision(project_id: str, rev: int) -> Response:
    """A revision as an app package (docs/adr/0009).

    Args:
        project_id: The project's id.
        rev: The revision.

    Returns:
        The package's zip, as a download.

    Raises:
        HTTPException: The revision cannot be packaged.
    """
    project = open_project(project_id)
    try:
        data, _ = apps.package(project, rev)
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = f"optopus-app-{project.id}-r{rev}.zip"
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/projects/{project_id}/uploads")
async def upload(project_id: str, name: str, request: Request) -> dict[str, str]:
    """Attaches a file to a project; the request's body is its content.

    Args:
        project_id: The project's id.
        name: The file's name.
        request: The request, whose body is read.

    Returns:
        ``{"name": <the name the file is kept under>}``.

    Raises:
        HTTPException: The file cannot be kept.
    """
    project = open_project(project_id)
    try:
        return {"name": project.save_upload(name, await request.body())}
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/cases")
async def attach_case(project_id: str, request: Request) -> dict[str, str]:
    """Attaches a case an app exported; the request's body is its zip.

    Args:
        project_id: The project's id.
        request: The request, whose body is read.

    Returns:
        ``{"case": <the name the case is kept under>}``.

    Raises:
        HTTPException: The body is not a case's zip, or not of this project.
    """
    project = open_project(project_id)
    try:
        return {"case": apps.import_case(project, await request.body())}
    except ProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/api/projects/{project_id}/ws")
async def project_socket(socket: WebSocket, project_id: str) -> None:
    """Speaks with one browser: sends a snapshot, then answers its events until it disconnects.

    Args:
        socket: The browser's WebSocket.
        project_id: The project's id.
    """
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
                case SelectAgent():
                    try:
                        await hub.session.select(event.agent)
                    except ProjectError as exc:
                        await socket.send_text(TurnEnd(error=str(exc)).model_dump_json())
                    else:
                        await hub.broadcast(AgentSelected(agent=event.agent))
                case SetWebSearch():
                    try:
                        await hub.session.set_web_search(event.enabled)
                    except ProjectError as exc:
                        await socket.send_text(TurnEnd(error=str(exc)).model_dump_json())
                    else:
                        await hub.broadcast(WebSearchChanged(enabled=event.enabled))
    except WebSocketDisconnect:
        pass
    finally:
        hub.sockets.discard(socket)


mount_frontend(app)
