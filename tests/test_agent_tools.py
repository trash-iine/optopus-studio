"""The agent's tools, called directly: no model is involved."""

import asyncio
import json

import pytest

from optopus_studio import docs
from optopus_studio.agent import (
    DOC_PAGES,
    HISTORY_LIMIT,
    Tools,
    api_help,
    describe,
    read_doc_page,
    with_history,
)
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import (
    ChatEntry,
    FilesChanged,
    RunSummary,
    SolveProgress,
    SolveStarted,
    ViewUpdated,
)
from tests.conftest import example_project


class Recorder:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


def call(fn, **args):
    return asyncio.run(fn(args))


def text(result):
    return result["content"][0]["text"]


def test_write_file_tells_the_gui(home):
    recorder = Recorder()
    tools = Tools(Project.create(home), recorder)
    result = call(tools.write_file, name="instance.json", content="{}")
    assert not result["is_error"]
    assert recorder.events == [FilesChanged(files={"instance.json": "{}"})]


def test_check_model_runs_briefly_without_a_revision(home):
    project = example_project("tsp", home)
    result = call(Tools(project, Recorder()).check_model)
    assert not result["is_error"], text(result)
    assert "view.py ok: kpi, route_map, table" in text(result)
    assert project.revisions() == []


def test_check_model_reports_a_broken_view(home):
    project = example_project("tsp", home)
    project.write_file("view.py", "def to_view(i, r):\n    return {}\n")
    result = call(Tools(project, Recorder()).check_model)
    assert result["is_error"]
    assert "invalid ViewSpec" in text(result)


def test_run_solver_makes_a_revision_and_updates_the_canvas(home):
    project = example_project("job_shop", home)
    recorder = Recorder()
    result = call(Tools(project, recorder).run_solver, runs=2, seed=4)
    assert not result["is_error"], text(result)
    assert text(result).startswith("revision 1\n")
    assert project.revisions() == [1]
    kinds = [type(e) for e in recorder.events]
    assert kinds[0] is SolveStarted
    assert kinds[-1] is ViewUpdated
    assert SolveProgress in kinds
    assert recorder.events[-1].view.views[1].type == "gantt"
    _, summary, view, error = project.load_revision(1)
    assert len(summary.runs) == 2
    assert summary.runs[0].seed == 4
    assert view == recorder.events[-1].view
    assert error is None


def test_max_duration_overrides_the_stop_of_solve_json(home):
    tools = Tools(example_project("tsp", home), Recorder())
    request = tools.solve_request({"max_duration_secs": 0.5})
    stop = request.variants[0].heuristic["stop"]
    assert stop == {"max_iteration": 20000, "max_duration_secs": 0.5}


def test_a_result_keeps_the_heuristics_as_solved(home):
    project = example_project("knapsack", home)
    asyncio.run(Tools(project, Recorder()).run_solver({"max_duration_secs": 0.2, "seed": 5}))
    summary = project.load_revision(1)[1]
    assert summary.heuristics[0].heuristic["stop"]["max_duration_secs"] == 0.2
    assert summary.seed == 5


def test_a_solve_starts_from_a_solution_an_earlier_revision_found(home):
    project = example_project("tsp", home)
    tools = Tools(project, Recorder())
    call(tools.run_solver, runs=1)
    best = project.load_revision(1)[1].runs[0]
    result = call(tools.import_solution, rev=1, key="tour")
    assert not result["is_error"], text(result)
    assert json.loads(project.read_file("instance.json"))["tour"] == best.solution
    solve = json.loads(project.read_file("solve.json"))
    project.write_file("solve.json", json.dumps({**solve, "initial_solution": "tour"}))
    result = call(tools.run_solver, runs=1)
    assert 'every run started from instance["tour"]' in text(result)
    summary = project.load_revision(2)[1]
    assert summary.initial_solution == "tour"
    assert summary.runs[0].initial_objective == pytest.approx(best.best_objective)


