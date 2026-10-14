"""Apps: a revision packaged to run without the agent (docs/adr/0009).

A project's ``app.json`` (``AppSpec``) says what the app's user may change: the tables that
replace keys of instance.json, and the parameters that set a value in instance.json or the
solve's time limit, runs or seed. Everything else is the revision's, and is changed in the
studio.

``package`` writes a revision into a zip; ``App.open_package`` unpacks one; a ``Case`` is one
set of inputs an app's user gives, solved with the packaged model and view.

    <home>/apps/<package hash>/
        optopus-studio-app.json   the manifest
        model/                    the revision's files, app.json included
        sample/                   the revision's own result.json and view.json
        cases/<id>/               inputs/<key>/<file>, case.json, instance.json, result.json,
                                  view.json
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from optopus_studio import docs
from optopus_studio.projects import (
    ALL_FILES,
    UPLOAD_NAME,
    Project,
    ProjectError,
    studio_home,
    variants_of,
)
from optopus_studio.protocol import (
    AppInfo,
    AppInput,
    AppParameter,
    AppSpec,
    CaseInput,
    CaseState,
    RunSummary,
    ViewSpec,
)
from optopus_studio.runner import render_view, run_solve
from optopus_studio.solving import rust_binary, solve_request, solve_timeout
from optopus_studio.tables import UPLOAD_SUFFIXES, TableError, read_records

log = logging.getLogger(__name__)

APP_FILE = "app.json"
PACKAGE_MANIFEST = "optopus-studio-app.json"
PACKAGE_FORMAT = 1
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
CASE_ID = re.compile(r"\A[0-9a-f]{12}\Z")
Status = Literal["draft", "solving", "solved", "failed"]
# Problems listed per kind before "and N more", so a broken file reads as a few lines.
EXAMPLES = 3
MAX_NOTE_CHARS = 10_000
SELF_TEST_SECONDS = 2.0
# Set in an app's image (docker/app.Dockerfile): the tag it was built as, carried into its cases.
IMAGE_VARIABLE = "OPTOPUS_APP_IMAGE"


# --- app.json ----------------------------------------------------------------------------------


def load_spec(text: str) -> AppSpec:
    try:
        return AppSpec.model_validate_json(text)
    except ValidationError as exc:
        lines = [
            f"{'.'.join(str(p) for p in error['loc']) or '(top)'}: {error['msg']}"
            for error in exc.errors()
        ]
        raise ProjectError("app.json is not a valid app:\n" + "\n".join(lines)) from exc


def _path(target: str) -> tuple[str, list[str]]:
    where, _, rest = target.partition(".")
    return where, rest.split(".")


def _get(value: Any, path: list[str]) -> Any:
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise KeyError(key)
        value = value[key]
    return value


def _set(value: dict[str, Any], path: list[str], new: Any) -> None:
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = new


def _solve_value(solve: dict[str, Any], name: str) -> Any:
    if name == "runs":
        return solve.get("runs", 1)
    if name == "seed":
        return solve.get("seed", 0)
    limits = [(v.heuristic.get("stop") or {}).get("max_duration_secs") for v in variants_of(solve)]
    return limits[0] if limits and all(limit == limits[0] for limit in limits) else None


def defaults(spec: AppSpec, instance: Any, solve: dict[str, Any]) -> dict[str, Any]:
    """Each parameter's value in the packaged files; None where they hold none."""
    values = {}
    for p in spec.parameters:
        where, path = _path(p.target)
        try:
            values[p.name] = (
                _get(instance, path) if where == "instance" else _solve_value(solve, path[0])
            )
        except KeyError:
            values[p.name] = None
    return values


def coerce(p: AppParameter, value: Any) -> Any:
    """The value as the parameter's type, or ValueError saying why it is not one."""
    if p.type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{p.label}: expected yes or no, got {value!r}")
    elif p.type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{p.label}: expected text, got {value!r}")
    else:
        if isinstance(value, str):
            text = value.strip()
            try:
                value = int(text)
            except ValueError:
                try:
                    value = float(text)
                except ValueError:
                    raise ValueError(f"{p.label}: expected a number, got {value!r}") from None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{p.label}: expected a number, got {value!r}")
        if p.type == "integer":
            if float(value) != int(value):
                raise ValueError(f"{p.label}: expected a whole number, got {value}")
            value = int(value)
        if p.min is not None and value < p.min:
            raise ValueError(f"{p.label}: {value} is below the minimum {p.min:g}")
        if p.max is not None and value > p.max:
            raise ValueError(f"{p.label}: {value} is above the maximum {p.max:g}")
    if p.choices is not None and value not in p.choices:
        raise ValueError(f"{p.label}: {value!r} is not one of {p.choices}")
    return value


