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
    parameters: dict[str, Any] = {}


class NoteBody(BaseModel):
    note: str


def create_app(package: Path, home: Path | None = None) -> FastAPI:
    app_package = App.open_package(package, home)
    server = FastAPI(title=f"optopus app: {app_package.spec.title}")

    def case_of(case_id: str) -> Case:
        try:
            return app_package.case(case_id)
        except ProjectError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @server.get("/api/mode")
    def mode() -> dict[str, str]:
        return {"mode": "app"}

    @server.get("/api/app")
    def info() -> AppInfo:
        return app_package.info()

    @server.post("/api/app/cases")
    def new_case() -> CaseState:
        return app_package.new_case().state()

    @server.get("/api/app/cases/{case_id}")
    def get_case(case_id: str) -> CaseState:
        return case_of(case_id).state()

    @server.put("/api/app/cases/{case_id}/inputs/{key}")
    async def put_input(case_id: str, key: str, name: str, request: Request) -> CaseState:
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
        case = case_of(case_id)
        try:
            case.remove_input(key)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.put("/api/app/cases/{case_id}/note")
    def put_note(case_id: str, body: NoteBody) -> CaseState:
        case = case_of(case_id)
        try:
            case.set_note(body.note)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.post("/api/app/cases/{case_id}/solve")
    async def solve(case_id: str, body: SolveBody) -> CaseState:
        case = case_of(case_id)
        try:
            await case.solve(body.parameters)
        except ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return case.state()

    @server.get("/api/app/cases/{case_id}/export")
    def export(case_id: str) -> Response:
        case = case_of(case_id)
        return Response(
            export_case(case),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="optopus-case-{case.id}.zip"'},
        )

    mount_frontend(server)
    return server
