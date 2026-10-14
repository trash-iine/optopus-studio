"""The server, without the agent: projects, the snapshot, revision selection."""

import asyncio

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from optopus_studio import app as app_module
from optopus_studio.agent import Tools
from optopus_studio.projects import Project


@pytest.fixture
def client():
    app_module.hubs.clear()
    with TestClient(app_module.app) as client:
        yield client
    app_module.hubs.clear()


def test_a_new_project_starts_empty(client):
    project_id = client.post("/api/projects").json()["id"]
    assert client.get("/api/projects").json() == [project_id]
    with client.websocket_connect(f"/api/projects/{project_id}/ws") as ws:
        snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot"
    assert snapshot["revisions"] == []
    assert snapshot["busy"] is False


def test_an_unknown_project_closes_the_socket(client):
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect("/api/projects/0123456789ab/ws") as ws,
    ):
        ws.receive_json()
    assert closed.value.code == 4404


def test_an_earlier_revision_can_be_selected(client, home):
    from tests.conftest import example_project

    project = example_project("knapsack", home)
    tools = Tools(project, lambda event: asyncio.sleep(0))
    asyncio.run(tools.run_solver({"runs": 1}))
    project.write_file(
        "solve.json",
        '{"heuristic": {"kind": "LocalSearch", "neighbor": "Flip", '
        '"stop": {"max_iteration": 10}}, "runs": 1, "seed": 0}',
    )
    asyncio.run(tools.run_solver({}))

    with client.websocket_connect(f"/api/projects/{project.id}/ws") as ws:
        latest = ws.receive_json()
        assert latest["rev"] == 2
        assert latest["revisions"] == [1, 2]
        ws.send_json({"type": "select_revision", "rev": 1})
        first = ws.receive_json()
        assert first["rev"] == 1
        assert "SimulatedAnnealing" in first["files"]["solve.json"]
        assert first["view"]["views"][0]["type"] == "kpi"
        ws.send_json({"type": "select_revision", "rev": 7})
        assert "no revision 7" in ws.receive_json()["error"]
        ws.send_json({"type": "nonsense"})
        assert "bad message" in ws.receive_json()["error"]
    assert Project.open(project.id).revisions() == [1, 2]
