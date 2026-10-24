"""Tuning a heuristic's settings by racing (tune.py)."""

import asyncio
import json
import random

import pytest

from optopus_studio import bench, tune
from optopus_studio.projects import Project, ProjectError
from tests.test_bench import SA, tsp_bench

TEMPERATURE = [{"name": "initial_temperature", "low": 0.1, "high": 1e5, "log": True}]


def run(project, rev, space, budget, **kwargs):
    return asyncio.run(tune.tune_and_check(project, rev, space, budget, **kwargs))


def test_the_distributions_match_known_values():
    # scipy.stats.chi2.sf and scipy.stats.t.sf.
    assert tune.chi2_sf(3.0, 1) == pytest.approx(0.08326451666355052)
    assert tune.chi2_sf(7.5, 4) == pytest.approx(0.11170929281604328)
    assert tune.chi2_sf(20.0, 7) == pytest.approx(0.0055696830729455755)
    assert tune.t_sf(1.5, 1) == pytest.approx(0.18716704181099886)
    assert tune.t_sf(2.5, 10) == pytest.approx(0.01572342211830441)
    assert tune.t_sf(-1.0, 7) == pytest.approx(0.8246916685898963)
    assert tune.t_sf(2.0, 693) == pytest.approx(0.022945037359970243)


def test_the_friedman_test_drops_what_is_worse_on_every_task():
    rng = random.Random(0)
    # Column 2 is the best on every task and column 0 the worst; 1 and 3 tie with each other.
    blocks = [[3 + rng.random() * 0.1, 2.0, 1.0, 2.0] for _ in range(8)]
    p, sums, compared = tune.friedman(blocks)
    assert p < 0.001
    assert sums == [32.0, 20.0, 8.0, 20.0]
    assert compared[2] == 1.0
    assert compared[0] < tune.ALPHA
    assert tune.ranks([2.0, 1.0, 2.0]) == [2.5, 1.0, 2.5]
    # Ties everywhere: no evidence.
    assert tune.friedman([[1.0, 1.0]] * 6)[0] == 1.0


def test_values_stay_in_their_space():
    rng = random.Random(1)
    number = tune.Parameter(name="tenure", type="int", low=5, high=9)
    assert {number.at(i / 50) for i in range(50)} == {5, 6, 7, 8, 9}
    assert all(5 <= number.near(9, 0.5, rng) <= 9 for _ in range(200))
    scaled = tune.Parameter(name="t", low=0.01, high=100, log=True)
    # Even over the orders of magnitude: half the space lies below 1.
    assert scaled.at(0.5) == pytest.approx(1.0)
    assert all(0.01 <= scaled.near(50.0, 0.3, rng) <= 100 for _ in range(200))
    choice = tune.Parameter(name="neighbor", choices=["TwoOpt", "Swap"])
    assert choice.type == "categorical"
    assert choice.near("Swap", 0.0, rng) == "Swap"


@pytest.mark.parametrize(
    ("space", "message"),
    [
        ([], "list of parameters"),
        ([{"name": "stop.max_iteration", "low": 1, "high": 2}], "the stop is the benchmark's"),
        ([{"name": "cooling_rate", "low": 1, "high": 1}], "low < high"),
        ([{"name": "cooling_rate", "low": 0, "high": 1, "log": True}], "log scale"),
        ([{"name": "tenure", "type": "int", "low": 1.5, "high": 4}], "must be whole"),
        ([{"name": "neighbor", "choices": ["TwoOpt"]}], "two or more choices"),
        ([{"name": "search.cooling_rate", "low": 0.9, "high": 1}], "nothing at 'search'"),
        ([{"name": "cooling_rate", "low": 0.9, "high": 1}] * 2, "named twice"),
    ],
)
def test_a_space_is_checked_against_the_heuristic(space, message):
    with pytest.raises(ProjectError, match=message):
        tune.parse_space(space, SA)


