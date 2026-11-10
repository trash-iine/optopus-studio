"""Diagnosing a search on the benchmark (diagnosis.py, probe.py)."""

import asyncio
import json

import pytest

from optopus_studio import bench, campaign, diagnosis
from optopus_studio.agent import Tools
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchProgress
from tests.test_agent_tools import Recorder, call, text
from tests.test_bench import random_cities, tsp_bench, with_heuristic
from tests.test_candidates import WALK
from tests.test_recipes import BINS

MODEL = (
    BINS
    + """

def build(instance):
    return Bins()


def explain(instance, s):
    loads = [0] * BINS
    for size, b in zip(SIZES, s):
        loads[b] += size
    return {"fullest": max(loads), "emptiest": min(loads)}
"""
)
# A descent that only swaps: from a random start, moving an item still helps.
SWAPS = {"kind": "LocalSearch", "neighbor": "Swap", "stop": {}}


def bins(home, heuristic=SWAPS) -> Project:
    """Items into bins, a problem written in Python with two neighborhoods and no delta."""
    project = Project.create(home)
    project.write_file("instance.json", "{}")
    project.write_file("model.py", MODEL)
    project.write_file("solve.json", json.dumps({"heuristic": heuristic, "runs": 1, "seed": 0}))
    bench.add_instance(project, "ten", "train", "the sizes", {"sizes": 10})
    bench.configure(project, runs=6, max_duration_secs=None, max_iteration=300)
    return project


def diagnose(project, **kwargs) -> diagnosis.Diagnosis:
    return asyncio.run(diagnosis.diagnose(project, **kwargs))


def test_a_probe_names_the_neighborhood_the_search_leaves_unused(home):
    project = bins(home)
    d = diagnose(project)
    probes = d.probes()
    assert set(probes) == {"Move", "Swap"}
    improved, probed, gain = probes["Move"]
    assert (probed, probes["Swap"][0]) == (6, 0)
    assert improved > 0
    assert gain > 0
    unused = [r for r in d.readings if "a neighborhood the search does not use" in r]
    assert len(unused) == 1
    assert unused[0].startswith("a short descent in Move")
    assert unused[0].endswith("[composition, heuristic]")
    report = diagnosis.report(d)
    assert report.startswith("diagnosis 1: variant LocalSearch of the work files on 1 train")
    assert "ten: mean " in report
    assert "known none yet" in report
    assert f"Move improves {improved} of 6" in report
    assert "explain(), mean per best solution: fullest " in report
    record = bench.diagnoses(project)[0]
    assert record["instances"][0]["shape"] == ""
    assert "solution" not in record["instances"][0]["runs"][0]
    assert record["instances"][0]["runs"][0]["terms"].keys() == {"fullest", "emptiest"}


def test_a_python_problems_calls_are_counted_apart_from_its_runs(home):
    project = bins(
        home, {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [2, 4], "stop": {}}
    )
    d = diagnose(project)
    calls = d.calls()
    assert calls["iterations"] == 300
    count, seconds = calls["methods"]["Move.neighbors"]
    assert count == 300
    assert seconds > 0
    assert calls["methods"]["Move.apply"][0] > 300
    assert calls["methods"]["Swap.neighbors"] == [0, 0.0]
    assert calls["objective"][0] > 300
    assert calls["deltas"] == {"Move": [0, 0], "Swap": [0, 0]}
    assert not d.native
    report = diagnosis.report(d)
    assert "calls, share of a counted run's time" in report
    assert "Move.neighbors" in report
    # No neighborhood prices a move, so each is applied and scored.
    assert any(r.endswith("[delta]") and "have no delta" in r for r in d.readings), d.readings
    # The runs themselves are not the counted one: all six are reported.
    assert len(d.instances[0].runs) == 6


def test_a_benchmark_that_cannot_tell_searches_apart_is_said_first(home):
    project, rev = tsp_bench(home, train=0, validation=0)
    for name in ("a", "b"):
        bench.add_instance(project, name, "train", "five", {"cities": random_cities(1, n=5)})
    d = diagnose(project, rev=rev)
    assert d.native
    assert len(d.readings) == 1
    assert d.readings[0].startswith("every run on every instance ends at the same objective")
    assert "Make it harder" in d.readings[0]
    assert "one of optopus's own, which runs compiled" in diagnosis.report(d)


def test_the_gap_is_measured_to_the_best_known(home):
    project, rev = tsp_bench(home)
    asyncio.run(bench.evaluate(project, rev))
    with_heuristic(project, WALK)
    d = diagnose(project)
    first = d.instances[0]
    assert first.known == bench.best_known(project)["tsp0"]["objective"]
    assert first.known_source == "evaluation 1"
    assert d.gap(first) > diagnosis.FAR
    assert [p.name for p in d.failures()] == sorted(
        ("tsp0", "tsp1"), key=lambda n: -d.gap(next(p for p in d.instances if p.name == n))
    )
    far = next(r for r in d.readings if r.startswith("the runs end furthest"))
    assert "from the best known, evaluation 1; cities 40)" in far
    # A walk's best is no local optimum of its own move.
    assert any(
        "the search stops before it has finished with its own moves" in r for r in d.readings
    )
    shown = diagnosis.state(bench.diagnoses(project)[0])
    assert (shown.rev, shown.variant, len(shown.instances)) == (None, "RandomWalk", 2)
    assert shown.instances[0].known == first.known
    assert shown.readings == d.readings


def test_a_diagnosis_runs_through_the_tool_and_reaches_the_brief(home):
    project, rev = tsp_bench(home, validation=2)
    tools = Tools(project, Recorder())
    result = call(tools.diagnose, rev=rev, neighbors=["TwoOpt", "OrOpt"])
    assert not result["is_error"], text(result)
    assert "probes, a short descent from each run's best solution: TwoOpt improves" in text(result)
    progress = [
        (e.task, e.done, e.total) for e in tools.broadcast.events if isinstance(e, BenchProgress)
    ]
    assert progress[-1] == ("diagnosis", 2, 2)
    assert f"diagnoses:\n  1: variant SimulatedAnnealing of revision {rev} on train" in text(
        call(tools.bench_list)
    )
    with pytest.raises(ProjectError, match="nothing is chosen on them"):
        call(tools.diagnose, split="test")
    state = campaign.start(project, rounds=2)
    state["round"] = 1
    assert f"Diagnosis 1 of revision {rev} read:" in campaign.round_brief(project, state)
    bench.diagnoses_dir(project).joinpath("1.json").unlink()
    assert f"Revision {rev} was not diagnosed: diagnose it first" in campaign.round_brief(
        project, state
    )


def test_a_model_that_cannot_be_probed_says_why(home):
    project = bins(home)
    project.write_file("model.py", "def build(instance):\n    raise ValueError('no data')\n")
    with pytest.raises(ProjectError, match="cannot be diagnosed on 'ten': ValueError: no data"):
        diagnose(project)
    project.write_file(
        "model.py", MODEL.replace('return {"fullest"', 'return 1 // 0 or {"fullest"')
    )
    d = diagnose(project, neighbors=["Move", "Nowhere"])
    report = diagnosis.report(d)
    assert "explain() failed: ZeroDivisionError" in report
    assert "cannot probe Nowhere:" in report
    assert set(d.probes()) == {"Move"}
