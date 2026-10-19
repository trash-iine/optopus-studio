"""The Rust worker library and the ports in examples/: protocol, parity, verification."""

import asyncio
import json
import subprocess

import pytest
from pydantic import TypeAdapter

from optopus_studio import rust
from optopus_studio.agent import Tools
from optopus_studio.projects import ProjectError
from optopus_studio.protocol import InitialSolution, RunSummary, SolveRequest, WorkerEvent
from optopus_studio.runner import run_solve
from optopus_studio.verify import verify
from tests.conftest import EXAMPLES, example_project, example_request, one

pytestmark = pytest.mark.skipif(rust.cargo() is None, reason="cargo is not installed")

EVENTS = TypeAdapter(list[WorkerEvent])


def port(name: str) -> str:
    return (EXAMPLES / name / "rust" / "main.rs").read_text()


def binary(source: str):
    built = asyncio.run(rust.build(source))
    assert built.ok, built.log
    return built.binary


def events(binary_path, request: SolveRequest) -> list:
    done = subprocess.run(
        [str(binary_path)], input=request.model_dump_json() + "\n", capture_output=True, text=True
    )
    return EVENTS.validate_python([json.loads(line) for line in done.stdout.splitlines()])


async def ignore(_: RunSummary) -> None:
    pass


def check(name: str, request: SolveRequest, source: str | None = None):
    return asyncio.run(
        verify(
            request,
            binary(source or port(name)),
            EXAMPLES / name,
            EXAMPLES / name / "view.py",
            60.0,
        )
    )


def test_a_build_is_kept_and_reused():
    source = port("tsp")
    first = asyncio.run(rust.build(source))
    assert first.ok
    again = asyncio.run(rust.build(source))
    assert again.cached
    assert again.binary == first.binary


def test_a_built_port_runs_where_there_is_no_cargo(monkeypatch):
    source = port("tsp")
    built = binary(source)
    # An app's image holds the binary and no cargo (docs/adr/0010).
    monkeypatch.setattr(rust, "cargo", lambda: None)
    assert asyncio.run(rust.build(source)).binary == built
    assert not asyncio.run(rust.build(source + "\n")).ok


def test_a_port_that_does_not_compile_returns_the_errors():
    built = asyncio.run(rust.build('fn main() { let x: u32 = "no"; }\n'))
    assert not built.ok
    assert "mismatched types" in built.log


def test_the_rust_worker_speaks_the_protocol_and_reports_progress():
    request = example_request("workload", runs=2)
    stream = events(binary(port("workload")), request)
    kinds = [e.type for e in stream]
    assert kinds[0] == "started"
    assert stream[0].native
    assert kinds.count("run_finished") == 6
    assert kinds[-1] == "done"
    # The first improvement of each run is reported at once.
    assert kinds.count("progress") >= 6
    first_progress = kinds.index("progress")
    assert first_progress < kinds.index("run_finished")


def test_a_built_in_port_reproduces_the_python_worker_exactly():
    verdict = check("tsp", example_request("tsp"))
    assert verdict.ok, verdict.text
    assert "exact: all 3 runs match" in verdict.text


def test_a_python_problem_port_scores_alike_and_searches_as_well():
    verdict = check("workload", example_request("workload"))
    assert verdict.ok, verdict.text
    assert "objective: the port scores all 9 Python solutions the same" in verdict.text
    assert "stat SA:" in verdict.text
    assert "speed LAHC:" in verdict.text


def test_a_port_with_another_objective_fails_verification():
    wrong = port("workload").replace("const SPREAD: f64 = 1e-3;", "const SPREAD: f64 = 2e-3;")
    verdict = check("workload", example_request("workload", runs=1), wrong)
    assert not verdict.ok
    assert "FAIL objective" in verdict.text


@pytest.mark.parametrize(
    ("instance", "heuristic", "stage"),
    [
        ({}, {"kind": "LocalSearch", "neighbor": "TwoOpt"}, "build"),
        (None, {"kind": "Nonsense"}, "heuristic"),
        (None, {"kind": "LocalSearch", "neighbor": "Flip"}, "heuristic"),
        (None, {"kind": "LocalSearch", "neighbor": "TwoOpt", "speed": 3}, "heuristic"),
        (None, {"kind": "TabuSearch", "neighbor": "TwoOpt", "tabu_tenure": 3}, "heuristic"),
        # Two cities leave TwoOpt no move, which the heuristic reports and the run fails on.
        (
            {"cities": [{"name": "a", "x": 0, "y": 0}, {"name": "b", "x": 1, "y": 0}]},
            {
                "kind": "SimulatedAnnealing",
                "neighbor": "TwoOpt",
                "initial_temperature": 1.0,
                "cooling_rate": 0.9,
                "stop": {"max_iteration": 10},
            },
            "run",
        ),
    ],
)
def test_failures_are_reported_with_their_stage(instance, heuristic, stage):
    base = example_request("tsp")
    request = SolveRequest(
        model_path="",
        instance=base.instance if instance is None else instance,
        variants=one(heuristic),
    )
    error = events(binary(port("tsp")), request)[-1]
    assert error.type == "error"
    assert error.stage == stage