def _rows(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:EXAMPLES])
    more = f" and {len(numbers) - EXAMPLES} more" if len(numbers) > EXAMPLES else ""
    return f"row{'s' if len(numbers) > 1 else ''} {shown}{more}"


def _fits(column_type: str, value: Any) -> bool:
    if column_type == "boolean":
        return isinstance(value, bool)
    if column_type == "string":
        return isinstance(value, str | int | float) and not isinstance(value, bool)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return column_type == "number" or float(value).is_integer()


def check_table(spec_input: AppInput, data: Any) -> list[str]:
    """What is wrong with a table for an input, in the user's terms. Rows count from 2, as in a
    spreadsheet whose first row is the header."""
    if not spec_input.columns:
        return []
    label = spec_input.label
    names = [c.name for c in spec_input.columns]
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        return [f"{label}: expected a table with the columns {names}"]
    if not data:
        return [f"{label}: the file has no rows"]
    present = {key for row in data for key in row}
    missing = [name for name in names if name not in present]
    if missing:
        return [f"{label}: the column(s) {missing} are missing; the file has {sorted(present)}"]
    problems = []
    for column in spec_input.columns:
        empty = [i + 2 for i, row in enumerate(data) if row.get(column.name) is None]
        if empty and column.required:
            problems.append(f"{label}: {column.name!r} is empty in {_rows(empty)}")
        if column.type:
            wrong = [
                (i + 2, row[column.name])
                for i, row in enumerate(data)
                if row.get(column.name) is not None and not _fits(column.type, row[column.name])
            ]
            if wrong:
                first = ", ".join(f"{value!r} in row {n}" for n, value in wrong[:EXAMPLES])
                more = f" and {len(wrong) - EXAMPLES} more" if len(wrong) > EXAMPLES else ""
                problems.append(f"{label}: {column.name!r} should be {column.type}: {first}{more}")
    return problems


def check_spec(spec: AppSpec, instance: Any, solve: dict[str, Any]) -> list[str]:
    """What keeps app.json from working with these files."""
    if not isinstance(instance, dict):
        return ["instance.json must be a JSON object for an app"]
    problems = []
    keys = [i.key for i in spec.inputs]
    names = [p.name for p in spec.parameters]
    for kind, values in (("input key", keys), ("parameter name", names)):
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            problems.append(f"repeated {kind}s: {repeated}")
    for spec_input in spec.inputs:
        if spec_input.key not in instance:
            problems.append(f"input {spec_input.key!r}: instance.json has no such key")
            continue
        problems += [
            f"input {spec_input.key!r}, on the packaged data: {problem}"
            for problem in check_table(spec_input, instance[spec_input.key])
        ]
    try:
        values = defaults(spec, instance, solve)
    except ProjectError as exc:
        return [*problems, str(exc)]
    for p in spec.parameters:
        where, path = _path(p.target)
        if where == "instance":
            if path[0] in keys:
                problems.append(f"parameter {p.name!r}: {p.target} is inside the input {path[0]!r}")
            try:
                _get(instance, path)
            except KeyError:
                problems.append(f"parameter {p.name!r}: instance.json has no {p.target[9:]}")
                continue
        if values[p.name] is None:
            if where == "instance" or path[0] != "max_duration_secs":
                problems.append(f"parameter {p.name!r}: the packaged value is null")
            continue
        try:
            coerce(p, values[p.name])
        except ValueError as exc:
            problems.append(f"parameter {p.name!r}, its packaged value: {exc}")
    return problems


