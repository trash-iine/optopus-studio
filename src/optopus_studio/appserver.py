"""The server of a packaged app (docs/adr/0009): no agent, no projects, one package.

GET    /api/mode                          {"mode": "app"}
GET    /api/app                           what the package holds (AppInfo)
POST   /api/app/cases                     a new case (CaseState)
GET    /api/app/cases/{id}                a case (CaseState)
PUT    /api/app/cases/{id}/inputs/{key}?name=   give a file for an input; the body is its content
DELETE /api/app/cases/{id}/inputs/{key}   go back to the packaged data
PUT    /api/app/cases/{id}/note           {"note": str}: what the user says about the case
POST   /api/app/cases/{id}/solve          {"parameters": {...}}: check the inputs and solve
GET    /api/app/cases/{id}/export         the case as a zip, to attach in the studio
/                                         the built frontend, which shows the app
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel

from optopus_studio.apps import App, Case, export_case
from optopus_studio.frontend import mount_frontend
from optopus_studio.projects import MAX_UPLOAD_BYTES, ProjectError
from optopus_studio.protocol import AppInfo, CaseState


class SolveBody(BaseModel):
    """The body of a solve: the values the user gave the app's parameters.

    Attributes:
        parameters: Each parameter's value, by its key in app.json.
    """

    parameters: dict[str, Any] = {}


class NoteBody(BaseModel):
    """The body of a note.

    Attributes:
        note: What the user says about the case.
    """

    note: str


def create_app(package: Path, home: Path | None = None) -> FastAPI:
    """The server of one package, with the routes listed at the top of this module.

    Args:
        package: The package's zip, or the folder it unpacked into.
        home: Where the app keeps its cases; the default home when None.

    Returns:
        The server.
    """
    app_package = App.open_package(package, home)
    server = FastAPI(title=f"optopus app: {app_package.spec.title}")

    def case_of(case_id: str) -> Case:
        """A case of the app, or a 404.

        Args:
            case_id: The case's id.

        Returns:
            The case.

        Raises:
            HTTPException: There is no such case.
        """
        try:
            return app_package.case(case_id)
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @server.get("/api/mode")
    def mode() -> dict[str, str]:
        """Says that this server runs an app, not the studio.

        Returns:
            ``{"mode": "app"}``.
        """
        return {"mode": "app"}

    @server.get("/api/app")
    def info() -> AppInfo:
        """What the package holds.

        Returns:
            The app's title, inputs, parameters and revision.
        """
        return app_package.info()

    @server.post("/api/app/cases")
    def new_case() -> CaseState:
        """Opens a new case on the packaged data.

        Returns:
            The new case.
        """
        return app_package.new_case().state()

    @server.get("/api/app/cases/{case_id}")
    def get_case(case_id: str) -> CaseState:
        """A case, as the app shows it.

        Args:
            case_id: The case's id.

        Returns:
            The case.
        """
        return case_of(case_id).state()

    @server.put("/api/app/cases/{case_id}/inputs/{key}")
    async def put_input(case_id: str, key: str, name: str, request: Request) -> CaseState:
        """Gives a case a file for one of its inputs; the request's body is the file's content.

        Args:
            case_id: The case's id.
            key: The input's key in app.json.
            name: The file's name.
            request: The request, whose body is read.

        Returns:
            The case with the input set.

        Raises:
            HTTPException: The file is too large or does not fit the input.
        """
        case = case_of(case_id)
        content = await request.body()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail=f"{name} is too large")
        try:
            case.set_input(key, name, content)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.delete("/api/app/cases/{case_id}/inputs/{key}")
    def delete_input(case_id: str, key: str) -> CaseState:
        """Takes a case's input back to the packaged data.

        Args:
            case_id: The case's id.
            key: The input's key in app.json.

        Returns:
            The case without that input.

        Raises:
            HTTPException: The input cannot be removed.
        """
        case = case_of(case_id)
        try:
            case.remove_input(key)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.put("/api/app/cases/{case_id}/note")
    def put_note(case_id: str, body: NoteBody) -> CaseState:
        """Sets what the user says about a case.

        Args:
            case_id: The case's id.
            body: The note.

        Returns:
            The case with the note.

        Raises:
            HTTPException: The note cannot be kept.
        """
        case = case_of(case_id)
        try:
            case.set_note(body.note)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.post("/api/app/cases/{case_id}/solve")
    async def solve(case_id: str, body: SolveBody) -> CaseState:
        """Checks a case's inputs and solves it.

        Args:
            case_id: The case's id.
            body: The parameters' values.

        Returns:
            The case with its result.

        Raises:
            HTTPException: The inputs or parameters do not fit, or the solve failed.
        """
        case = case_of(case_id)
        try:
            await case.solve(body.parameters)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.get("/api/app/cases/{case_id}/export")
    def export(case_id: str) -> Response:
        """The case as a zip, to attach in the studio.

        Args:
            case_id: The case's id.

        Returns:
            The zip, as a download.
        """
        case = case_of(case_id)
        return Response(
            export_case(case),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="optopus-case-{case.id}.zip"'},
        )

    mount_frontend(server)
    return server