@pytest.mark.parametrize("name", ["tsp", "workload"])
def test_both_workers_start_from_the_same_solution(name):
    from tests.test_worker import run_worker

    request = example_request(name, runs=1)
    first = run_worker(request)[1]
    request.initial_solution = InitialSolution(key="plan", solution=first.solution)
    python = run_worker(request)[1]
    port_run = [e for e in events(binary(port(name)), request) if e.type == "run_finished"]
    assert port_run[0].initial_objective == pytest.approx(python.initial_objective)
    assert python.initial_objective == pytest.approx(first.best_objective)


def test_a_solution_the_port_cannot_decode_fails_at_the_start():
    request = example_request("workload", runs=1)
    request.initial_solution = InitialSolution(key="plan", solution={"assignment": [0]})
    error = events(binary(port("workload")), request)[-1]
    assert error.type == "error"
    assert error.stage == "start"


def test_nested_heuristics_run_in_the_rust_worker():
    heuristic = {
        "kind": "Iterated",
        "search": {"kind": "LocalSearch", "neighbor": "TwoOpt", "stop": {"max_iteration": 200}},
        "perturbation": {
            "kind": "RandomWalk",
            "neighbor": "Relocate",
            "stop": {"max_iteration": 3},
        },
        "stop": {"max_iteration": 20},
    }
    request = SolveRequest(
        model_path="", instance=example_request("tsp").instance, variants=one(heuristic)
    )
    summary = asyncio.run(run_solve(request, 1, EXAMPLES, ignore, 60.0, binary(port("tsp"))))
    assert summary.error is None
    assert summary.worker == "rust"
    assert summary.live is None


def test_run_solver_uses_the_port_when_solve_json_asks_for_it(home):
    project = example_project("workload", home)
    solve = json.loads(project.read_file("solve.json"))
    project.write_file("solve.json", json.dumps({**solve, "worker": "rust"}))
    result = asyncio.run(Tools(project, lambda e: asyncio.sleep(0)).run_solver({}))
    assert not result["is_error"], result["content"][0]["text"]
    files, summary, view, _ = project.load_revision(1)
    assert summary.worker == "rust"
    assert "rust/main.rs" in files
    assert view is not None


def test_a_port_that_does_not_compile_makes_no_revision(home):
    project = example_project("workload", home)
    project.write_file("rust/main.rs", "fn main() { nope }\n")
    solve = json.loads(project.read_file("solve.json"))
    project.write_file("solve.json", json.dumps({**solve, "worker": "rust"}))
    with pytest.raises(ProjectError, match="does not build"):
        asyncio.run(Tools(project, lambda e: asyncio.sleep(0)).run_solver({}))
    assert project.revisions() == []


def test_verify_rust_reports_through_the_tool(home):
    project = example_project("workload", home)
    tools = Tools(project, lambda e: asyncio.sleep(0))
    result = asyncio.run(tools.verify_rust({}))
    assert not result["is_error"], result["content"][0]["text"]
    assert result["content"][0]["text"].startswith("verification: PASS")
    assert "speed SA" in result["content"][0]["text"]
    guide = asyncio.run(tools.rust_guide({}))["content"][0]["text"]
    assert "impl StudioProblem for Workload" in guide


def test_progress_catches_up_with_the_best_while_the_run_goes_on():
    heuristic = {
        "kind": "SimulatedAnnealing",
        "neighbor": "Move",
        "initial_temperature": 2.0,
        "cooling_rate": 0.9999,
        "stop": {"max_duration_secs": 0.3},
    }
    request = SolveRequest(
        model_path="", instance=example_request("workload").instance, variants=one(heuristic)
    )
    stream = events(binary(port("workload")), request)
    progress = [e for e in stream if e.type == "progress"]
    finished = next(e for e in stream if e.type == "run_finished")
    # Improvements held back by the 100 ms interval are sent by the ticker, not dropped.
    assert progress[-1].objective == finished.best_objective
    assert all(p.elapsed_secs <= finished.total_time_secs for p in progress)


def test_the_improvement_held_at_the_end_of_a_run_is_sent():
    # The example's runs stop by iterations, well within the ticker's 100 ms interval.
    stream = events(binary(port("workload")), example_request("workload"))
    for finished in (e for e in stream if e.type == "run_finished"):
        mine = [
            e.objective
            for e in stream
            if e.type == "progress" and (e.run, e.variant) == (finished.run, finished.variant)
        ]
        assert mine[-1] == finished.best_objective, (finished.run, finished.variant)