def build_instance(
    spec: AppSpec, base: dict[str, Any], tables: dict[str, Any], values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The instance and the solve overrides a case's tables and parameter values make."""
    instance = copy.deepcopy(base)
    instance.update(tables)
    overrides = {}
    for p in spec.parameters:
        value = values.get(p.name)
        if value is None:
            continue
        where, path = _path(p.target)
        if where == "instance":
            _set(instance, path, value)
        else:
            overrides[path[0]] = value
    return instance, overrides


# --- packaging ---------------------------------------------------------------------------------


def package(project: Project, rev: int) -> tuple[bytes, AppSpec]:
    """A revision as a zip ``App.open_package`` runs."""
    files, summary, view, _ = project.load_revision(rev)
    if APP_FILE not in files:
        raise ProjectError(
            f"revision {rev} has no app.json; ask the agent to make the model an app, then "
            "package the revision that has it"
        )
    spec = load_spec(files[APP_FILE])
    try:
        instance, solve = json.loads(files["instance.json"]), json.loads(files["solve.json"])
    except json.JSONDecodeError as exc:
        raise ProjectError(f"revision {rev}: invalid JSON: {exc}") from exc
    problems = check_spec(spec, instance, solve)
    if problems:
        raise ProjectError("app.json does not fit the revision:\n" + "\n".join(problems))
    manifest = {
        "format": PACKAGE_FORMAT,
        "title": spec.title,
        "project": project.id,
        "rev": rev,
        "packaged_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "optopus": docs.installed_commit(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PACKAGE_MANIFEST, json.dumps(manifest, indent=2))
        for name, content in sorted(files.items()):
            archive.writestr(f"model/{name}", content)
        if summary is not None:
            archive.writestr("sample/result.json", summary.model_dump_json())
            archive.writestr(
                "sample/view.json",
                json.dumps({"view": view.model_dump(mode="json")} if view else {}),
            )
    return buffer.getvalue(), spec


_PACKAGE_MEMBER = re.compile(
    "|".join(
        [re.escape(PACKAGE_MANIFEST), r"sample/(?:result|view)\.json"]
        + [f"model/{re.escape(name)}" for name in ALL_FILES]
    )
)


class App:
    def __init__(self, root: Path):
        self.root = root
        self.model = root / "model"
        self.manifest: dict[str, Any] = json.loads((root / PACKAGE_MANIFEST).read_text())
        self.files = {
            name: (self.model / name).read_text()
            for name in ALL_FILES
            if (self.model / name).is_file()
        }
        self.spec = load_spec(self.files[APP_FILE])
        self.instance: dict[str, Any] = json.loads(self.files["instance.json"])
        self.solve: dict[str, Any] = json.loads(self.files["solve.json"])
        self.cases: dict[str, Case] = {}

    async def prebuild(self) -> Path | None:
        """Checks the package's own files and builds its Rust port, if it has one, so that an
        image of the app runs it without cargo (docs/adr/0010). Returns the binary."""
        problems = check_spec(self.spec, self.instance, self.solve)
        if problems:
            raise ProjectError("app.json does not fit the package:\n" + "\n".join(problems))
        solve_request(self.solve, self.instance, self.model / "model.py", {})
        return await rust_binary(self.solve, self.files.get("rust/main.rs"))

    async def self_test(self, seconds: float = SELF_TEST_SECONDS) -> RunSummary:
        """Solves the packaged data once, briefly, and renders its view: what an app's image
        checks before it is handed over."""
        request = solve_request(
            self.solve,
            self.instance,
            self.model / "model.py",
            {"max_duration_secs": seconds, "runs": 1},
        )
        binary = await rust_binary(self.solve, self.files.get("rust/main.rs"))

        async def ignore(_: RunSummary) -> None:
            pass

        summary = await run_solve(request, 0, self.model, ignore, solve_timeout(request), binary)
        if summary.error:
            raise ProjectError(f"the packaged data does not solve: {summary.error.message}")
        _, error = await render_view(self.model / "view.py", self.instance, summary)
        if error:
            raise ProjectError(f"view.py fails on the packaged data:\n{error}")
        return summary

    @classmethod
    def open_package(cls, path: Path, home: Path | None = None) -> App:
        """Unpacks a package and opens it. The directory is named by the model's files, so a
        revision packaged again opens with the cases given to it before."""
        contents = _unpack(read_package(path))
        digest = hashlib.sha256()
        for name in sorted(contents):
            if name.startswith("model/"):
                digest.update(name.encode() + b"\0" + contents[name] + b"\0")
        root = (home or studio_home()) / "apps" / digest.hexdigest()[:16]
        if not (root / PACKAGE_MANIFEST).is_file():
            staging = root.with_name(root.name + ".unpacking")
            shutil.rmtree(staging, ignore_errors=True)
            for name, content in contents.items():
                (staging / name).parent.mkdir(parents=True, exist_ok=True)
                (staging / name).write_bytes(content)
            staging.replace(root)
        return cls(root)

    def info(self) -> AppInfo:
        sample = view = None
        if (self.root / "sample" / "result.json").is_file():
            sample = RunSummary.model_validate_json(
                (self.root / "sample" / "result.json").read_text()
            )
            stored = json.loads((self.root / "sample" / "view.json").read_text())
            view = ViewSpec.model_validate(stored["view"]) if stored.get("view") else None
        return AppInfo(
            spec=self.spec,
            project=self.manifest["project"],
            rev=self.manifest["rev"],
            packaged_at=self.manifest["packaged_at"],
            defaults=defaults(self.spec, self.instance, self.solve),
            sample=sample,
            sample_view=view,
        )

    def new_case(self) -> Case:
        case = Case(self, self.root / "cases" / uuid.uuid4().hex[:12])
        case.save()
        self.cases[case.id] = case
        return case

    def case(self, case_id: str) -> Case:
        if case_id in self.cases:
            return self.cases[case_id]
        root = self.root / "cases" / case_id
        if not CASE_ID.match(case_id) or not (root / "case.json").is_file():
            raise ProjectError(f"no case {case_id!r}")
        self.cases[case_id] = Case(self, root)
        return self.cases[case_id]


def _unpack(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if sum(info.file_size for info in members) > MAX_PACKAGE_BYTES:
                raise ProjectError("the package unpacks to too much data")
            contents = {info.filename: archive.read(info) for info in members}
    except zipfile.BadZipFile as exc:
        raise ProjectError(f"not a zip file: {exc}") from exc
    unexpected = [name for name in contents if not _PACKAGE_MEMBER.fullmatch(name)]
    if unexpected:
        raise ProjectError(f"not an app package: it holds {unexpected[:EXAMPLES]}")
    try:
        manifest = json.loads(contents[PACKAGE_MANIFEST])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ProjectError(f"not an app package: {PACKAGE_MANIFEST} is missing or broken") from exc
    if manifest.get("format") != PACKAGE_FORMAT:
        raise ProjectError(f"the package is in a format this studio cannot run: {manifest!r}")
    for name in ("model/model.py", "model/view.py", "model/instance.json", "model/solve.json"):
        if name not in contents:
            raise ProjectError(f"not an app package: {name} is missing")
    if f"model/{APP_FILE}" not in contents:
        raise ProjectError("not an app package: model/app.json is missing")
    return contents


def read_package(path: Path) -> bytes:
    """A package's zip, from the zip or from the folder it was unpacked into (Safari unpacks a
    downloaded zip by default). A folder's hidden files, such as .DS_Store, are left out."""
    if not path.is_dir():
        return path.read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(path.rglob("*")):
            name = file.relative_to(path).as_posix()
            if file.is_file() and not any(part.startswith(".") for part in name.split("/")):
                archive.write(file, name)
    return buffer.getvalue()


def package_manifest(data: bytes) -> dict[str, Any]:
    """The manifest of a package, once the package is checked as ``App.open_package`` checks it."""
    return json.loads(_unpack(data)[PACKAGE_MANIFEST])


class Case:
    """One set of inputs, saved as they are given, and what solving them gave."""

    def __init__(self, app: App, root: Path):
        self.app = app
        self.root = root
        self.id = root.name
        self.status: Status = "draft"
        self.parameters: dict[str, Any] = {}
        self.problems: list[str] = []
        self.note = ""
        self.rows: dict[str, int | None] = {}
        self.summary: RunSummary | None = None
        self.view: ViewSpec | None = None
        self.view_error: str | None = None
        self.task: asyncio.Task[None] | None = None
        if (root / "case.json").is_file():
            stored = json.loads((root / "case.json").read_text())
            self.status = stored["status"]
            self.parameters = stored["parameters"]
            self.problems = stored["problems"]
            self.rows = stored["rows"]
            self.note = stored.get("note", "")
            if self.status == "solving":  # the app stopped during the solve
                self.status, self.problems = "draft", ["the app stopped before the solve ended"]
        if (root / "result.json").is_file():
            self.summary = RunSummary.model_validate_json((root / "result.json").read_text())
        if (root / "view.json").is_file():
            stored = json.loads((root / "view.json").read_text())
            self.view = ViewSpec.model_validate(stored["view"]) if stored["view"] else None
            self.view_error = stored["error"]

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        stored = {
            "status": self.status,
            "parameters": self.parameters,
            "problems": self.problems,
            "rows": self.rows,
            "note": self.note,
        }
        (self.root / "case.json").write_text(json.dumps(stored, ensure_ascii=False, indent=1))

    def input_file(self, key: str) -> Path | None:
        directory = self.root / "inputs" / key
        files = sorted(directory.iterdir()) if directory.is_dir() else []
        return files[0] if files else None

    def spec_input(self, key: str) -> AppInput:
        for spec_input in self.app.spec.inputs:
            if spec_input.key == key:
                return spec_input
        raise ProjectError(f"the app has no input {key!r}")

    def state(self) -> CaseState:
        inputs = []
        for spec_input in self.app.spec.inputs:
            path = self.input_file(spec_input.key)
            if path is not None:
                rows = self.rows.get(spec_input.key)
                inputs.append(CaseInput(key=spec_input.key, file=path.name, rows=rows))
        return CaseState(
            id=self.id,
            status=self.status,
            inputs=inputs,
            parameters=self.parameters,
            problems=self.problems,
            note=self.note,
            summary=self.summary,
            view=self.view,
            view_error=self.view_error,
        )

    def _read(self, spec_input: AppInput, path: Path) -> tuple[Any, list[str]]:
        try:
            data = read_records(path)
        except (TableError, ValueError, OSError) as exc:
            return None, [f"{spec_input.label}: cannot read {path.name}: {exc}"]
        self.rows[spec_input.key] = len(data) if isinstance(data, list) else None
        return data, check_table(spec_input, data)

    def set_input(self, key: str, name: str, content: bytes) -> None:
        spec_input = self.spec_input(key)
        self._check_editable()
        name = Path(name).name
        if not UPLOAD_NAME.match(name) or name.startswith("."):
            raise ProjectError(f"invalid file name {name!r}")
        if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
            raise ProjectError(f"{name}: expected one of {UPLOAD_SUFFIXES}")
        directory = self.root / "inputs" / key
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        (directory / name).write_bytes(content)
        _, self.problems = self._read(spec_input, directory / name)
        self.save()

    def remove_input(self, key: str) -> None:
        self.spec_input(key)
        self._check_editable()
        shutil.rmtree(self.root / "inputs" / key, ignore_errors=True)
        self.rows.pop(key, None)
        self.problems = []
        self.save()

    def set_note(self, note: str) -> None:
        """What the app's user says about the case, for whoever reads it in the studio."""
        if len(note) > MAX_NOTE_CHARS:
            raise ProjectError(f"the note is longer than {MAX_NOTE_CHARS} characters")
        self.note = note
        self.save()

    def _check_editable(self) -> None:
        if self.status == "solving":
            raise ProjectError("the case is being solved")

    def prepare(self, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        """The instance and overrides the inputs and ``values`` make, or the problems."""
        problems, parameters = [], {}
        for p in self.app.spec.parameters:
            if values.get(p.name) is None:
                continue
            try:
                parameters[p.name] = coerce(p, values[p.name])
            except ValueError as exc:
                problems.append(str(exc))
        unknown = sorted(set(values) - {p.name for p in self.app.spec.parameters})
        if unknown:
            problems.append(f"the app has no parameters {unknown}")
        tables = {}
        for spec_input in self.app.spec.inputs:
            path = self.input_file(spec_input.key)
            if path is None:
                if spec_input.required:
                    problems.append(f"{spec_input.label}: a file is required")
                continue
            data, found = self._read(spec_input, path)
            problems += found
            tables[spec_input.key] = data
        self.parameters = parameters
        if problems:
            return {}, {}, problems
        instance, overrides = build_instance(self.app.spec, self.app.instance, tables, parameters)
        return instance, overrides, []

    async def solve(self, values: dict[str, Any], on_update: Callable[[], None] = lambda: None):
        """Checks the inputs and, when they are fine, solves them in the background."""
        self._check_editable()
        instance, overrides, problems = self.prepare(values)
        self.problems = problems
        self.summary, self.view, self.view_error = None, None, None
        for name in ("result.json", "view.json", "instance.json"):
            (self.root / name).unlink(missing_ok=True)
        if problems:
            self.status = "draft"
            self.save()
            return
        (self.root / "instance.json").write_text(json.dumps(instance, ensure_ascii=False))
        self.status = "solving"
        self.save()
        self.task = asyncio.create_task(self._solve(instance, overrides, on_update))

    async def _solve(self, instance: dict[str, Any], overrides: dict[str, Any], on_update) -> None:
        app = self.app
        try:
            request = solve_request(app.solve, instance, app.model / "model.py", overrides)
            binary = await rust_binary(app.solve, app.files.get("rust/main.rs"))

            async def progress(summary: RunSummary) -> None:
                self.summary = summary
                on_update()

            summary = await run_solve(
                request, 0, app.model, progress, solve_timeout(request), binary
            )
            self.summary = summary
            (self.root / "result.json").write_text(summary.model_dump_json())
            self.view, self.view_error = await render_view(app.model / "view.py", instance, summary)
            payload = {
                "view": self.view.model_dump(mode="json") if self.view else None,
                "error": self.view_error,
            }
            (self.root / "view.json").write_text(json.dumps(payload))
            self.status = "failed" if summary.error else "solved"
        except ProjectError as exc:
            self.status, self.problems = "failed", [str(exc)]
        except Exception as exc:
            log.exception("case %s failed", self.id)
            self.status, self.problems = "failed", [f"the app failed: {exc}"]
        finally:
            self.save()
            on_update()


# --- cases, out of an app and into the studio --------------------------------------------------

CASE_MANIFEST = "optopus-studio-case.json"
CASE_FORMAT = 1
_CASE_MEMBER = re.compile(
    rf"{re.escape(CASE_MANIFEST)}|(?:instance|result|view)\.json"
    r"|inputs/(?P<key>[A-Za-z_][A-Za-z0-9_-]*)/(?P<file>[^/]+)"
)


def export_case(case: Case) -> bytes:
    """A case as a zip the studio the app came from imports: what was given, and what it gave."""
    manifest = {
        "format": CASE_FORMAT,
        "case": case.id,
        "app": {
            "title": case.app.spec.title,
            "project": case.app.manifest["project"],
            "rev": case.app.manifest["rev"],
            "packaged_at": case.app.manifest["packaged_at"],
        },
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "image": os.environ.get(IMAGE_VARIABLE),
        "status": case.status,
        "parameters": case.parameters,
        "problems": case.problems,
        "note": case.note,
        "inputs": [i.model_dump() for i in case.state().inputs],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(CASE_MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        for name in ("instance.json", "result.json", "view.json"):
            if (case.root / name).is_file():
                archive.write(case.root / name, name)
        for spec_input in case.app.spec.inputs:
            path = case.input_file(spec_input.key)
            if path is not None:
                archive.write(path, f"inputs/{spec_input.key}/{path.name}")
    return buffer.getvalue()


def check_case_member(name: str, content: bytes) -> None:
    """Rejects a file a case cannot hold, or one the studio would fail on later."""
    match = _CASE_MEMBER.fullmatch(name)
    file = match and match["file"]
    if not match or (file and (not UPLOAD_NAME.match(file) or file.startswith("."))):
        raise ProjectError(f"a case holds no {name!r}")
    if file:
        return
    try:
        if name == "result.json":
            RunSummary.model_validate_json(content)
        else:
            json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ProjectError(f"{name} in the case is broken: {exc}") from exc


def import_case(project: Project, data: bytes) -> str:
    """Stores a case an app exported under the project's cases/, and returns its id."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            if sum(info.file_size for info in members) > MAX_PACKAGE_BYTES:
                raise ProjectError("the case unpacks to too much data")
            contents = {info.filename: archive.read(info) for info in members}
    except zipfile.BadZipFile as exc:
        raise ProjectError(f"not a zip file: {exc}") from exc
    try:
        manifest = json.loads(contents[CASE_MANIFEST])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ProjectError(f"not a case from an app: {CASE_MANIFEST} is missing") from exc
    if manifest.get("format") != CASE_FORMAT or not CASE_ID.match(str(manifest.get("case"))):
        raise ProjectError("not a case this studio can read")
    for name, content in contents.items():
        check_case_member(name, content)
    root = project.root / "cases" / manifest["case"]
    shutil.rmtree(root, ignore_errors=True)
    for name, content in contents.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(content)
    return manifest["case"]


def project_cases(project: Project) -> list[str]:
    base = project.root / "cases"
    return (
        sorted(p.name for p in base.iterdir() if (p / CASE_MANIFEST).is_file())
        if (base.is_dir())
        else []
    )


def case_dir(project: Project, case_id: str) -> Path:
    if case_id not in project_cases(project):
        raise ProjectError(f"no case {case_id!r}; the cases are {project_cases(project)}")
    return project.root / "cases" / case_id


def case_inputs(root: Path) -> dict[str, Path]:
    inputs = root / "inputs"
    found = {}
    for directory in sorted(inputs.iterdir()) if inputs.is_dir() else []:
        files = sorted(directory.iterdir())
        if files:
            found[directory.name] = files[0]
    return found


def _case_app(project: Project, manifest: dict[str, Any]) -> tuple[dict[str, str], str]:
    """The files of the revision the case's app was packaged from, if this project has it."""
    app = manifest["app"]
    if app.get("project") == project.id and app.get("rev") in project.revisions():
        files = project.load_revision(app["rev"])[0]
        return files, f"revision {app['rev']} of this project"
    return {}, f"revision {app.get('rev')} of project {app.get('project')}, which is not this one"


def describe_case(project: Project, case_id: str, preview_file: Callable[[Path], str]) -> str:
    """What the agent reads of a case: where it came from, what went wrong, and its data."""
    root = case_dir(project, case_id)
    manifest = json.loads((root / CASE_MANIFEST).read_text())
    _, origin = _case_app(project, manifest)
    lines = [
        f"case {case_id} from the app {manifest['app']['title']!r}, packaged from {origin}",
        f"status: {manifest['status']}",
    ]
    if manifest.get("image"):
        lines.append(f"run in the image {manifest['image']}")
    if manifest.get("note"):
        lines.append(f"the user's note on the case, in their words:\n{manifest['note']}")
    lines.append(
        f"parameters the user set: {json.dumps(manifest['parameters'], ensure_ascii=False)}"
    )
    for problem in manifest["problems"]:
        lines.append(f"the app refused the inputs: {problem}")
    if (root / "result.json").is_file():
        summary = RunSummary.model_validate_json((root / "result.json").read_text())
        if summary.error:
            lines.append(f"the solve failed at {summary.error.stage}: {summary.error.message}")
            if summary.error.traceback:
                lines.append(summary.error.traceback[-2000:])
        elif summary.best_run is not None:
            best = summary.runs[summary.best_run]
            lines.append(
                f"solved: best objective {best.best_objective:g} over {len(summary.runs)} runs"
            )
    if (root / "view.json").is_file():
        error = json.loads((root / "view.json").read_text()).get("error")
        if error:
            lines.append(f"view.py failed on it:\n{error}")
    given = case_inputs(root)
    if not given:
        lines.append("the user gave no files: the packaged data was used")
    for key, path in given.items():
        lines.append(f"\ninput {key}:\n{preview_file(path)}")
    lines.append(
        "\nload_case puts this case's data into instance.json, to reproduce it with check_model "
        "or run_solver."
    )
    return "\n".join(lines)


def load_case(project: Project, case_id: str) -> str:
    """Writes the case's instance into the project's instance.json; says how it was made."""
    root = case_dir(project, case_id)
    if (root / "instance.json").is_file():
        project.write_file("instance.json", (root / "instance.json").read_text())
        return "instance.json is now the instance the app solved"
    # The app refused the inputs, so it built no instance: build it as the app would have.
    manifest = json.loads((root / CASE_MANIFEST).read_text())
    files, origin = _case_app(project, manifest)
    files = files or project.files()
    if APP_FILE not in files:
        raise ProjectError(f"cannot rebuild the case: {origin} has no app.json")
    spec = load_spec(files[APP_FILE])
    tables = {}
    for key, path in case_inputs(root).items():
        try:
            tables[key] = read_records(path)
        except (TableError, ValueError, OSError) as exc:
            raise ProjectError(f"cannot read the case's {path.name}: {exc}") from exc
    instance, overrides = build_instance(
        spec, json.loads(files["instance.json"]), tables, manifest["parameters"]
    )
    project.write_file("instance.json", json.dumps(instance, ensure_ascii=False, indent=1))
    note = f" The app's solve settings were {overrides}." if overrides else ""
    return (
        "instance.json is now the case's data, built from its files and parameters over the "
        f"instance of {origin}; the app refused it, so expect what it reported.{note}"
    )
