import pytest

from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import ChatEntry, KpiView, RunSummary, ViewSpec
from tests.conftest import example_project


def test_a_project_is_found_again_by_its_id(home):
    project = Project.create(home)
    assert Project.list(home) == [project.id]
    assert Project.open(project.id, home).root == project.root


@pytest.mark.parametrize("project_id", ["../etc", "abc", "0123456789ab"])
def test_an_unknown_or_unsafe_id_is_rejected(home, project_id):
    with pytest.raises(ProjectError):
        Project.open(project_id, home)


@pytest.mark.parametrize(
    ("name", "content"),
    [("../model.py", "x"), ("notes.txt", "x"), ("instance.json", "{not json")],
)
def test_only_project_files_with_valid_json_are_written(home, name, content):
    with pytest.raises(ProjectError):
        Project.create(home).write_file(name, content)


def test_a_snapshot_needs_every_file(home):
    project = Project.create(home)
    project.write_file("model.py", "")
    with pytest.raises(ProjectError, match=r"instance\.json"):
        project.snapshot()


def test_revisions_freeze_the_files_with_their_result(home):
    project = example_project("knapsack", home)
    first = project.snapshot()
    project.write_file("solve.json", '{"heuristic": {}, "runs": 9}')
    second = project.snapshot()
    assert project.revisions() == [first, second] == [1, 2]

    summary = RunSummary(rev=first, problem="Formula")
    view = ViewSpec(views=[KpiView(items=[{"label": "Value", "value": 1}])])
    project.save_result(first, summary)
    project.save_view(first, view, None)
    files, loaded, loaded_view, error = project.load_revision(first)
    assert '"runs": 9' not in files["solve.json"]
    assert loaded == summary
    assert loaded_view == view
    assert error is None


def test_the_chat_is_kept_in_order(home):
    project = Project.create(home)
    entries = [ChatEntry(role="user", text="hi"), ChatEntry(role="assistant", text="hello")]
    for entry in entries:
        project.append_chat(entry)
    assert project.chat() == entries
