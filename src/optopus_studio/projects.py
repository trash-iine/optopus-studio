"""Projects on disk: the files the agent edits, and one revision per solve.

    <home>/projects/<id>/
        meta.json       the agent session to resume
        chat.jsonl      the conversation as shown in the GUI
        work/           the files the agent edits (PROJECT_FILES)
        uploads/        files the user attached in the chat, imported into instance.json
        revs/<n>/       a copy of work/ as solved, with result.json and view.json

A revision freezes the files next to what they produced, so the GUI can go back to any earlier
model and its result, and a later worker can re-run exactly what an earlier one did.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from optopus_studio.protocol import ChatEntry, RunSummary, ViewSpec

PROJECT_FILES = ("instance.json", "model.py", "view.py", "solve.json")
PROJECT_ID = re.compile(r"\A[0-9a-f]{12}\Z")
UPLOAD_NAME = re.compile(r"\A[\w.\- ]{1,100}\Z")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def studio_home() -> Path:
    return Path(os.environ.get("OPTOPUS_STUDIO_HOME", Path.home() / ".optopus-studio"))


class ProjectError(ValueError):
    pass


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
        if name not in PROJECT_FILES:
            raise ProjectError(f"{name!r} is not a project file; expected one of {PROJECT_FILES}")
        return name

    def files(self) -> dict[str, str]:
        return {
            name: (self.work / name).read_text()
            for name in PROJECT_FILES
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
        for name in PROJECT_FILES:
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
        files = {name: (path / name).read_text() for name in PROJECT_FILES}
        result = path / "result.json"
        summary = RunSummary.model_validate_json(result.read_text()) if result.is_file() else None
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