def test_paths_reach_into_nested_heuristics():
    iterated = {"kind": "Iterated", "search": dict(SA), "steps": [{"tenure": [3, 5]}]}
    assert tune._get(iterated, "search.cooling_rate") == 0.999
    assert tune._get(iterated, "search.absent") is None
    changed = tune.with_values(
        iterated, {"search.cooling_rate": 0.99, "steps.0.tenure.1": 8, "search.absent": None}
    )
    assert changed["search"]["cooling_rate"] == 0.99
    assert changed["steps"][0]["tenure"] == [3, 8]
    assert "absent" not in changed["search"]
    assert iterated["search"]["cooling_rate"] == 0.999


def test_a_race_drops_bad_temperatures_and_checks_the_best_on_validation(home):
    project, rev = tsp_bench(home, train=3, validation=2)
    tuning, evaluation = run(project, rev, TEMPERATURE, 80)
    assert tuning.used <= 80
    hot = [s for s in tuning.settings if s.values["initial_temperature"] > 1000]
    # A random walk wastes the budget: dropped after the first test.
    assert hot
    assert all(s.eliminated == (1, tune.FIRST_TEST) for s in hot)
    assert all(s.values["initial_temperature"] < 50 for s in tuning.elites)
    assert tuning.written
    heuristic = json.loads(project.read_file("solve.json"))["heuristic"]
    assert heuristic["initial_temperature"] == tuning.best.values["initial_temperature"]
    assert heuristic["stop"] == SA["stop"]
    assert evaluation is not None
    assert evaluation.split == "validation"
    assert tuning.validation == evaluation.id
    text = tune.report(tuning, evaluation)
    assert f"#{tuning.best.id}: initial_temperature=" in text
    assert "on validation" in text
    record = bench.tunings(project)[0]
    assert record["best"] == tuning.best.id
    assert record["validation"] == evaluation.id
    assert "best #" in tune.describe(project)[0]
    assert f"#{tuning.best.id}'s runs: " in text
    assert record["signs"] == tuning.signs
    assert set(record["settings"][1]["stats"]) == set(record["settings"][1]["results"])
    assert bench.history(project)[0]["candidate"]["note"].startswith("tuning 1: ")


def test_a_check_on_validation_that_fails_says_the_files_changed(home, monkeypatch):
    project, rev = tsp_bench(home, train=3, validation=1)

    async def broken(*args, **kwargs):
        raise ProjectError("revision 1 fails on 'tsp3' at build: boom")

    monkeypatch.setattr(bench, "evaluate", broken)
    with pytest.raises(ProjectError, match="now revision 1's with the tuned settings"):
        run(project, rev, TEMPERATURE, 80)
    (record,) = bench.tunings(project)
    assert record["written"]
    assert record["validation"] is None


def test_the_revisions_settings_stay_when_nothing_beats_them(home):
    project, rev = tsp_bench(home)
    before = project.read_file("solve.json")
    hot = [{"name": "initial_temperature", "low": 1e4, "high": 1e6, "log": True}]
    tuning, evaluation = run(project, rev, hot, 60)
    assert tuning.best is tuning.default
    assert evaluation is None
    assert not tuning.written
    assert project.read_file("solve.json") == before
    assert "stay the best; solve.json is unchanged" in tune.report(tuning, evaluation)
    assert "kept the revision's settings" in tune.describe(project)[0]


def test_settings_that_fail_are_dropped_and_reported(home):
    project, rev = tsp_bench(home, validation=0)
    space = [{"name": "neighbor", "choices": ["TwoOpt", "NoSuchMove"]}]
    tuning, evaluation = run(project, rev, space, 40)
    failed = [s for s in tuning.settings if s.error]
    assert [s.values["neighbor"] for s in failed] == ["NoSuchMove"]
    assert "invalid neighbor 'NoSuchMove'" in failed[0].error
    assert tuning.best.values["neighbor"] == "TwoOpt"
    assert "failed: #" in tune.report(tuning, evaluation)


