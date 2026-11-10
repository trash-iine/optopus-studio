"""Saving candidates, racing them and adopting the winner (candidates.py)."""

import asyncio
import json

import pytest

from optopus_studio import bench, candidates
from optopus_studio.agent import Tools
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchProgress
from tests.conftest import example_project
from tests.test_agent_tools import Recorder, call, text
from tests.test_bench import SA, random_cities, tsp_bench, with_heuristic

WALK = {"kind": "RandomWalk", "neighbor": "TwoOpt", "stop": {}}


def walking(home) -> tuple[Project, int]:
    """The TSP benchmark whose incumbent, revision 2, is a random walk."""
    project, _ = tsp_bench(home)
    with_heuristic(project, WALK)
    return project, project.snapshot()


def save(project, rev, heuristic, family="heuristic", hypothesis="another search") -> dict:
    with_heuristic(project, heuristic)
    return asyncio.run(candidates.save(project, rev, hypothesis, family))


def test_a_saved_candidate_leaves_the_incumbents_files(home):
    project, rev = walking(home)
    record = save(project, rev, SA, hypothesis="annealing escapes what a walk cannot")
    assert (record["id"], record["family"], record["variant"]) == (
        1,
        "heuristic",
        "SimulatedAnnealing",
    )
    assert json.loads(project.read_file("solve.json"))["heuristic"] == WALK
    kept = candidates.files_dir(project, 1)
    assert json.loads((kept / "solve.json").read_text())["heuristic"] == SA
    assert project.revisions() == [1, rev]


def test_a_candidate_saved_before_or_changing_nothing_is_refused(home):
    project, rev = walking(home)
    with pytest.raises(ProjectError, match="there is no change to save"):
        asyncio.run(candidates.save(project, rev, "nothing", "settings"))
    save(project, rev, SA)
    with pytest.raises(ProjectError, match="candidate 1 already"):
        save(project, rev, SA)
    with pytest.raises(ProjectError, match="unknown family"):
        save(project, rev, {**SA, "cooling_rate": 0.99}, family="magic")
    # A refused candidate leaves nothing behind, and the files as they were written.
    assert [r["id"] for r in bench.candidate_records(project)] == [1]
    assert not candidates.files_dir(project, 2).exists()
    assert json.loads(project.read_file("solve.json"))["heuristic"]["cooling_rate"] == 0.99


def test_a_candidate_that_changes_the_objective_is_refused_before_it_runs(home):
    project = example_project("workload", home)
    tools = Tools(project, Recorder())
    assert not call(tools.run_solver, max_duration_secs=0.2)["is_error"]
    model = project.read_file("model.py")
    project.write_file("model.py", model.replace("SPREAD = 1e-3", "SPREAD = 0"))
    with pytest.raises(ProjectError, match="changes the objective"):
        call(
            tools.candidate_save,
            baseline_rev=1,
            hypothesis="no spread",
            family="delta",
            variant="SA",
        )
    assert bench.candidate_records(project) == []


def test_a_race_pairs_every_candidate_with_one_run_of_the_baseline(home):
    project, rev = walking(home)
    save(project, rev, SA, hypothesis="annealing")
    save(project, rev, {**WALK, "stop": {"max_iteration": 7}}, "settings", "a walk again")
    seen = []

    async def progress(event: BenchProgress) -> None:
        seen.append((event.task, event.done, event.total))

    record, evaluations = asyncio.run(candidates.race(project, [1, 2], progress=progress))
    # Two train instances, each solved by the baseline and the two candidates.
    assert seen[-1] == ("race", 6, 6)
    assert [e.verdict for e in evaluations] == ["better", "same"]
    assert record["winner"] == 1
    ranks = {e["candidate"]: e["mean_rank"] for e in record["entries"]}
    assert ranks[1] == 1.0
    assert ranks[2] == record["baseline_rank"] == 2.5
    report = candidates.report(project, record, evaluations)
    assert "candidate 1 [heuristic] annealing" in report
    assert "winner: candidate 1" in report
    # Each candidate has the evaluation evaluate would have made of it.
    kept = bench.history(project)
    assert [(r["candidate"]["where"], r["verdict"]) for r in kept] == [
        ("candidate 1", "better"),
        ("candidate 2", "same"),
    ]
    assert kept[0]["candidate"]["note"] == "[heuristic] annealing"
    state = bench.state(project)
    assert [(c.id, c.verdict) for c in state.candidates] == [(1, "better"), (2, "same")]
    assert state.races[0].winner == 1
    assert {b.name for b in state.best} == {"tsp0", "tsp1"}
    assert all(b.source == "evaluation 1" for b in state.best)


def test_a_candidate_that_fails_does_not_stop_the_race(home):
    project, rev = walking(home)
    save(project, rev, SA)
    save(project, rev, {**SA, "neighbor": "NoSuchMove"}, hypothesis="a move there is not")
    record, evaluations = asyncio.run(candidates.race(project, [1, 2]))
    assert [e.verdict for e in evaluations] == ["better", "failed"]
    assert record["winner"] == 1
    assert record["entries"][1]["mean_rank"] is None


def test_candidates_of_different_revisions_are_not_raced_together(home):
    project, rev = walking(home)
    save(project, rev, SA)
    save(project, 1, WALK)
    with pytest.raises(ProjectError, match="different revisions"):
        asyncio.run(candidates.race(project, [1, 2]))
    with pytest.raises(ProjectError, match="no candidate 9"):
        asyncio.run(candidates.race(project, [9]))


