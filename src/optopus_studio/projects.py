"""Projects on disk: the files the agent edits, and one revision per solve.

    <home>/projects/<id>/
        meta.json       the agent (Claude or Codex) and its session to resume
        chat.jsonl      the conversation as shown in the GUI
        work/           the files the agent edits (PROJECT_FILES, and OPTIONAL_FILES once written)
        uploads/        files the user attached in the chat, imported into instance.json
        cases/<id>/     cases attached from a packaged app (docs/adr/0009)
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

from optopus_studio.protocol import AppSpec, ChatEntry, ProjectInfo, RunSummary, Variant, ViewSpec

PROJECT_FILES = ("instance.json", "model.py", "view.py", "solve.json")
# The model ported to Rust, which a solve.json with "worker": "rust" runs (docs/adr/0005), and
# what a packaged app lets its user change (docs/adr/0009).
OPTIONAL_FILES = ("rust/main.rs", "app.json")
ALL_FILES = PROJECT_FILES + OPTIONAL_FILES
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
    r"|uploads/(?P<upload>[^/]+)|cases/(?P<case>[0-9a-f]{12})/(?P<case_file>.+))\Z"
)


def studio_home() -> Path:
    return Path(os.environ.get("OPTOPUS_STUDIO_HOME", Path.home() / ".optopus-studio"))


class ProjectError(ValueError):
    pass


def variants_of(solve: dict[str, Any]) -> list[Variant]:
    """The heuristics of solve.json: one under "heuristic", or labeled ones under "heuristics"."""
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
    def __init__(self, root: Path):
        self.root = root
        self.id = root.name
        self.work = root / "work"
        self.revs = root / "revs"
        self.uploads_dir = root / "uploads"

    # --- creation ------------------------------------------------------------------------------

    @classmethod
    def create(cls, home: Path | None = None) -> Project:
        root = (home or studio_home()) / "projects" / uuid.uuid4().hex[:12]
        (root / "work").mkdir(parents=True)
        (root / "revs").mkdir()
        project = cls(root)
        project._write_meta({})
        return project

    @classmethod
    def open(cls, project_id: str, home: Path | None = None) -> Project:
        if not PROJECT_ID.match(project_id):
            raise ProjectError(f"invalid project id {project_id!r}")
        root = (home or studio_home()) / "projects" / project_id
        if not (root / "meta.json").is_file():
            raise ProjectError(f"no project {project_id!r}")
        return cls(root)

    @staticmethod
    def list(home: Path | None = None) -> list[str]:
        base = (home or studio_home()) / "projects"
        if not base.is_dir():
            return []
        roots = [p for p in base.iterdir() if (p / "meta.json").is_file()]
        return [p.name for p in sorted(roots, key=lambda p: p.stat().st_mtime, reverse=True)]

    def info(self) -> ProjectInfo:
        return ProjectInfo(
            id=self.id, title=self.title(), imported_from=self.meta().get("imported_from")
        )

    def title(self) -> str | None:
        first = next((entry.text for entry in self.chat() if entry.role == "user"), None)
        if first is None:
            return None
        if first.startswith("Attached: ") and "\n\n" in first:
            first = first.split("\n\n", 1)[1]
        line = " ".join(first.split())
        return line if len(line) <= TITLE_LENGTH else line[: TITLE_LENGTH - 1] + "…"

    # --- meta ----------------------------------------------------------------------------------

    def meta(self) -> dict[str, Any]:
        return json.loads((self.root / "meta.json").read_text())

    def _write_meta(self, meta: dict[str, Any]) -> None:
        (self.root / "meta.json").write_text(json.dumps(meta, indent=2))

    def set_meta(self, **values: Any) -> None:
        self._write_meta({**self.meta(), **values})

    # --- files ---------------------------------------------------------------------------------

    @staticmethod
    def check_name(name: str) -> str:
        if name not in ALL_FILES:
            raise ProjectError(f"{name!r} is not a project file; expected one of {ALL_FILES}")
        return name

    def files(self) -> dict[str, str]:
        return {
            name: (self.work / name).read_text()
            for name in ALL_FILES
            if (self.work / name).is_file()
        }

    def read_file(self, name: str) -> str:
        path = self.work / self.check_name(name)
        if not path.is_file():
            raise ProjectError(f"{name} has not been written yet")
        return path.read_text()

    def write_file(self, name: str, content: str) -> None:
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
        return sorted(int(p.name) for p in self.revs.iterdir() if p.name.isdigit())

    def snapshot(self) -> int:
        """Copies work/ into a new revision and returns its number."""
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

    def rev_dir(self, rev: int) -> Path:
        path = self.revs / str(rev)
        if not path.is_dir():
            raise ProjectError(f"no revision {rev}")
        return path

    def save_result(self, rev: int, summary: RunSummary) -> None:
        (self.rev_dir(rev) / "result.json").write_text(summary.model_dump_json())

    def save_view(self, rev: int, view: ViewSpec | None, error: str | None) -> None:
        payload = {"view": view.model_dump(mode="json") if view else None, "error": error}
        (self.rev_dir(rev) / "view.json").write_text(json.dumps(payload))

    def load_revision(
        self, rev: int
    ) -> tuple[dict[str, str], RunSummary | None, ViewSpec | None, str | None]:
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
        if not self.uploads_dir.is_dir():
            return []
        return sorted(p.name for p in self.uploads_dir.iterdir() if p.is_file())

    def upload_path(self, name: str) -> Path:
        if name not in self.uploads():
            raise ProjectError(f"no upload {name!r}; the uploads are {self.uploads()}")
        return self.uploads_dir / name

    # --- chat ----------------------------------------------------------------------------------

    def append_chat(self, entry: ChatEntry) -> None:
        with (self.root / "chat.jsonl").open("a") as f:
            f.write(entry.model_dump_json() + "\n")

    def chat(self) -> list[ChatEntry]:
        path = self.root / "chat.jsonl"
        if not path.is_file():
            return []
        return [ChatEntry.model_validate_json(line) for line in path.read_text().splitlines()]

    # --- sharing -------------------------------------------------------------------------------

    def export(self) -> bytes:
        """The project as a zip another studio imports: the chat, the files, every revision with
        its result, and the uploads. Not the agent's session, which this machine's Claude Code or
        Codex keeps; the importing studio's agent reads the chat instead."""
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
        """Creates a project from what ``export`` wrote, after checking all of it."""
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
    """Rejects a file the archive may not hold, or one the studio would fail on later."""
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
        elif name.endswith(".json"):
            json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ProjectError(f"{name} in the archive is broken: {exc}") from exc