def test_a_variant_is_tuned_among_several(home):
    project, _ = tsp_bench(home, validation=0)
    walk = {"kind": "RandomWalk", "neighbor": "TwoOpt", "stop": {}}
    project.write_file(
        "solve.json",
        json.dumps(
            {
                "heuristics": [
                    {"label": "SA", "heuristic": SA},
                    {"label": "RW", "heuristic": walk},
                ],
                "runs": 1,
                "seed": 0,
            }
        ),
    )
    rev = project.snapshot()
    with pytest.raises(ProjectError, match="say which variant"):
        run(project, rev, TEMPERATURE, 40)
    tuning, evaluation = run(project, rev, TEMPERATURE, 80, variant="SA")
    assert evaluation is None
    assert tuning.written
    variants = json.loads(project.read_file("solve.json"))["heuristics"]
    assert variants[1] == {"label": "RW", "heuristic": walk}
    assert variants[0]["heuristic"]["initial_temperature"] != SA["initial_temperature"]
    assert "no validation instances" in tune.report(tuning, evaluation)


WALK = {"kind": "RandomWalk", "neighbor": "TwoOpt", "stop": {}}


def with_variants(project, *variants) -> int:
    heuristics = [{"label": label, "heuristic": h} for label, h in variants]
    project.write_file("solve.json", json.dumps({"heuristics": heuristics, "runs": 1, "seed": 0}))
    return project.snapshot()


def test_a_race_chooses_among_variants_and_solves_with_the_winner(home):
    project, _ = tsp_bench(home, train=3, validation=2)
    rev = with_variants(project, ("RW", WALK), ("SA", SA))
    space = {
        "RW": [],
        "SA": [*TEMPERATURE, {"name": "cooling_rate", "low": 0.9, "high": 0.9999}],
    }
    tuning, evaluation = run(project, rev, space, 150)
    assert tuning.choosing
    assert tuning.default.variant == "RW"
    assert {s.variant for s in tuning.settings if s.iteration == 1} == {"RW", "SA"}
    assert tuning.best.variant == "SA"
    solve = json.loads(project.read_file("solve.json"))
    assert "heuristics" not in solve
    assert solve["heuristic"] == tuning.heuristic(tuning.best)
    assert solve["heuristic"]["stop"] == SA["stop"]
    assert evaluation is not None
    assert evaluation.verdict == "better"
    assert evaluation.baseline["variant"] == "RW"
    assert evaluation.candidate["variant"] == "SimulatedAnnealing"
    text = tune.report(tuning, evaluation)
    assert "variants RW, SA of revision" in text
    assert "(#0: RW: its own settings) were eliminated" in text
    assert f"#{tuning.best.id} (SA) as solve.json's only heuristic" in text
    record = bench.tunings(project)[0]
    assert record["variants"] == ["RW", "SA"]
    assert record["settings"][0]["variant"] == "RW"
    assert "RW or SA of revision" in tune.describe(project)[0]
    (state,) = bench.state(project).tunings
    assert state.variants == ["RW", "SA"]
    assert state.best_variant == "SA"


def test_a_space_by_variant_is_checked(home):
    project, _ = tsp_bench(home, validation=0)
    rev = with_variants(project, ("RW", WALK), ("SA", SA))
    with pytest.raises(ProjectError, match="leave variant out"):
        run(project, rev, {"SA": TEMPERATURE}, 80, variant="SA")
    with pytest.raises(ProjectError, match=r"no variant 'TS'; it has \['RW', 'SA'\]"):
        run(project, rev, {"SA": TEMPERATURE, "TS": []}, 80)
    with pytest.raises(ProjectError, match="nothing to tune"):
        run(project, rev, {"SA": []}, 80)
    nested = [{"name": "search.tabu_tenure", "low": 1, "high": 9}]
    with pytest.raises(ProjectError, match=r"variant 'RW': .*nothing at 'search'"):
        run(project, rev, {"SA": TEMPERATURE, "RW": nested}, 80)
    # One variant by label is the same as naming it.
    tuning, _ = run(project, rev, {"SA": TEMPERATURE}, 80)
    assert not tuning.choosing
    assert json.loads(project.read_file("solve.json"))["heuristics"][0]["label"] == "RW"


