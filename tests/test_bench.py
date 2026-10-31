"""Judging a change of the algorithm on the benchmark (bench.py)."""

import asyncio
import json
import math

import pytest

from optopus_studio import bench
from optopus_studio.projects import Project, ProjectError
from tests.conftest import example_project

SA = {
    "kind": "SimulatedAnnealing",
    "neighbor": "TwoOpt",
    "initial_temperature": 20.0,
    "cooling_rate": 0.999,
    "stop": {"max_iteration": 3000},
}


def tsp_bench(home, train=2, validation=1) -> tuple[Project, int]:
    """The TSP example on generated instances, solved once as the baseline."""
    project = example_project("tsp", home)
    project.write_file("solve.json", json.dumps({"heuristic": SA, "runs": 1, "seed": 0}))
    rev = project.snapshot()
    for i in range(train + validation):
        split = "train" if i < train else "validation"
        instance = {"cities": random_cities(i)}
        bench.add_instance(project, f"tsp{i}", split, f"seed {i}", instance)
    bench.configure(project, runs=4, max_duration_secs=None, max_iteration=3000)
    return project, rev


def random_cities(seed: int, n: int = 40) -> list[dict]:
    import random

    rng = random.Random(seed)
    return [{"name": f"C{i}", "x": rng.uniform(0, 100), "y": rng.uniform(0, 100)} for i in range(n)]


def evaluate(project, rev, **kwargs) -> bench.Evaluation:
    return asyncio.run(bench.evaluate(project, rev, **kwargs))


def with_heuristic(project: Project, heuristic: dict) -> None:
    project.write_file("solve.json", json.dumps({"heuristic": heuristic, "runs": 1, "seed": 0}))


def test_the_signed_rank_test_is_exact_on_few_pairs():
    # Five gains, all positive: one sign pattern in 32 reaches it.
    greater, less = bench.wilcoxon([0.1, 0.2, 0.3, 0.4, 0.5])
    assert math.isclose(greater, 1 / 32)
    assert math.isclose(less, 1.0)
    assert bench.wilcoxon([0.0, 0.0]) == (1.0, 1.0)


def test_the_normal_approximation_agrees_with_the_exact_test(monkeypatch):
    gains = [(-1) ** (i % 3 == 0) * (i + 1) / 10 for i in range(40)]
    exact = bench.wilcoxon(gains)
    monkeypatch.setattr(bench, "EXACT_PAIRS", 0)
    approximate = bench.wilcoxon(gains)
    assert approximate[0] == pytest.approx(exact[0], abs=0.01)
    assert approximate[1] == pytest.approx(exact[1], abs=0.01)


def test_the_same_files_are_judged_the_same(home):
    project, rev = tsp_bench(home)
    evaluation = evaluate(project, rev)
    assert evaluation.verdict == "same", bench.report(evaluation)
    assert all(g == 0 for g in evaluation.gains)
    assert "scores all 8 of the candidate's solutions" in evaluation.reference


def test_a_better_search_is_judged_better_and_kept(home):
    project, rev = tsp_bench(home)
    with_heuristic(project, {"kind": "RandomWalk", "neighbor": "TwoOpt", "stop": {}})
    worse = evaluate(project, rev, note="a random walk")
    assert worse.verdict == "worse", bench.report(worse)
    # Revision 2, the random walk, as the baseline the incumbent is judged against.
    walk = project.snapshot()
    project.restore(rev)
    better = evaluate(project, walk)
    assert better.verdict == "better", bench.report(better)
    assert "verdict: BETTER" in bench.report(better)
    listed = bench.describe_bench(project)
    assert "1: the work files vs revision 1 on train: worse" in listed
    assert "- a random walk" in listed
    kept = bench.history(project)
    assert [r["verdict"] for r in kept] == ["worse", "better"]
    assert kept[1]["instances"][0]["sha256"] == bench.load_spec(project).instances[0].sha256


def test_the_budget_replaces_the_stop_of_either_side(home):
    project, rev = tsp_bench(home)
    # Ten times the iterations of its own: still the benchmark's 3000.
    with_heuristic(project, {**SA, "stop": {"max_iteration": 30000}})
    evaluation = evaluate(project, rev)
    assert evaluation.verdict == "same", bench.report(evaluation)
    runs = evaluation.instances[0].candidate
    assert {r.iterations for r in runs} == {3000}


def test_a_candidate_that_changes_the_objective_is_rejected(home):
    project = example_project("workload", home)
    rev = project.snapshot()
    instance = json.loads(project.read_file("instance.json"))
    bench.add_instance(project, "given", "train", "instance.json", instance)
    bench.configure(project, runs=2, max_duration_secs=None, max_iteration=2000)
    project.write_file(
        "model.py", project.read_file("model.py").replace("SPREAD = 1e-3", "SPREAD = 0")
    )
    evaluation = evaluate(project, rev, variant="SA", baseline_variant="SA")
    assert evaluation.verdict == "rejected"
    assert "changed the objective" in bench.report(evaluation)
    assert bench.history(project)[0]["gain"] is None


