import io
import json
import zipfile

import pytest

from optopus_studio.projects import ARCHIVE_MANIFEST, Project, ProjectError
from optopus_studio.protocol import ChatEntry, KpiView, RunSummary, ViewSpec
from tests.conftest import example_project, one


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

    summary = RunSummary(rev=first, problem="Formula", heuristics=one({"kind": "LocalSearch"}))
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


# The size, not the content: pytest names a test by its parameters, and 20 MiB of content would
# make a 20 MiB test id, which hangs a GitHub Actions runner printing it under -v.
@pytest.mark.parametrize(
    ("name", "size"),
    [(".hidden.csv", 1), ("../x.csv", 1), ("run.sh", 1), ("big.csv", 20 * 2**20 + 1)],
)
def test_uploads_need_a_plain_name_a_table_suffix_and_a_sane_size(home, name, size):
    data = b"a" * size
    project = Project.create(home)
    if name == "../x.csv":
        # The directory part is dropped rather than followed.
        assert project.save_upload(name, data) == "x.csv"
        return
    with pytest.raises(ProjectError):
        project.save_upload(name, data)


def test_an_upload_is_found_by_name(home):
    project = Project.create(home)
    project.save_upload("stores.csv", b"a,b\n1,2\n")
    assert project.uploads() == ["stores.csv"]
    assert project.upload_path("stores.csv").read_bytes() == b"a,b\n1,2\n"
    with pytest.raises(ProjectError):
        project.upload_path("other.csv")


def test_a_result_older_than_its_heuristics_takes_them_from_solve_json(home):
    project = example_project("knapsack", home)
    rev = project.snapshot()
    project.save_result(rev, RunSummary(rev=rev))
    summary = project.load_revision(rev)[1]
    assert [v.heuristic["kind"] for v in summary.heuristics] == ["SimulatedAnnealing"]
    assert summary.seed == 0


@pytest.mark.parametrize(
    ("said", "title"),
    [
        ([], None),
        (["fill the bag"], "fill the bag"),
        (["Attached: items.csv\n\nfill   the\nbag", "later"], "fill the bag"),
        (["x" * 80], "x" * 59 + "…"),
    ],
)
def test_a_project_is_titled_by_what_the_user_asked_first(home, said, title):
    project = Project.create(home)
    project.append_chat(ChatEntry(role="assistant", text="hello"))
    for text in said:
        project.append_chat(ChatEntry(role="user", text=text))
    assert project.title() == title


def shared_project(home):
    project = example_project("knapsack", home)
    project.append_chat(ChatEntry(role="user", text="fill the bag"))
    project.append_chat(ChatEntry(role="tool", text="write_file model.py"))
    project.save_upload("items.csv", b"w,v\n1,2\n")
    rev = project.snapshot()
    project.save_result(rev, RunSummary(rev=rev, problem="Formula"))
    project.save_view(rev, ViewSpec(views=[KpiView(items=[{"label": "Value", "value": 1}])]), None)
    project.set_meta(session_id="stays-on-this-machine")
    (project.work / "__pycache__").mkdir()
    (project.work / "__pycache__" / "model.pyc").write_bytes(b"")
    return project


def test_an_exported_project_is_imported_as_a_new_one(home, tmp_path):
    source = shared_project(home)
    elsewhere = tmp_path / "elsewhere"
    copy = Project.import_archive(source.export(), elsewhere)
    assert Project.list(elsewhere) == [copy.id]
    assert copy.chat() == source.chat()
    assert copy.files() == source.files()
    assert copy.revisions() == [1]
    assert copy.load_revision(1) == source.load_revision(1)
    assert copy.uploads() == ["items.csv"]
    assert copy.meta() == {"imported_from": source.id}
    assert not (copy.work / "__pycache__").exists()


def archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, content in files.items():
            zipped.writestr(name, content)
    return buffer.getvalue()


MANIFEST = {ARCHIVE_MANIFEST: json.dumps({"format": 1, "project": "0123456789ab"})}


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"chat.jsonl": ""}, "is missing"),
        ({ARCHIVE_MANIFEST: '{"format": 2}'}, "format"),
        ({**MANIFEST, "../model.py": "x"}, "does not"),
        ({**MANIFEST, "meta.json": "{}"}, "does not"),
        ({**MANIFEST, "work/notes.txt": "x"}, "does not"),
        ({**MANIFEST, "revs/0/model.py": "x"}, "does not"),
        ({**MANIFEST, "uploads/.hidden.csv": "x"}, "does not"),
        ({**MANIFEST, "uploads/a/b.csv": "x"}, "does not"),
        ({**MANIFEST, "work/instance.json": "{not json"}, "broken"),
        ({**MANIFEST, "chat.jsonl": '{"role": "robot", "text": ""}'}, "broken"),
        ({**MANIFEST, "revs/1/result.json": '{"rev": "one"}'}, "broken"),
    ],
)
def test_an_archive_that_is_not_a_project_is_refused(home, files, message):
    with pytest.raises(ProjectError, match=message):
        Project.import_archive(archive(files), home)
    assert Project.list(home) == []


def test_a_file_that_is_not_a_zip_is_refused(home):
    with pytest.raises(ProjectError, match="not a zip"):
        Project.import_archive(b"hello", home)