def raced(settings, instances=1):
    """A finished tuning of SA's initial temperature, made by hand: each setting is (its
    temperature, its objective on each task, what its runs did), the first the best."""
    tuning = tune.Tuning(
        id=1,
        rev=1,
        spec=None,
        side=None,
        space={"SA": tune.parse_space(TEMPERATURE, SA)},
        variants={},
        budget=100,
        seed=0,
        instances=[
            (bench.BenchInstance(name=f"i{k}", split="train", source="test", sha256="0"), {})
            for k in range(instances)
        ],
    )
    for i, (temperature, results, stats) in enumerate(settings):
        s = tune.Setting(i, "SA", {"initial_temperature": temperature}, 1)
        s.results = dict(enumerate(results))
        s.stats = dict.fromkeys(s.results, stats)
        tuning.settings.append(s)
    tuning.elites = list(tuning.settings)
    tasks = len(settings[0][1])
    tuning.iterations = [{"iteration": 1, "raced": list(range(len(settings))), "tasks": tasks}]
    return tuning


CALM = (30, 70, 900, 1000, 0.01)


def test_a_race_that_shows_nothing_has_no_signs():
    assert tune.signs(raced([(20.0, [10] * 6, CALM), (5.0, [11] * 6, CALM)])) == []


def test_signs_read_what_the_settings_cannot_fix():
    (edge,) = tune.signs(raced([(0.11, [10] * 6, CALM), (0.12, [11] * 6, CALM)]))
    assert edge.startswith("initial_temperature: every elite is at the low end of [0.1, 100000]")

    (flat,) = tune.signs(raced([(20.0, [10] * 6, CALM), (5.0, [10] * 6, CALM)]))
    assert flat.startswith("the settings barely matter: 0 of 2 dropped")

    split = raced(
        [(20.0, [10, 20] * 3, CALM), (5.0, [11, 18] * 3, CALM)],
        instances=2,
    )
    assert any(
        s.startswith("instances prefer different elites: i0 #0, i1 #1") for s in tune.signs(split)
    )
    # A margin within the noise tells nothing.
    close = raced([(20.0, [10, 20] * 3, CALM), (5.0, [11, 19.9] * 3, CALM)], instances=2)
    assert not any(s.startswith("instances") for s in tune.signs(close))

    stalled = tune.signs(
        raced([(20.0, [10] * 6, (0, 1000, 100, 1000, 0.01)), (5.0, [11] * 6, CALM)])
    )
    assert [s.split(";")[0] for s in stalled] == [
        "#0 finds its best 10% of the way through a run on average",
        "#0 accepts 0.0% of its moves: almost none, the search barely moves",
    ]
    # A heuristic that does not count its moves shows no rate.
    uncounted = raced([(20.0, [10] * 6, (None, None, 900, 1000, 0.01)), (5.0, [11] * 6, CALM)])
    assert tune.signs(uncounted) == []


def test_a_budget_too_small_or_no_train_split_is_refused(home):
    project, rev = tsp_bench(home)
    with pytest.raises(ProjectError, match="too small"):
        run(project, rev, TEMPERATURE, 10)
    for entry in bench.load_spec(project).instances:
        if entry.split == "train":
            bench.remove_instance(project, entry.name)
    with pytest.raises(ProjectError, match="no train instances"):
        run(project, rev, TEMPERATURE, 100)


def test_a_tuning_travels_with_an_exported_project(home):
    project, rev = tsp_bench(home)
    run(project, rev, TEMPERATURE, 40)
    copy = Project.import_archive(project.export(), home)
    assert bench.tunings(copy) == bench.tunings(project)