def test_a_solution_the_reference_cannot_decode_is_rejected(home):
    project = example_project("workload", home)
    rev = project.snapshot()
    bench.add_instance(
        project, "given", "train", "x", json.loads(project.read_file("instance.json"))
    )
    bench.configure(project, runs=1, max_duration_secs=None, max_iteration=100)
    model = project.read_file("model.py")
    project.write_file(
        "model.py",
        model.replace(
            'return {"assignment": list(assignment)', 'return {"tasks": list(assignment)'
        ),
    )
    evaluation = evaluate(project, rev, variant="SA", baseline_variant="SA")
    assert evaluation.verdict == "rejected"
    assert "cannot score the candidate's solutions" in evaluation.reference


def test_a_candidate_that_fails_is_reported_and_kept(home):
    project, rev = tsp_bench(home)
    project.write_file("model.py", "def build(instance):\n    raise ValueError('no')\n")
    evaluation = evaluate(project, rev)
    assert evaluation.verdict == "failed"
    assert "the work files fails on 'tsp0' at build" in bench.report(evaluation)
    assert bench.history(project)[0]["verdict"] == "failed"


def test_a_split_without_instances_cannot_be_evaluated(home):
    project, rev = tsp_bench(home, validation=0)
    with pytest.raises(ProjectError, match="no validation instances"):
        evaluate(project, rev, split="validation")


def test_several_variants_need_one_named(home):
    project = example_project("workload", home)
    rev = project.snapshot()
    bench.add_instance(
        project, "given", "train", "x", json.loads(project.read_file("instance.json"))
    )
    with pytest.raises(ProjectError, match="say which variant"):
        evaluate(project, rev)
    with pytest.raises(ProjectError, match="no variant 'GA'"):
        evaluate(project, rev, variant="GA", baseline_variant="SA")


def test_an_instance_changed_on_disk_is_refused(home):
    project, rev = tsp_bench(home)
    bench.instance_path(project, "tsp0").write_text('{"cities": []}')
    with pytest.raises(ProjectError, match="changed since it was added"):
        evaluate(project, rev)


def test_instances_are_replaced_by_name_and_removed(home):
    project, _ = tsp_bench(home)
    bench.add_instance(project, "tsp0", "validation", "again", {"cities": random_cities(9)})
    spec = bench.load_spec(project)
    assert [(i.name, i.split) for i in spec.instances][-1] == ("tsp0", "validation")
    assert len(spec.instances) == 3
    bench.remove_instance(project, "tsp0")
    assert not bench.instance_path(project, "tsp0").exists()
    with pytest.raises(ProjectError, match="no benchmark instance"):
        bench.remove_instance(project, "tsp0")
    with pytest.raises(ProjectError, match="JSON object"):
        bench.add_instance(project, "list", "train", "x", [1, 2])
    with pytest.raises(ProjectError, match="cannot add"):
        bench.add_instance(project, "../up", "train", "x", {})


def test_a_budget_is_required(home):
    project, _ = tsp_bench(home)
    with pytest.raises(ProjectError, match="give each run a budget"):
        bench.configure(project, max_duration_secs=None, max_iteration=None)
    with pytest.raises(ProjectError, match="not a benchmark setting"):
        bench.configure(project, runs=0)


def test_the_benchmark_travels_with_an_exported_project(home):
    project, rev = tsp_bench(home)
    evaluate(project, rev)
    copy = Project.import_archive(project.export(), home)
    assert bench.load_spec(copy) == bench.load_spec(project)
    assert bench.history(copy) == bench.history(project)
    assert bench.read_instance(copy, bench.load_spec(copy).instances[0])["cities"]


def test_the_state_says_which_change_was_solved_into_a_revision(home):
    project, rev = tsp_bench(home, validation=0)
    with_heuristic(project, {"kind": "RandomWalk", "neighbor": "TwoOpt", "stop": {}})
    evaluate(project, rev, note="a random walk")
    project.restore(rev)
    with_heuristic(project, {**SA, "cooling_rate": 0.998})
    evaluate(project, rev, note="cooler")
    kept = project.snapshot()
    state = bench.state(project)
    assert [(e.note, e.kept) for e in state.evaluations] == [
        ("a random walk", None),
        ("cooler", kept),
    ]
    walk = state.evaluations[0]
    assert walk.verdict == "worse"
    assert walk.candidate.where == "the work files"
    assert walk.baseline.rev == rev
    first = walk.instances[0]
    assert first.name == "tsp0"
    # A random walk ends where it is, far from the annealed tour.
    assert first.candidate > first.baseline
    assert first.gain < 0
    assert state.spec.max_iteration == 3000
    assert f"kept as revision {kept}" in bench.describe_bench(project)


def test_a_rejected_candidate_says_why_in_the_state(home):
    project = example_project("workload", home)
    rev = project.snapshot()
    instance = json.loads(project.read_file("instance.json"))
    bench.add_instance(project, "given", "train", "instance.json", instance)
    bench.configure(project, runs=1, max_duration_secs=None, max_iteration=500)
    project.write_file(
        "model.py", project.read_file("model.py").replace("SPREAD = 1e-3", "SPREAD = 0")
    )
    evaluate(project, rev, variant="SA", baseline_variant="SA")
    rejected = bench.state(project).evaluations[0]
    assert rejected.verdict == "rejected"
    assert rejected.gain is None
    assert "changed the objective" in (rejected.detail or "")
