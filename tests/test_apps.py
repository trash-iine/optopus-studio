"""Apps: app.json, packaging a revision, and solving a case with the packaged model."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from optopus_studio.agent import Tools
from optopus_studio.apps import (
    App,
    check_spec,
    check_table,
    coerce,
    load_spec,
    package,
)
from optopus_studio.appserver import create_app
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import AppInput, AppParameter
from tests.conftest import EXAMPLES, example_project

ITEMS = b"name,weight,value\nmap,1,15\nlamp,2,25\ntent,9,70\n"


def knapsack_files():
    return (
        load_spec((EXAMPLES / "knapsack" / "app.json").read_text()),
        json.loads((EXAMPLES / "knapsack" / "instance.json").read_text()),
        json.loads((EXAMPLES / "knapsack" / "solve.json").read_text()),
    )


def test_the_example_app_fits_its_project():
    assert check_spec(*knapsack_files()) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda s, i: s.inputs[0].__setattr__("key", "goods"), "no such key"),
        (lambda s, i: i["items"][1].pop("value"), "'value' is empty in row 3"),
        (lambda s, i: s.parameters[0].__setattr__("target", "instance.limit"), "no limit"),
        (lambda s, i: s.parameters[0].__setattr__("target", "instance.items.0"), "inside"),
        (lambda s, i: i.__setitem__("capacity", -1), "below the minimum"),
        (lambda s, i: s.parameters.append(s.parameters[0]), "repeated parameter names"),
    ],
)
def test_an_app_that_does_not_fit_says_why(change, problem):
    spec, instance, solve = knapsack_files()
    change(spec, instance)
    assert any(problem in p for p in check_spec(spec, instance, solve))


def test_a_table_is_checked_row_by_row_in_spreadsheet_rows():
    spec_input = load_spec((EXAMPLES / "knapsack" / "app.json").read_text()).inputs[0]
    rows = [
        {"name": "a", "weight": 1, "value": 2},
        {"name": "b", "weight": "heavy", "value": 2},
        {"name": "c", "weight": 3, "value": None},
    ]
    assert check_table(spec_input, rows) == [
        "Items: 'weight' should be number: 'heavy' in row 3",
        "Items: 'value' is empty in row 4",
    ]
    assert check_table(spec_input, [{"name": "a"}]) == [
        "Items: the column(s) ['weight', 'value'] are missing; the file has ['name']"
    ]
    assert check_table(spec_input, []) == ["Items: the file has no rows"]
    assert check_table(AppInput(key="k", label="Any"), {"free": "form"}) == []


@pytest.mark.parametrize(
    ("kind", "value", "result"),
    [
        ("integer", "4", 4),
        ("number", "10", 10),
        ("number", " 2.5 ", 2.5),
        ("integer", 4.0, 4),
        ("integer", 4.5, "whole number"),
        ("number", "x", "expected a number"),
        ("number", True, "expected a number"),
        ("number", 11, "above the maximum"),
        ("boolean", "yes", "yes or no"),
    ],
)
def test_a_parameter_value_is_checked_against_its_type(kind, value, result):
    p = AppParameter(name="p", label="P", type=kind, target="solve.runs", min=1, max=10)
    if isinstance(result, str):
        with pytest.raises(ValueError, match=result):
            coerce(p, value)
    else:
        assert coerce(p, value) == result


def test_app_json_must_be_an_app(home):
    project = Project.create(home)
    with pytest.raises(ProjectError, match="not a valid app"):
        project.write_file("app.json", '{"inputs": []}')


def test_check_app_reports_the_inputs_and_parameters(home):
    tools = Tools(example_project("knapsack", home), lambda event: asyncio.sleep(0))
    report = asyncio.run(tools.check_app({}))["content"][0]["text"]
    assert "input items (optional, else the packaged data): packaged 7 rows" in report
    assert "parameter capacity: packaged value 20" in report


def solved_project(home, name="knapsack"):
    project = example_project(name, home)
    asyncio.run(Tools(project, lambda event: asyncio.sleep(0)).run_solver({"runs": 1}))
    return project


def test_only_a_revision_with_app_json_is_packaged(home):
    project = solved_project(home, "tsp")
    with pytest.raises(ProjectError, match=r"no app\.json"):
        package(project, 1)


def packaged(home, tmp_path):
    data, _ = package(solved_project(home), 1)
    path = tmp_path / "bag.zip"
    path.write_bytes(data)
    return path


def test_a_package_opens_as_the_revision_it_was_made_from(home, tmp_path):
    path = packaged(home, tmp_path)
    app = App.open_package(path, home)
    info = app.info()
    assert info.spec.title == "Pack the bag"
    assert info.rev == 1
    assert info.defaults == {"capacity": 20, "runs": 3}
    assert info.sample is not None
    assert info.sample.runs
    assert info.sample_view is not None
    # Packaged again, the same revision opens where its cases are.
    project = Project.open(app.manifest["project"], home)
    again = tmp_path / "again.zip"
    again.write_bytes(package(project, 1)[0])
    assert App.open_package(again, home).root == app.root


def solve(case, values):
    async def go():
        await case.solve(values)
        if case.task:
            await case.task

    asyncio.run(go())


def test_a_case_solves_the_users_data_with_their_parameters(home, tmp_path):
    case = App.open_package(packaged(home, tmp_path), home).new_case()
    case.set_input("items", "mine.csv", ITEMS)
    assert case.problems == []
    solve(case, {"capacity": 3, "runs": "2"})
    state = case.state()
    assert state.status == "solved", state
    assert state.inputs[0].file == "mine.csv"
    assert state.inputs[0].rows == 3
    assert state.parameters == {"capacity": 3, "runs": 2}
    assert len(state.summary.runs) == 2
    assert state.summary.runs[state.summary.best_run].best_objective == 40
    assert json.loads((case.root / "instance.json").read_text())["capacity"] == 3


@pytest.mark.parametrize(
    ("content", "values", "problem"),
    [
        (b"name,weight\nmap,1\n", {}, "['value'] are missing"),
        (ITEMS, {"capacity": -2}, "below the minimum"),
        (ITEMS, {"speed": 3}, "no parameters ['speed']"),
    ],
)
def test_a_case_that_cannot_be_solved_says_why_before_solving(
    home, tmp_path, content, values, problem
):
    case = App.open_package(packaged(home, tmp_path), home).new_case()
    case.set_input("items", "mine.csv", content)
    solve(case, values)
    state = case.state()
    assert state.status == "draft"
    assert any(problem in p for p in state.problems), state.problems
    assert state.summary is None


def test_a_model_that_rejects_the_data_fails_the_case_with_its_message(home, tmp_path):
    case = App.open_package(packaged(home, tmp_path), home).new_case()
    case.set_input("items", "mine.csv", b"name,weight,value\nmap,1,15\nghost,0,5\n")
    solve(case, {})
    state = case.state()
    assert state.status == "failed"
    assert "'ghost' (row 3) weighs 0" in state.summary.error.message


def test_a_case_is_found_again_after_the_app_restarts(home, tmp_path):
    path = packaged(home, tmp_path)
    case = App.open_package(path, home).new_case()
    case.set_input("items", "mine.csv", ITEMS)
    solve(case, {})
    again = App.open_package(path, home).case(case.id).state()
    assert again.status == "solved"
    assert again.inputs[0].rows == 3
    assert again.view is not None


@pytest.mark.parametrize(
    "files",
    [{"model/model.py": "x"}, {"optopus-studio-app.json": "{}", "model/../evil.py": "x"}],
)
def test_a_zip_that_is_not_a_package_is_refused(home, tmp_path, files):
    import zipfile

    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(ProjectError, match="not an app package"):
        App.open_package(path, home)


def test_the_app_server_runs_a_case_end_to_end(home, tmp_path):
    with TestClient(create_app(packaged(home, tmp_path), home)) as client:
        assert client.get("/api/mode").json() == {"mode": "app"}
        assert client.get("/api/app").json()["spec"]["title"] == "Pack the bag"
        case_id = client.post("/api/app/cases").json()["id"]
        put = client.put(
            f"/api/app/cases/{case_id}/inputs/items", params={"name": "mine.csv"}, content=ITEMS
        )
        assert put.json()["inputs"][0]["rows"] == 3
        bad = client.put(
            f"/api/app/cases/{case_id}/inputs/nope", params={"name": "x.csv"}, content=ITEMS
        )
        assert bad.status_code == 400
        started = client.post(f"/api/app/cases/{case_id}/solve", json={"parameters": {}})
        assert started.json()["status"] in ("solving", "solved")
        deadline = time.monotonic() + 30
        while client.get(f"/api/app/cases/{case_id}").json()["status"] == "solving":
            assert time.monotonic() < deadline
            time.sleep(0.1)
        state = client.get(f"/api/app/cases/{case_id}").json()
        assert state["status"] == "solved"
        assert state["view"]["views"][0]["type"] == "kpi"
        assert client.get("/api/app/cases/0123456789ab").status_code == 404


def test_the_studio_packages_a_revision_for_download(home):
    from optopus_studio import app as studio

    project = solved_project(home)
    with TestClient(studio.app) as client:
        assert client.get("/api/mode").json() == {"mode": "studio"}
        response = client.get(f"/api/projects/{project.id}/revisions/1/package")
        assert response.headers["content-type"] == "application/zip"
        assert f"optopus-app-{project.id}-r1.zip" in response.headers["content-disposition"]
        missing = client.get(f"/api/projects/{project.id}/revisions/2/package")
        assert missing.status_code == 400


# --- cases, out of an app and into the studio --------------------------------------------------


def app_and_project(home, tmp_path):
    path = packaged(home, tmp_path)
    app = App.open_package(path, home)
    return app, Project.open(app.manifest["project"], home)


def exported(case):
    from optopus_studio.apps import export_case

    return export_case(case)


def test_a_refused_case_carries_its_files_and_problems(home, tmp_path):
    import io
    import zipfile

    app, _ = app_and_project(home, tmp_path)
    case = app.new_case()
    case.set_input("items", "mine.csv", b"name,weight\nmap,1\n")
    solve(case, {"capacity": 3})
    with zipfile.ZipFile(io.BytesIO(exported(case))) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("optopus-studio-case.json"))
    assert names == {"optopus-studio-case.json", "inputs/items/mine.csv"}
    assert manifest["app"]["rev"] == 1
    assert manifest["status"] == "draft"
    assert manifest["parameters"] == {"capacity": 3}
    assert "['value'] are missing" in manifest["problems"][0]


def test_the_studio_reads_and_reproduces_a_case_that_failed(home, tmp_path):
    from optopus_studio.apps import describe_case, import_case, load_case

    app, project = app_and_project(home, tmp_path)
    case = app.new_case()
    case.set_input("items", "mine.csv", b"name,weight,value\nmap,1,15\nghost,0,5\n")
    solve(case, {"capacity": 7})
    case_id = import_case(project, exported(case))
    report = describe_case(project, case_id, lambda path: f"<{path.name}>")
    assert "packaged from revision 1 of this project" in report
    assert "the solve failed at build: ValueError: item 'ghost' (row 3) weighs 0" in report
    assert "<mine.csv>" in report
    assert load_case(project, case_id).startswith("instance.json is now the instance the app")
    instance = json.loads(project.read_file("instance.json"))
    assert instance["capacity"] == 7
    assert [item["name"] for item in instance["items"]] == ["map", "ghost"]


def test_a_refused_case_is_rebuilt_as_the_app_would_have(home, tmp_path):
    from optopus_studio.apps import import_case, load_case

    app, project = app_and_project(home, tmp_path)
    case = app.new_case()
    case.set_input("items", "mine.csv", b"name,weight,value\nmap,1,15\nlamp,two,25\n")
    solve(case, {"capacity": 3})
    case_id = import_case(project, exported(case))
    assert "app refused it" in load_case(project, case_id)
    instance = json.loads(project.read_file("instance.json"))
    assert instance["capacity"] == 3
    assert instance["items"][1]["weight"] == "two"


@pytest.mark.parametrize(
    ("files", "problem"),
    [
        ({"inputs/items/a.csv": "x"}, "not a case"),
        ({"optopus-studio-case.json": '{"format": 1, "case": "../x"}'}, "studio can read"),
        (
            {
                "optopus-studio-case.json": '{"format": 1, "case": "0123456789ab"}',
                "inputs/../a.csv": "x",
            },
            "holds no",
        ),
        (
            {
                "optopus-studio-case.json": '{"format": 1, "case": "0123456789ab"}',
                "result.json": "{}",
            },
            "broken",
        ),
    ],
)
def test_a_zip_that_is_not_a_case_is_refused(home, files, problem):
    import io
    import zipfile

    from optopus_studio.apps import import_case

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    with pytest.raises(ProjectError, match=problem):
        import_case(Project.create(home), buffer.getvalue())


def test_cases_travel_with_a_shared_project(home, tmp_path):
    from optopus_studio.apps import import_case, project_cases

    app, project = app_and_project(home, tmp_path)
    case = app.new_case()
    case.set_input("items", "mine.csv", ITEMS)
    case_id = import_case(project, exported(case))
    copy = Project.import_archive(project.export(), tmp_path / "elsewhere")
    assert project_cases(copy) == [case_id]


def test_a_case_goes_from_the_app_server_to_the_studio_and_its_agent(home, tmp_path):
    from optopus_studio import app as studio

    path = packaged(home, tmp_path)
    project = Project.open(App.open_package(path, home).manifest["project"], home)
    with TestClient(create_app(path, home)) as client:
        case_id = client.post("/api/app/cases").json()["id"]
        client.put(
            f"/api/app/cases/{case_id}/inputs/items", params={"name": "mine.csv"}, content=b"x"
        )
        archive = client.get(f"/api/app/cases/{case_id}/export")
        assert f"optopus-case-{case_id}.zip" in archive.headers["content-disposition"]
    with TestClient(studio.app) as client:
        attached = client.post(f"/api/projects/{project.id}/cases", content=archive.content)
        assert attached.json() == {"case": case_id}
        assert client.post(f"/api/projects/{project.id}/cases", content=b"x").status_code == 400
    tools = Tools(project, lambda event: asyncio.sleep(0))
    listed = asyncio.run(tools.read_case({}))["content"][0]["text"]
    assert listed == f"case:{case_id}"
    report = asyncio.run(tools.read_case({"case": f"case:{case_id}"}))["content"][0]["text"]
    assert "input items:" in report


# --- handing an app over (docs/adr/0010) -------------------------------------------------------


def test_a_case_carries_its_users_note_into_the_studio(home, tmp_path, monkeypatch):
    from optopus_studio.apps import describe_case, import_case

    monkeypatch.setenv("OPTOPUS_APP_IMAGE", "optopus-app-x:r1")
    app, project = app_and_project(home, tmp_path)
    case = app.new_case()
    solve(case, {})
    case.set_note("地図より毛布を優先してほしい")
    assert app.case(case.id).state().note == "地図より毛布を優先してほしい"
    with pytest.raises(ProjectError, match="longer than"):
        case.set_note("x" * 10_001)
    import_case(project, exported(app.case(case.id)))
    report = describe_case(project, case.id, lambda path: "")
    assert "run in the image optopus-app-x:r1" in report
    assert "in their words:\n地図より毛布を優先してほしい" in report


def test_the_app_server_keeps_a_note(home, tmp_path):
    with TestClient(create_app(packaged(home, tmp_path), home)) as client:
        case_id = client.post("/api/app/cases").json()["id"]
        saved = client.put(f"/api/app/cases/{case_id}/note", json={"note": "too slow"})
        assert saved.json()["note"] == "too slow"
        assert client.get(f"/api/app/cases/{case_id}").json()["note"] == "too slow"
        long = client.put(f"/api/app/cases/{case_id}/note", json={"note": "x" * 10_001})
        assert long.status_code == 400


def test_a_package_opens_from_the_folder_it_was_unpacked_into(home, tmp_path):
    import zipfile

    path = packaged(home, tmp_path)
    folder = tmp_path / "unpacked"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(folder)
    (folder / ".DS_Store").write_bytes(b"\0")
    assert App.open_package(folder, home).root == App.open_package(path, home).root


def test_a_package_is_checked_and_solved_before_it_becomes_an_image(home, tmp_path):
    app = App.open_package(packaged(home, tmp_path), home)
    assert asyncio.run(app.prebuild()) is None
    summary = asyncio.run(app.self_test(seconds=0.2))
    assert len(summary.runs) == 1
    app.instance["capacity"] = -1
    with pytest.raises(ProjectError, match="does not fit the package"):
        asyncio.run(app.prebuild())
