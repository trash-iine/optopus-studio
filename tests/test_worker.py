"""The Python worker: the protocol it speaks, and the solves it runs."""

import importlib.util
import io
import itertools
import json
import math
import subprocess
import sys

import optopus
import pytest
from pydantic import TypeAdapter

from optopus_studio import worker
from optopus_studio.protocol import SolveRequest, WorkerEvent
from tests.conftest import EXAMPLE_NAMES, EXAMPLES, example_request, one, write_model

EVENTS = TypeAdapter(list[WorkerEvent])


def run_worker(request: SolveRequest, progress: bool = False) -> list:
    """The worker's events, without the progress ones unless asked for."""
    stdout = io.StringIO()
    worker.main(io.StringIO(request.model_dump_json() + "\n"), stdout)
    events = EVENTS.validate_python([json.loads(line) for line in stdout.getvalue().splitlines()])
    return [e for e in events if progress or e.type != "progress"]


def load_view(name):
    spec = importlib.util.spec_from_file_location(f"view_{name}", EXAMPLES / name / "view.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_the_worker_speaks_the_protocol_as_a_process(name):
    request = example_request(name)
    done = subprocess.run(
        [sys.executable, "-m", "optopus_studio.worker"],
        input=request.model_dump_json() + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    events = EVENTS.validate_python([json.loads(line) for line in done.stdout.splitlines()])
    events = [e for e in events if e.type != "progress"]
    runs = request.runs * len(request.variants)
    assert [e.type for e in events] == ["started"] + ["run_finished"] * runs + ["done"]
    runs = events[1:-1]
    best = (max if events[0].higher_is_better else min)(r.best_objective for r in runs)
    assert events[-1].best_objective == best


def test_run_i_matches_run_i_of_a_multi_run_report():
    request = example_request("tsp", runs=3, seed=11)
    events = run_worker(request)
    module = worker.load_model(request.model_path)
    heuristic = worker.build_heuristic(request.variants[0].heuristic)
    report = heuristic.run(module.build(request.instance), runs=3, seed=11)
    for event, run in zip(events[1:-1], report.runs, strict=True):
        assert event.seed == run.seed
        assert event.best_objective == run.best_objective
        assert [p[1:] for p in event.trajectory] == [p[1:] for p in run.trajectory]


def test_the_knapsack_reaches_the_brute_force_optimum():
    request = example_request("knapsack")
    items, capacity = request.instance["items"], request.instance["capacity"]
    optimum = max(
        sum(i["value"] for i, x in zip(items, xs, strict=True) if x)
        for xs in itertools.product([0, 1], repeat=len(items))
        if sum(i["weight"] for i, x in zip(items, xs, strict=True) if x) <= capacity
    )
    assert run_worker(request)[-1].best_objective == optimum


def test_the_job_shop_view_decodes_the_schedule_the_core_scores():
    request = example_request("job_shop")
    view = load_view("job_shop")
    for run in run_worker(request)[1:-1]:
        tasks = view.schedule(request.instance, run.solution)
        assert max(t["end"] for t in tasks) == run.best_objective


def test_the_tsp_view_measures_the_tour_the_core_scores():
    request = example_request("tsp")
    cities = request.instance["cities"]
    for run in run_worker(request)[1:-1]:
        tour = run.solution
        length = sum(
            math.dist((cities[a]["x"], cities[a]["y"]), (cities[b]["x"], cities[b]["y"]))
            for a, b in zip(tour, tour[1:] + tour[:1], strict=True)
        )
        assert length == pytest.approx(run.best_objective)


ONE_MAX = """
import optopus

class Flip:
    def neighbors(self, problem, x):
        return range(len(x))

    def apply(self, problem, x, i):
        return (*x[:i], not x[i], *x[i + 1:])

class OneMax:
    minimize = False
    neighborhoods = {"Flip": Flip()}

    def new_solution(self, rng):
        return tuple(rng.random() < 0.5 for _ in range(8))

    def objective(self, x):
        print("noise on stdout must not break the protocol")
        return float(sum(x))

def build(instance):
    return OneMax()
"""


def test_a_python_problem_runs_and_its_tuple_solution_is_encoded(tmp_path):
    request = SolveRequest(
        model_path=write_model(tmp_path, ONE_MAX),
        instance={},
        variants=one({"kind": "LocalSearch", "neighbor": "Flip", "stop": {"max_iteration": 100}}),
    )
    started, run, done = run_worker(request)
    assert started.problem == "OneMax"
    assert started.higher_is_better
    assert run.solution == [True] * 8
    assert done.best_objective == 8.0


def test_nested_heuristics_and_tuple_arguments_are_built():
    heuristic = worker.build_heuristic(
        {
            "kind": "Iterated",
            "search": {
                "kind": "TabuSearch",
                "neighbor": "Swap",
                "tabu_tenure": [2, 4],
                "stop": {"max_iteration": 50},
            },
            "perturbation": {
                "kind": "RandomWalk",
                "neighbor": "Swap",
                "stop": {"max_iteration": 3},
            },
            "stop": {"max_iteration": 10},
        }
    )
    assert isinstance(heuristic, optopus.Iterated)


def test_tuning_tuples_and_a_relaxation_object_are_built():
    stop = {"max_iteration": 10}
    alns = {"kind": "AdaptiveLargeNeighborhoodSearch", "scores": [4.0, 2.0, 1.0], "stop": stop}
    assert isinstance(worker.build_heuristic(alns), optopus.AdaptiveLargeNeighborhoodSearch)
    hgs = {
        "kind": "HybridGeneticSearch",
        "penalty_adaptation": [100, 1.2, 0.85, 0.05],
        "initial_population": [4, 2],
        "stop": stop,
    }
    assert isinstance(worker.build_heuristic(hgs), optopus.HybridGeneticSearch)
    bnb = worker.build_heuristic(
        {
            "kind": "BranchAndBound",
            "heuristic": {"kind": "LocalSearch", "neighbor": "Flip", "stop": stop},
            "relaxation": {"kind": "EigenvalueRelaxation", "max_iterations": 10},
        }
    )
    triangle = optopus.MaxCut.from_edges([(0, 1, 1.0), (1, 2, 1.0), (0, 2, 1.0)])
    assert bnb.run(triangle, 1, 0).runs[0].best_objective == 2.0


BROKEN = {
    "build": ("def solve(instance):\n    pass\n", {"kind": "LocalSearch"}),
    "heuristic": (
        "import optopus\ndef build(i):\n    return optopus.MaxCut.from_edges([(0, 1, 1.0)])\n",
        {"kind": "Nonsense"},
    ),
    "run": (
        "import optopus\ndef build(i):\n    return optopus.MaxCut.from_edges([(0, 1, 1.0)])\n",
        {"kind": "LocalSearch", "neighbor": "TwoOpt", "stop": {"max_iteration": 10}},
    ),
    "encode": (
        "import optopus\ndef build(i):\n    return optopus.MaxCut.from_edges([(0, 1, 1.0)])\n"
        "def encode_solution(i, s):\n    return set(s)\n",
        {"kind": "LocalSearch", "neighbor": "Flip", "stop": {"max_iteration": 10}},
    ),
}


@pytest.mark.parametrize("stage", BROKEN.keys())
def test_a_failure_is_reported_with_its_stage(tmp_path, stage):
    source, heuristic = BROKEN[stage]
    request = SolveRequest(
        model_path=write_model(tmp_path, source), instance={}, variants=one(heuristic)
    )
    error = run_worker(request)[-1]
    assert error.type == "error"
    assert error.stage == stage
    assert error.traceback


def test_a_malformed_request_is_reported():
    stdout = io.StringIO()
    assert worker.main(io.StringIO('{"runs": 0}\n'), stdout) == 2
    assert json.loads(stdout.getvalue())["stage"] == "request"


def test_variants_run_with_the_same_seeds_and_the_best_is_found_across_them():
    request = example_request("workload", runs=2)
    events = run_worker(request)
    started, runs, done = events[0], events[1:-1], events[-1]
    assert started.variants == ["SA", "Tabu", "LAHC"]
    assert [r.run for r in runs] == list(range(6))
    assert [r.variant for r in runs] == [0, 0, 1, 1, 2, 2]
    assert [r.seed for r in runs[:2]] == [r.seed for r in runs[2:4]] == [r.seed for r in runs[4:]]
    assert [r.initial_objective for r in runs[:2]] == [r.initial_objective for r in runs[2:4]]
    assert done.best_objective == min(r.best_objective for r in runs)
    assert runs[done.best_run].best_objective == done.best_objective


def test_the_workload_balances_every_worker_within_their_skills():
    request = example_request("workload")
    instance = request.instance
    events = run_worker(request)
    # Four workers can share the 48 hours evenly, and their skills allow it.
    assert sum(t["hours"] for t in instance["tasks"]) == 48
    solution = events[1:-1][events[-1].best_run].solution
    assert solution["loads"] == [12.0] * 4
    for task, person in zip(instance["tasks"], solution["assignment"], strict=True):
        assert task["skill"] in instance["workers"][person]["skills"]


def test_started_says_whether_the_search_runs_in_compiled_code(tmp_path):
    builtin = run_worker(example_request("tsp", runs=1))[0]
    assert builtin.native
    python = run_worker(
        SolveRequest(
            model_path=write_model(tmp_path, ONE_MAX),
            instance={},
            variants=one({"kind": "LocalSearch", "neighbor": "Flip", "stop": {"max_iteration": 5}}),
        )
    )[0]
    assert not python.native


def test_a_python_problem_reports_progress_while_it_runs(tmp_path):
    request = SolveRequest(
        model_path=write_model(tmp_path, ONE_MAX.replace("range(8)", "range(400)")),
        instance={},
        variants=one(
            {"kind": "RandomWalk", "neighbor": "Flip", "stop": {"max_duration_secs": 0.3}}
        ),
    )
    stream = run_worker(request, progress=True)
    progress = [e for e in stream if e.type == "progress"]
    finished = next(e for e in stream if e.type == "run_finished")
    assert progress, "the first improvement is reported at once"
    assert progress[-1].objective == finished.best_objective
    assert stream.index(progress[0]) < stream.index(finished)
