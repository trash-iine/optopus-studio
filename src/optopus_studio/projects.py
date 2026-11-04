"""Projects on disk: the files the agent edits, and one revision per solve.

    <home>/projects/<id>/
        meta.json       the agent (Claude or Codex), its session to resume, and whether it may
                        search the web (docs/adr/0016)
        chat.jsonl      the conversation as shown in the GUI
        work/           the files the agent edits (PROJECT_FILES, and OPTIONAL_FILES once written)
        uploads/        files the user attached in the chat, imported into instance.json
        cases/<id>/     cases attached from a packaged app (docs/adr/0009)
        bench/          the instances a change of the algorithm is judged on, and every
                        evaluation's result, tuning's and profile's record (bench.py, tune.py,
                        profiling.py, docs/adr/0013, 0014, 0015)
        revs/<n>/       a copy of work/ as solved, with result.json and view.json

A revision freezes the files next to what they produced, so the GUI can go back to any earlier
model and its result, and a later worker can re-run exactly what an earlier one did.

A project is shared as a zip of all of it but meta.json (``Project.export``), which another
studio imports as a new project (``Project.import_archive``).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from optopus_studio.protocol import (
    BENCH_NAME,
    AppSpec,
    BenchSpec,
    ChatEntry,
    ProjectInfo,
    RunSummary,
    Variant,
    ViewSpec,
)

PROJECT_FILES = ("instance.json", "model.py", "view.py", "solve.json")
# The model ported to Rust, which a solve.json with "worker": "rust" runs (docs/adr/0005), what
# a packaged app lets its user change (docs/adr/0009), and the generator of benchmark instances
# (docs/adr/0013).
OPTIONAL_FILES = ("rust/main.rs", "app.json", "generate.py")
ALL_FILES = PROJECT_FILES + OPTIONAL_FILES
# What builds the benchmark rather than the algorithm, which restoring a revision leaves alone.
BENCH_FILES = ("generate.py",)
PROJECT_ID = re.compile(r"\A[0-9a-f]{12}\Z")
UPLOAD_NAME = re.compile(r"\A[\w.\- ]{1,100}\Z")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TITLE_LENGTH = 60

ARCHIVE_MANIFEST = "optopus-studio-project.json"
ARCHIVE_FORMAT = 1
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_FILE = "|".join(re.escape(name) for name in ALL_FILES)
# Everything of a project but meta.json, whose agent session lives in this machine's Claude Code
# or Codex.
ARCHIVE_MEMBER = re.compile(
    rf"\A(?:chat\.jsonl|work/(?:{_FILE})|revs/[1-9][0-9]{{0,5}}/(?:{_FILE}|result\.json|view\.json)"
    r"|uploads/(?P<upload>[^/]+)|cases/(?P<case>[0-9a-f]{12})/(?P<case_file>.+)"
    rf"|bench/(?:bench\.json|instances/{BENCH_NAME[1:-1]}\.json"
    r"|(?:results|tunings|profiles)/[1-9][0-9]{0,5}\.json))\Z"
)


def studio_home() -> Path:
    """Where the studio keeps its projects: ``OPTOPUS_STUDIO_HOME``, or ``~/.optopus-studio``.

    Returns:
        The directory's path.
    """
    return Path(os.environ.get("OPTOPUS_STUDIO_HOME", Path.home() / ".optopus-studio"))


class ProjectError(ValueError):
    """Something the user or the agent asked of a project that cannot be done."""


def variants_of(solve: dict[str, Any]) -> list[Variant]:
    """The heuristics of solve.json: one under "heuristic", or labeled ones under "heuristics".

    Args:
        solve: solve.json's content.

    Returns:
        The heuristics, each under its label; a lone heuristic is labeled by its kind.

    Raises:
        ProjectError: solve.json has neither, or "heuristics" is not a list.
        pydantic.ValidationError: An entry of "heuristics" is not a labeled heuristic.
    """
    if "heuristics" in solve:
        entries = solve["heuristics"]
        if not isinstance(entries, list):
            raise ProjectError('"heuristics" must be a list of {"label", "heuristic"}')
        return [Variant.model_validate(entry) for entry in entries]
    heuristic = solve.get("heuristic")
    if not isinstance(heuristic, dict):
        raise ProjectError('solve.json needs "heuristic" or "heuristics"')
    return [Variant(label=str(heuristic.get("kind", "heuristic")), heuristic=heuristic)]


class Project:
    """A project on disk, laid out as this module's docstring shows.

    Attributes:
        root: The project's directory.
        id: The project's id, the directory's name.
        work: The files the agent edits.
        revs: The revisions.
        uploads_dir: The files the user attached.
        bench: The benchmark and its records.
    """

    def __init__(self, root: Path):
        """Opens the project at ``root`` without checking it; ``open`` checks.

        Args:
            root: The project's directory.
        """
        self.root = root
        self.id = root.name
        self.work = root / "work"
        self.revs = root / "revs"
        self.uploads_dir = root / "uploads"
        self.bench = root / "bench"

    # --- creation ------------------------------------------------------------------------------

    @classmethod
    def create(cls, home: Path | None = None) -> Project:
        """Creates an empty project with a new id.

        Args:
            home: The studio's home; ``studio_home()`` when None.

        Returns:
            The project.
        """
        root = (home or studio_home()) / "projects" / uuid.uuid4().hex[:12]
        (root / "work").mkdir(parents=True)
        (root / "revs").mkdir()
        project = cls(root)
        project._write_meta({})
        return project

    @classmethod
    def open(cls, project_id: str, home: Path | None = None) -> Project:
        """Opens an existing project.

        Args:
            project_id: The project's id.
            home: The studio's home; ``studio_home()`` when None.

        Returns:
            The project.

        Raises:
            ProjectError: The id is malformed, or there is no such project.
        """
        if not PROJECT_ID.match(project_id):
            raise ProjectError(f"invalid project id {project_id!r}")
        root = (home or studio_home()) / "projects" / project_id
        if not (root / "meta.json").is_file():
            raise ProjectError(f"no project {project_id!r}")
        return cls(root)

    @staticmethod
    def list(home: Path | None = None) -> list[str]:
        """The projects' ids, the most recently changed first.

        Args:
            home: The studio's home; ``studio_home()`` when None.

        Returns:
            The ids.
        """
        base = (home or studio_home()) / "projects"
        if not base.is_dir():
            return []
        roots = [p for p in base.iterdir() if (p / "meta.json").is_file()]
        return [p.name for p in sorted(roots, key=lambda p: p.stat().st_mtime, reverse=True)]

    def info(self) -> ProjectInfo:
        """What the project list shows of the project.

        Returns:
            The project's id, title, and the project it was imported from.
        """
        return ProjectInfo(
            id=self.id, title=self.title(), imported_from=self.meta().get("imported_from")
        )

    def title(self) -> str | None:
        """The project's title: the user's first message, on one line and cut short.

        Returns:
            The title, or None before the user has said anything.
        """
        first = next((entry.text for entry in self.chat() if entry.role == "user"), None)
        if first is None:
            return None
        if first.startswith("Attached: ") and "\n\n" in first:
            first = first.split("\n\n", 1)[1]
        line = " ".join(first.split())
        return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1] + "…"

    # --- meta ----------------------------------------------------------------------------------

    def meta(self) -> dict[str, Any]:
        """meta.json's content: the agent, its session, and whether it may search the web.

        Returns:
            The content.
        """
        return json.loads((self.root / "meta.json").read_text())

    def _write_meta(self, meta: dict[str, Any]) -> None:
        """Replaces meta.json's content.

        Args:
            meta: The new content.
        """
        (self.root / "meta.json").write_text(json.dumps(meta, indent=2))

    def set_meta(self, **values: Any) -> None:
        """Sets some of meta.json's values, keeping the rest.

        Args:
            **values: The values to set.
        """
        self._write_meta({**self.meta(), **values})

    # --- files ---------------------------------------------------------------------------------

    @staticmethod
    def check_name(name: str) -> str:
        """Checks that a name is one of a project's files.

        Args:
            name: The file's name, such as ``model.py`` or ``rust/main.rs``.

        Returns:
            The name.

        Raises:
            ProjectError: The name is not a project file.
        """
        if name not in ALL_FILES:
            raise ProjectError(f"{name!r} is not a project file; expected one of {ALL_FILES}")
        return name

    def files(self) -> dict[str, str]:
        """The work files that have been written.

        Returns:
            Each file's content, by its name.
        """
        return {
            name: (self.work / name).read_text()
            for name in ALL_FILES
            if (self.work / name).is_file()
        }

    def read_file(self, name: str) -> str:
        """One work file's content.

        Args:
            name: The file's name.

        Returns:
            The content.

        Raises:
            ProjectError: The name is not a project file, or the file has not been written.
        """
        path = self.work / self.check_name(name)
        if not path.is_file():
            raise ProjectError(f"{name} has not been written yet")
        return path.read_text()

    def write_file(self, name: str, content: str) -> None:
        """Writes a work file, after checking that a JSON file is JSON and app.json is an app.

        Args:
            name: The file's name.
            content: The file's new content.

        Raises:
            ProjectError: The name is not a project file, or the content does not fit it.
        """
        if self.check_name(name).endswith(".json"):
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                raise ProjectError(f"{name} is not valid JSON: {exc}") from exc
        if name == "app.json":
            try:
                AppSpec.model_validate_json(content)
            except ValidationError as exc:
                raise ProjectError(f"app.json is not a valid app: {exc}") from exc
        (self.work / name).parent.mkdir(parents=True, exist_ok=True)
        (self.work / name).write_text(content)

    # --- revisions -----------------------------------------------------------------------------

    def revisions(self) -> list[int]:
        """The revisions' numbers.

        Returns:
            The numbers, in order.
        """
        return sorted(int(p.name) for p in self.revs.iterdir() if p.name.isdigit())

    def snapshot(self) -> int:
        """Copies work/ into a new revision and returns its number.

        Returns:
            The new revision's number.

        Raises:
            ProjectError: A file every revision needs has not been written.
        """
        missing = [name for name in PROJECT_FILES if not (self.work / name).is_file()]
        if missing:
            raise ProjectError(f"write {', '.join(missing)} first")
        rev = max(self.revisions(), default=0) + 1
        target = self.revs / str(rev)
        target.mkdir()
        for name in ALL_FILES:
            if (self.work / name).is_file():
                (target / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.work / name, target / name)
        return rev

    def restore(self, rev: int) -> None:
        """Makes work/ the files of revision ``rev`` again, without the ones it did not have.

        The benchmark's generator stays as it is: it makes instances, it is not the algorithm.

        Args:
            rev: The revision.

        Raises:
            ProjectError: There is no such revision.
        """
        source = self.rev_dir(rev)
        for name in ALL_FILES:
            if name in BENCH_FILES:
                continue
            if (source / name).is_file():
                (self.work / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, self.work / name)
            else:
                (self.work / name).unlink(missing_ok=True)

    def rev_dir(self, rev: int) -> Path:
        """A revision's directory.

        Args:
            rev: The revision.

        Returns:
            The directory's path.

        Raises:
            ProjectError: There is no such revision.
        """
        path = self.revs / str(rev)
        if not path.is_dir():
            raise ProjectError(f"no revision {rev}")
        return path

    def save_result(self, rev: int, summary: RunSummary) -> None:
        """Keeps a revision's solve.

        Args:
            rev: The revision.
            summary: The solve's summary.
        """
        (self.rev_dir(rev) / "result.json").write_text(summary.model_dump_json())

    def save_view(self, rev: int, view: ViewSpec | None, error: str | None) -> None:
        """Keeps what a revision's ``view.py`` drew, or why it failed.

        Args:
            rev: The revision.
            view: The view, or None when it failed.
            error: Why it failed, or None.
        """
        payload = {"view": view.model_dump(mode="json") if view else None, "error": error}
        (self.rev_dir(rev) / "view.json").write_text(json.dumps(payload))

    def load_revision(
        self, rev: int
    ) -> tuple[dict[str, str], RunSummary | None, ViewSpec | None, str | None]:
        """A revision's files, solve and view.

        Args:
            rev: The revision.

        Returns:
            The files, the solve's summary, the view, and the view's error; each of the last three
                is
            None when the revision has none.

        Raises:
            ProjectError: There is no such revision.
        """
        path = self.rev_dir(rev)
        files = {name: (path / name).read_text() for name in ALL_FILES if (path / name).is_file()}
        result = path / "result.json"
        summary = RunSummary.model_validate_json(result.read_text()) if result.is_file() else None
        if summary and not summary.heuristics and "solve.json" in files:
            # Solved before results kept their heuristics: solve.json says, barring overrides.
            try:
                solve = json.loads(files["solve.json"])
                summary.heuristics = variants_of(solve)
                summary.seed = solve.get("seed", 0)
            except (json.JSONDecodeError, ProjectError, ValidationError):
                pass
        view, error = None, None
        if (path / "view.json").is_file():
            stored = json.loads((path / "view.json").read_text())
            view = ViewSpec.model_validate(stored["view"]) if stored["view"] else None
            error = stored["error"]
        return files, summary, view, error

    # --- uploads -------------------------------------------------------------------------------

    def save_upload(self, name: str, data: bytes) -> str:
        """Keeps a file the user attached.

        Args:
            name: The file's name; only its last part is used.
            data: The file's content.

        Returns:
            The name the file is kept under.

        Raises:
            ProjectError: The name, type or size is not one the studio accepts.
        """
        from optopus_studio.tables import UPLOAD_SUFFIXES

        name = Path(name).name
        if not UPLOAD_NAME.match(name) or name.startswith("."):
            raise ProjectError(f"invalid file name {name!r}")
        if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
            raise ProjectError(f"{name}: expected one of {UPLOAD_SUFFIXES}")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ProjectError(f"{name} is larger than {MAX_UPLOAD_BYTES // 2**20} MiB")
        self.uploads_dir.mkdir(exist_ok=True)
        (self.uploads_dir / name).write_bytes(data)
        return name

    def uploads(self) -> list[str]:
        """The files the user attached.

        Returns:
            Their names, in order.
        """
        if not self.uploads_dir.is_dir():
            return []
        return sorted(p.name for p in self.uploads_dir.iterdir() if p.is_file())

    def upload_path(self, name: str) -> Path:
        """Where an attached file is kept.

        Args:
            name: The file's name.

        Returns:
            The file's path.

        Raises:
            ProjectError: No file of that name was attached.
        """
        if name not in self.uploads():
            raise ProjectError(f"no upload {name!r}; the uploads are {self.uploads()}")
        return self.uploads_dir / name

    # --- chat ----------------------------------------------------------------------------------

    def append_chat(self, entry: ChatEntry) -> None:
        """Adds an entry to the conversation the GUI shows.

        Args:
            entry: The entry.
        """
        with (self.root / "chat.jsonl").open("a") as f:
            f.write(entry.model_dump_json() + "\n")

    def chat(self) -> list[ChatEntry]:
        """The conversation as the GUI shows it.

        Returns:
            Its entries, in order.
        """
        path = self.root / "chat.jsonl"
        if not path.is_file():
            return []
        return [ChatEntry.model_validate_json(line) for line in path.read_text().splitlines()]

    # --- sharing -------------------------------------------------------------------------------

    def export(self) -> bytes:
        """The project as a zip another studio imports.

        It holds the chat, the files, every revision with its result, and the uploads. Not the
        agent's session, which this machine's Claude Code or Codex keeps; the importing studio's
        agent reads the chat instead.

        Returns:
            The zip's bytes.
        """
        manifest = {
            "format": ARCHIVE_FORMAT,
            "project": self.id,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(ARCHIVE_MANIFEST, json.dumps(manifest, indent=2))
            for path in sorted(self.root.rglob("*")):
                name = path.relative_to(self.root).as_posix()
                if path.is_file() and ARCHIVE_MEMBER.match(name):
                    archive.write(path, name)
        return buffer.getvalue()

    @classmethod
    def import_archive(cls, data: bytes, home: Path | None = None) -> Project:
        """Creates a project from what ``export`` wrote, after checking all of it.

        Args:
            data: The zip's bytes.
            home: The studio's home; ``studio_home()`` when None.

        Returns:
            The new project.

        Raises:
            ProjectError: The zip is not an exported project, is too large, or holds a broken file.
        """
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = [info for info in archive.infolist() if not info.is_dir()]
                if sum(info.file_size for info in members) > MAX_ARCHIVE_BYTES:
                    raise ProjectError(
                        f"the archive unpacks to over {MAX_ARCHIVE_BYTES // 2**20} MiB"
                    )
                contents = {info.filename: archive.read(info) for info in members}
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
            raise ProjectError(f"not a zip file: {exc}") from exc
        manifest = _manifest(contents.pop(ARCHIVE_MANIFEST, None))
        for name, content in contents.items():
            _check_member(name, content)
        project = cls.create(home)
        for name, content in contents.items():
            path = project.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        origin = manifest.get("project")
        project.set_meta(imported_from=origin if isinstance(origin, str) else None)
        return project


def _manifest(content: bytes | None) -> dict[str, Any]:
    """Reads an archive's manifest and checks its format.

    Args:
        content: The manifest's bytes, or None when the archive has none.

    Returns:
        The manifest.

    Raises:
        ProjectError: The manifest is missing, not JSON, or of another format.
    """
    if content is None:
        raise ProjectError(f"not an exported studio project: {ARCHIVE_MANIFEST} is missing")
    try:
        manifest = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProjectError(f"{ARCHIVE_MANIFEST} is not JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
        raise ProjectError(
            f"the archive is in a format this studio cannot read; expected {ARCHIVE_FORMAT}"
        )
    return manifest


def _check_member(name: str, content: bytes) -> None:
    """Rejects a file the archive may not hold, or one the studio would fail on later.

    Args:
        name: The file's path in the archive.
        content: The file's bytes.

    Raises:
        ProjectError: The file has no place in a project, or is broken.
    """
    match = ARCHIVE_MEMBER.match(name)
    upload = match and match["upload"]
    if not match or (upload and (not UPLOAD_NAME.match(upload) or upload.startswith("."))):
        raise ProjectError(f"the archive holds a file a project does not: {name!r}")
    if upload:
        return
    if match["case"]:
        # apps imports this module, so import it here.
        from optopus_studio.apps import check_case_member

        check_case_member(match["case_file"], content)
        return
    try:
        text = content.decode()
        if name == "chat.jsonl":
            for line in text.splitlines():
                ChatEntry.model_validate_json(line)
        elif name.endswith("/result.json"):
            RunSummary.model_validate_json(text)
        elif name == "bench/bench.json":
            BenchSpec.model_validate_json(text)
        elif name.endswith(".json"):
            json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ProjectError(f"{name} in the archive is broken: {exc}") from exc