def test_only_a_better_candidate_is_adopted_and_becomes_the_incumbent(home):
    project, rev = walking(home)
    tools = Tools(project, Recorder())
    with_heuristic(project, SA)
    saved = call(tools.candidate_save, baseline_rev=rev, hypothesis="annealing", family="heuristic")
    assert "candidate 1 [heuristic] saved" in text(saved)
    with_heuristic(project, {**WALK, "stop": {"max_iteration": 7}})
    call(tools.candidate_save, baseline_rev=rev, hypothesis="a walk again", family="settings")
    raced = call(tools.race, candidates=[1, 2])
    assert "winner: candidate 1" in text(raced)

    with pytest.raises(ProjectError, match="judged SAME"):
        call(tools.adopt, candidate=2, lesson="the budget replaces the stop")
    assert json.loads(project.read_file("solve.json"))["heuristic"] == WALK
    adopted = call(tools.adopt, candidate=1, lesson="a walk never settles")
    assert not adopted["is_error"], text(adopted)
    assert "revision 3 is the incumbent now" in text(adopted)
    assert project.revisions() == [1, rev, 3]
    assert json.loads((project.rev_dir(3) / "solve.json").read_text())["heuristic"] == SA

    call(tools.candidate_lesson, lessons=[{"candidate": 2, "lesson": "nothing changed"}])
    listed = text(call(tools.bench_list))
    assert "1 [heuristic] on revision 2: adopted as revision 3 (gain +" in listed
    assert "| lesson: a walk never settles" in listed
    assert (
        "2 [settings] on revision 2: same (gain +0.000%) - a walk again | lesson: nothing changed"
        in listed
    )
    assert "families tried: settings 1, heuristic 1 (1 adopted); not yet: composition" in listed
    assert "kept as revision 3" in listed
    # The incumbent moved, so what was judged against the old one is not adopted any more.
    with pytest.raises(ProjectError, match="which is the incumbent now"):
        call(tools.adopt, candidate=2)


def test_adopting_a_candidate_not_raced_yet_races_it_first(home):
    project, rev = walking(home)
    tools = Tools(project, Recorder())
    save(project, rev, {**WALK, "stop": {"max_iteration": 7}}, "settings", "a walk again")
    refused = call(tools.adopt, candidate=1)
    assert refused["is_error"]
    assert "candidate 1 is not adopted" in text(refused)
    assert project.revisions() == [1, rev]
    save(project, rev, SA)
    assert "revision 3 is the incumbent now" in text(call(tools.adopt, candidate=2))


def test_a_candidate_of_several_variants_is_adopted_as_the_one_it_ran(home):
    project, rev = walking(home)
    heuristics = [{"label": "walk", "heuristic": WALK}, {"label": "anneal", "heuristic": SA}]
    project.write_file("solve.json", json.dumps({"heuristics": heuristics, "runs": 1, "seed": 0}))
    with pytest.raises(ProjectError, match="say which variant"):
        asyncio.run(candidates.save(project, rev, "annealing", "heuristic"))
    asyncio.run(candidates.save(project, rev, "annealing", "heuristic", variant="anneal"))
    tools = Tools(project, Recorder())
    assert "revision 3 is the incumbent now" in text(call(tools.adopt, candidate=1))
    assert json.loads(project.read_file("solve.json")) == {"heuristic": SA, "runs": 1, "seed": 0}


def test_the_test_split_is_measured_but_never_chosen_on(home):
    project, rev = tsp_bench(home)
    bench.add_instance(project, "held", "test", "seed 9", {"cities": random_cities(9)})
    spec = bench.load_spec(project)
    assert [i.name for i in bench.instances_of(spec, "all")] == ["tsp0", "tsp1", "tsp2"]
    assert [i.name for i in bench.instances_of(spec, "test")] == ["held"]
    assert "test: held (seed 9)" in bench.describe_bench(project)
    tools = Tools(project, Recorder())
    for tool in (tools.evaluate, tools.profile):
        with pytest.raises(ProjectError, match="nothing is chosen on them"):
            call(tool, baseline_rev=rev, split="test")
    measured = asyncio.run(bench.evaluate(project, rev, "test"))
    assert measured.verdict == "same"
    assert [i.name for i in measured.instances] == ["held"]


def test_the_best_known_follows_the_instance_it_was_found_on(home):
    project, rev = tsp_bench(home)
    asyncio.run(bench.evaluate(project, rev))
    known = bench.best_known(project)
    assert set(known) == {"tsp0", "tsp1"}
    first = known["tsp0"]
    assert sorted(first["solution"]) == list(range(40))
    assert first["source"] == "evaluation 1"
    # A worse search does not replace it; an instance replaced under the same name drops it.
    with_heuristic(project, WALK)
    asyncio.run(bench.evaluate(project, rev))
    assert bench.best_known(project)["tsp0"] == first
    bench.add_instance(project, "tsp0", "train", "seed 7", {"cities": random_cities(7)})
    assert set(bench.best_known(project)) == {"tsp1"}


def test_candidates_and_their_races_travel_with_an_exported_project(home):
    project, rev = walking(home)
    save(project, rev, SA, hypothesis="annealing")
    asyncio.run(candidates.race(project, [1]))
    copy = Project.import_archive(project.export(), home)
    assert [(c.id, c.verdict) for c in bench.state(copy).candidates] == [(1, "better")]
    assert bench.state(copy).races[0].winner == 1
    assert set(bench.best_known(copy)) == {"tsp0", "tsp1"}
    assert (candidates.files_dir(copy, 1) / "model.py").is_file()
