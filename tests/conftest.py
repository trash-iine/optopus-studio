import json
import shutil
from pathlib import Path

import pytest

from optopus_studio.agent import variants_of
from optopus_studio.projects import PROJECT_FILES, Project
from optopus_studio.protocol import SolveRequest, Variant

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_NAMES = sorted(p.name for p in EXAMPLES.iterdir() if (p / "model.py").is_file())


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    monkeypatch.setenv("OPTOPUS_STUDIO_HOME", str(path))
    return path


def example_request(name: str, **overrides) -> SolveRequest:
    solve = json.loads((EXAMPLES / name / "solve.json").read_text())
    return SolveRequest(
        model_path=str(EXAMPLES / name / "model.py"),
        instance=json.loads((EXAMPLES / name / "instance.json").read_text()),
        variants=variants_of(solve),
        runs=overrides.get("runs", solve["runs"]),
        seed=overrides.get("seed", solve["seed"]),
    )


def example_project(name: str, home: Path) -> Project:
    project = Project.create(home)
    for file in PROJECT_FILES:
        shutil.copy(EXAMPLES / name / file, project.work / file)
    return project


def one(heuristic: dict) -> list[Variant]:
    return [Variant(label="h", heuristic=heuristic)]


def write_model(tmp_path: Path, source: str) -> str:
    path = tmp_path / "model.py"
    path.write_text(source)
    return str(path)
