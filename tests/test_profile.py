"""Profiling heuristics on the benchmark before composing them (profiling.py)."""

import asyncio
import json

import pytest

from optopus_studio import bench, profiling
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchSpec, RunFinished
from optopus_studio.tune import EARLY
from tests.test_bench import SA, tsp_bench
from tests.test_tune import WALK, with_variants

DESCENT = {"kind": "LocalSearch", "neighbor": "TwoOpt", "stop": {}}


def run(project, rev=None, **kwargs) -> profiling.Profile:
    return asyncio.run(profiling.profile(project, rev, **kwargs))


def test_a_profile_ranks_the_heuristics_and_reads_how_they_run(home):
    project, _ = tsp_bench(home, train=3, validation=1)
    broken = {**SA, "neighbor": "NoSuchMove"}
    rev = with_variants(project, ("SA", SA), ("RW", WALK), ("LS", DESCENT), ("bad", broken))
    profiled = run(project, rev)
    assert [p.label for p in profiled.alive] == ["SA", "RW", "LS"]
    assert "invalid neighbor 'NoSuchMove'" in profiled.profiled[3].error
    record = bench.profiles(project)[0]
    assert record["rev"] == rev
    assert record["split"] == "train"
    assert record["instances"] == ["tsp0", "tsp1", "tsp2"]
    by_label = {v["label"]: v for v in record["variants"]}
    # A random walk is the worst everywhere, clearly; the others are near the best at the end.
    assert by_label["RW"]["mean_rank"] == 3
    assert by_label["RW"]["p_vs_best"] < 0.05
    assert by_label["RW"]["wins"] == 0
    assert by_label["SA"]["wins"] + by_label["LS"]["wins"] == 3
    for label in ("SA", "RW", "LS"):
        anytime = by_label[label]["anytime"]
        assert len(anytime) == len(profiling.FRACTIONS)
        # The best so far only gets closer to the best found.
        assert anytime == sorted(anytime, reverse=True)
        assert anytime[-1] >= 0
    assert by_label["bad"]["error"] is not None
    # A descent stops at its local optimum, long before the budget ends.
    assert by_label["LS"]["best_found_at"] < EARLY
    assert by_label["SA"]["best_found_at"] > EARLY
    text = profiling.report(profiled)
    assert text.startswith(f"profile 1: 4 heuristics of revision {rev}")
    assert text.index("  SA: ") < text.index("  RW: ") or text.index("  LS: ") < text.index(
        "  RW: "
    )
    assert "  bad failed: " in text
    assert profiling.describe(project)[0].startswith(f"  1: revision {rev} on train")
    (state,) = bench.state(project).profiles
    assert [v.label for v in state.variants] == ["SA", "RW", "LS", "bad"]
    assert state.fractions == list(profiling.FRACTIONS)


def test_a_profile_runs_on_the_work_files_and_some_variants(home):
    project, _ = tsp_bench(home)
    with_variants(project, ("SA", SA), ("RW", WALK), ("LS", DESCENT))
    profiled = run(project, variants=["LS", "SA"], split="all")
    assert profiled.where == "the work files"
    assert [p.label for p in profiled.profiled] == ["LS", "SA"]
    assert profiled.instances == ["tsp0", "tsp1", "tsp2"]


def test_a_profile_needs_two_heuristics_and_the_split(home):
    project, rev = tsp_bench(home, validation=0)
    with pytest.raises(ProjectError, match="has one heuristic"):
        run(project, rev)
    with_variants(project, ("SA", SA), ("RW", WALK))
    with pytest.raises(ProjectError, match="no variant 'XX'"):
        run(project, variants=["SA", "XX"])
    with pytest.raises(ProjectError, match="no validation instances"):
        run(project, split="validation")


def test_a_profile_travels_with_an_exported_project(home):
    project, _ = tsp_bench(home)
    rev = with_variants(project, ("SA", SA), ("RW", WALK))
    run(project, rev)
    copy = Project.import_archive(project.export(), home)
    assert bench.profiles(copy) == bench.profiles(project)


# --- readings, on profiles made by hand ----------------------------------------------------------


def finished(best: float, trajectory, best_iteration: int = 900) -> RunFinished:
    return RunFinished(
        run=0,
        variant=0,
        seed=0,
        best_objective=best,
        initial_objective=100.0,
        solution=None,
        trajectory=trajectory,
        iterations=1000,
        best_iteration=best_iteration,
        time_to_best_secs=0.5,
        total_time_secs=1.0,
        n_accepted=300,
        n_rejected=700,
    )