def test_a_start_that_instance_json_lacks_is_explained(home):
    project = example_project("tsp", home)
    solve = json.loads(project.read_file("solve.json"))
    project.write_file("solve.json", json.dumps({**solve, "initial_solution": "tour"}))
    with pytest.raises(ProjectError, match=r'instance\["tour"\]'):
        call(Tools(project, Recorder()).run_solver)
    assert project.revisions() == []
    with pytest.raises(ProjectError, match="no revision 1"):
        call(Tools(project, Recorder()).import_solution, rev=1, key="tour")


def test_a_failed_solve_is_an_error_result_with_the_traceback(home):
    project = example_project("tsp", home)
    project.write_file("model.py", "def build(instance):\n    return 1 / 0\n")
    result = call(Tools(project, Recorder()).run_solver)
    assert result["is_error"]
    assert "ZeroDivisionError" in text(result)
    assert "stage 'build'" in text(result)


def test_describe_truncates_a_long_solution():
    summary = RunSummary.model_validate(
        {
            "rev": 1,
            "problem": "Tsp",
            "higher_is_better": False,
            "best_run": 0,
            "runs": [
                {
                    "run": 0,
                    "variant": 0,
                    "seed": 0,
                    "best_objective": 1.0,
                    "initial_objective": 2.0,
                    "solution": list(range(5000)),
                    "trajectory": [],
                    "iterations": 1,
                    "best_iteration": 0,
                    "time_to_best_secs": 0.0,
                    "total_time_secs": 0.0,
                }
            ],
        }
    )
    assert "characters)" in describe(summary, solution_preview=100)


@pytest.mark.parametrize(
    ("proven", "bound", "said"),
    [
        (None, None, None),
        (True, 1.0, ", proven optimal"),
        (False, 0.5, ", not proven optimal: no solution beats 0.5"),
        (False, None, ", not proven optimal, no bound yet"),
    ],
)
def test_describe_says_what_a_branch_and_bound_run_proved(proven, bound, said):
    run = {
        "run": 0,
        "variant": 0,
        "seed": 0,
        "best_objective": 1.0,
        "initial_objective": 2.0,
        "solution": [],
        "trajectory": [],
        "iterations": 1,
        "best_iteration": 0,
        "time_to_best_secs": 0.0,
        "total_time_secs": 0.0,
        "proven_optimal": proven,
        "dual_bound": bound,
    }
    summary = RunSummary.model_validate({"rev": 1, "best_run": 0, "runs": [run]})
    line = describe(summary).splitlines()[0]
    if said is None:
        assert "proven" not in line
    else:
        assert line.endswith(said)


def test_api_help_shows_constructors():
    assert "from_coordinates" in api_help("Tsp")
    with pytest.raises(ProjectError):
        api_help("Nonsense")


@pytest.mark.network
def test_every_doc_page_is_in_the_installed_optopus_docs():
    for page in DOC_PAGES:
        assert read_doc_page(page).startswith("#")


def test_a_doc_page_is_fetched_once_at_the_installed_commit(home, monkeypatch):
    fetched = []
    monkeypatch.setattr(docs, "installed_commit", lambda: "abc123")
    monkeypatch.setattr(docs, "fetch", lambda url: fetched.append(url) or "# Problems\n")
    assert read_doc_page("problems") == "# Problems\n"
    assert read_doc_page("problems") == "# Problems\n"
    assert fetched == [f"{docs.RAW}/abc123/docs/source/problems.md"]
    assert (home / "docs" / "abc123" / "problems.md").is_file()
    with pytest.raises(ProjectError, match="unknown page"):
        read_doc_page("../README")


def test_docs_that_cannot_be_found_point_to_api_help(home, monkeypatch):
    def offline(url):
        raise OSError("no network")

    monkeypatch.setattr(docs, "installed_commit", lambda: "abc123")
    monkeypatch.setattr(docs, "fetch", offline)
    with pytest.raises(ProjectError, match=r"no network.*api_help"):
        read_doc_page("problems")
    monkeypatch.setattr(docs, "installed_commit", lambda: None)
    with pytest.raises(ProjectError, match="OPTOPUS_STUDIO_DOCS"):
        read_doc_page("problems")


def test_docs_are_read_from_a_checkout_when_configured(tmp_path, monkeypatch):
    (tmp_path / "running.md").write_text("# Running\n")
    monkeypatch.setenv("OPTOPUS_STUDIO_DOCS", str(tmp_path))
    assert read_doc_page("running") == "# Running\n"
    with pytest.raises(ProjectError, match="does not exist"):
        read_doc_page("problems")


