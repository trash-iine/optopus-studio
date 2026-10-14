"""Starting the worker and viewer processes from the backend."""

import asyncio
import json

from optopus_studio.protocol import RunSummary, SolveRequest
from optopus_studio.runner import render_view, run_solve
from tests.conftest import EXAMPLES, example_request, one, write_model


def solve(request, timeout=60.0):
    updates = []

    async def on_update(summary):
        updates.append(summary.model_copy(deep=True))

    summary = asyncio.run(run_solve(request, 1, EXAMPLES, on_update, timeout))
    return summary, updates


def test_a_solve_reports_every_run_as_it_finishes():
    summary, updates = solve(example_request("job_shop", runs=2))
    assert summary.error is None
    assert summary.problem == "JobShopScheduling"
    assert summary.best_run is not None
    counts = [len(u.runs) for u in updates]
    assert counts[0] == 0
    assert counts == sorted(counts)
    assert counts[-1] == 2
    assert any(u.live for u in updates), "progress shows the run under way"
    assert updates[-1].live is None


def test_a_solve_that_hangs_is_killed(tmp_path):
    request = SolveRequest(
        model_path=write_model(tmp_path, "def build(i):\n    while True:\n        pass\n"),
        instance={},
        variants=one({"kind": "LocalSearch"}),
    )
    summary, _ = solve(request, timeout=1.0)
    assert "longer than" in summary.error.message


def test_a_worker_that_dies_is_reported_with_its_stderr(tmp_path):
    request = SolveRequest(
        model_path=write_model(
            tmp_path, "import os, sys\nprint('dying', file=sys.stderr)\nos._exit(3)\n"
        ),
        instance={},
        variants=one({"kind": "LocalSearch"}),
    )
    summary, _ = solve(request)
    assert "exited with 3" in summary.error.message
    assert "dying" in summary.error.traceback


def view(tmp_path, source, summary=None):
    path = tmp_path / "view.py"
    path.write_text(source)
    return asyncio.run(render_view(path, {}, summary or RunSummary(rev=1), timeout=5.0))


def test_the_example_views_render():
    for name in ("tsp", "job_shop", "knapsack"):
        summary, _ = solve(example_request(name, runs=1))
        instance = json.loads((EXAMPLES / name / "instance.json").read_text())
        spec, error = asyncio.run(render_view(EXAMPLES / name / "view.py", instance, summary))
        assert error is None, error
        assert spec.views


def test_an_invalid_view_spec_is_explained(tmp_path):
    spec, error = view(tmp_path, "def to_view(i, r):\n    return {'views': [{'type': 'pie'}]}\n")
    assert spec is None
    assert "invalid ViewSpec" in error


def test_a_view_that_raises_returns_its_traceback(tmp_path):
    spec, error = view(tmp_path, "def to_view(i, r):\n    return r['best']['solution']\n")
    assert spec is None
    assert "TypeError" in error


def test_a_view_that_hangs_is_killed(tmp_path):
    spec, error = view(tmp_path, "def to_view(i, r):\n    while True:\n        pass\n")
    assert spec is None
    assert "longer than" in error