def made(heuristics: dict[str, dict[str, RunFinished]], runs: int = 3) -> profiling.Profile:
    """A finished profile on an iteration budget of 1000: each heuristic's run on each instance,
    repeated ``runs`` times."""
    instances = list(next(iter(heuristics.values())))
    profile = profiling.Profile(
        id=1,
        rev=1,
        split="train",
        spec=BenchSpec(runs=runs, max_duration_secs=None, max_iteration=1000),
        worker="python",
        where="revision 1",
        instances=instances,
        profiled=[
            profiling.Profiled(label, {i: [r] * runs for i, r in by_instance.items()})
            for label, by_instance in heuristics.items()
        ],
    )
    profile.readings = profiling.readings(profile)
    return profile


# Reaches 20 by iteration 50, then 12; and 15 only at iteration 600, then 10.
FAST = finished(12.0, [(0.0, 50, 20.0), (0.0, 900, 12.0)])
SLOW = finished(10.0, [(0.0, 600, 15.0), (0.0, 950, 10.0)], best_iteration=950)


def test_one_that_leads_early_and_one_that_ends_best_make_a_sequential():
    profile = made({"fast": {"a": FAST, "b": FAST}, "slow": {"a": SLOW, "b": SLOW}})
    assert profile.best_so_far(FAST, 0.1) == 20.0
    assert profile.best_so_far(SLOW, 0.1) == 100.0
    assert profile.anytime(profile.profiled[1]) == pytest.approx([9.0, 9.0, 9.0, 0.0])
    (reading,) = profile.readings
    assert reading.startswith(
        "fast leads at 10% of the budget (gap 100% vs 900%, ahead by 0.1% or more on 2 of 2"
    )
    assert "try Sequential [fast, slow]" in reading


def test_a_lead_within_the_noise_is_no_lead():
    almost = finished(10.005, [(0.0, 50, 10.005)])
    profile = made({"almost": {"a": almost, "b": almost}, "slow": {"a": SLOW, "b": SLOW}})
    # 0.05% ahead at 10%, then behind at the end.
    profile.profiled[1].runs = {
        i: [finished(10.0, [(0.0, 50, 10.01), (0.0, 950, 10.0)])] * 3 for i in "ab"
    }
    profile.readings = profiling.readings(profile)
    assert not any("leads at" in r for r in profile.readings)


def test_the_best_so_far_is_read_by_time_on_a_time_budget():
    profile = made({"fast": {"a": FAST}, "slow": {"a": SLOW}})
    profile.spec = BenchSpec(runs=3, max_duration_secs=2.0)
    timed = finished(10.0, [(0.1, 1, 30.0), (1.5, 2, 10.0)])
    assert profile.best_so_far(timed, 0.25) == 30.0
    assert profile.best_so_far(timed, 1.0) == 10.0


def test_one_that_stalls_wants_a_perturbation():
    stalled = finished(10.0, [(0.0, 100, 10.0)], best_iteration=100)
    profile = made({"stalled": {"a": stalled, "b": stalled}, "slow": {"a": SLOW, "b": SLOW}})
    # Equal at the end, so neither is clearly worse; only the stalled one stalls.
    assert [r.split(":")[0] for r in profile.readings if "stalls" in r] == [
        "stalled finds its best 10% into the budget on average and stalls or stops after"
    ]


def test_instances_that_prefer_different_heuristics_are_read():
    better_on_b = finished(10.0, [(0.0, 950, 10.0)])
    worse_on_b = finished(10.5, [(0.0, 950, 10.5)])
    profile = made({"x": {"a": SLOW, "b": worse_on_b}, "y": {"a": FAST, "b": better_on_b}})
    assert any(
        r.startswith("instances prefer different heuristics (a x, b y)") for r in profile.readings
    )
    # Within the evaluation's 1% they tell nothing.
    close = finished(10.05, [(0.0, 950, 10.05)])
    profile = made({"x": {"a": SLOW, "b": close}, "y": {"a": FAST, "b": better_on_b}})
    assert not any(r.startswith("instances") for r in profile.readings)


def test_heuristics_that_cannot_be_told_apart_point_elsewhere():
    profile = made({"x": {"a": SLOW}, "y": {"a": SLOW}})
    (reading,) = profile.readings
    assert reading.startswith("the heuristics cannot be told apart (Friedman p = 1)")


def test_a_profile_record_is_json():
    profile = made({"fast": {"a": FAST}, "slow": {"a": SLOW}})
    record = json.loads(json.dumps(profile.to_json()))
    assert [v["wins"] for v in record["variants"]] == [0, 1]
    assert record["variants"][1]["objectives"] == {"a": [10.0, 10.0, 10.0]}