def test_the_installed_optopus_records_its_commit():
    assert len(docs.installed_commit() or "") == 40


def test_an_upload_is_imported_into_instance_json_under_a_key(home):
    project = Project.create(home)
    project.write_file("instance.json", '{"capacity": 30}')
    project.save_upload("stores.csv", b"name,demand\nA,3\nB,5\n")
    recorder = Recorder()
    tools = Tools(project, recorder)
    assert "2 rows, columns: ['name', 'demand']" in text(
        call(tools.preview_upload, name="stores.csv")
    )
    result = call(tools.import_upload, name="stores.csv", key="stores")
    assert "2 records with keys ['name', 'demand']" in text(result)
    assert "['capacity']" in text(result)
    assert json.loads(project.read_file("instance.json")) == {
        "capacity": 30,
        "stores": [{"name": "A", "demand": 3}, {"name": "B", "demand": 5}],
    }
    assert isinstance(recorder.events[-1], FilesChanged)
    with pytest.raises(ProjectError, match="no upload"):
        call(tools.import_upload, name="missing.csv", key="x")


def test_read_file_cuts_a_large_file(home):
    project = Project.create(home)
    project.write_file("instance.json", json.dumps({"rows": list(range(20000))}))
    result = text(call(Tools(project, Recorder()).read_file, name="instance.json"))
    assert "characters in all" in result


@pytest.mark.parametrize(
    "solve",
    [{"runs": 1}, {"heuristics": {"kind": "LocalSearch"}}, {"heuristics": [{"label": ""}]}],
)
def test_a_solve_json_without_valid_heuristics_is_explained(home, solve):
    project = example_project("tsp", home)
    project.write_file("solve.json", json.dumps(solve))
    with pytest.raises(ProjectError, match="heuristic"):
        call(Tools(project, Recorder()).run_solver)
    assert project.revisions() == []


def test_check_model_runs_every_variant_briefly(home):
    result = call(Tools(example_project("workload", home), Recorder()).check_model)
    assert not result["is_error"], text(result)
    assert "SA:" in text(result)
    assert "LAHC:" in text(result)


def test_an_agent_joining_a_conversation_reads_it_first():
    chat = [
        ChatEntry(role="user", text="visit every city"),
        ChatEntry(role="tool", text="write_file model.py"),
        ChatEntry(role="assistant", text="The tour is 412 long."),
    ]
    prompt = with_history(chat, "now from the depot")
    assert prompt.index("visit every city") < prompt.index("[tool] write_file model.py")
    assert prompt.index("412") < prompt.index("now from the depot")
    long = with_history([ChatEntry(role="user", text="x" * (2 * HISTORY_LIMIT))], "next")
    assert "[earlier messages left out]" in long
    assert len(long) < HISTORY_LIMIT + 1000


def test_the_agent_on_claude_sees_only_the_studios_tools(home):
    from optopus_studio.agent_claude import SERVER, options

    project = Project.create(home)
    specs = Tools(project, Recorder()).specs()
    claude = options(specs, project.work, None)
    assert claude.tools == []
    assert claude.setting_sources == []
    assert list(claude.mcp_servers) == [SERVER]
    assert claude.allowed_tools == [f"mcp__{SERVER}__{spec.name}" for spec in specs]
    # Not the MCP servers of the Claude account it signs in with, such as claude.ai connectors.
    assert claude.strict_mcp_config


def test_a_new_project_starts_on_the_agent_named_or_the_first_that_can_run(home, monkeypatch):
    from optopus_studio.agent import AgentSession

    def agent(**meta):
        project = Project.create(home)
        project.set_meta(**meta)
        return AgentSession(project, Recorder()).agent

    assert agent() == "claude"
    monkeypatch.setenv("OPTOPUS_STUDIO_AGENT", "codex")
    assert agent() == "codex"
    # A project from before the choice has a Claude session.
    assert agent(session_id="a-claude-session") == "claude"
    assert agent(agent="claude") == "claude"
