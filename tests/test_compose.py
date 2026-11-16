"""Compositions built from a grammar of leaves, and raced with them (compose.py)."""

import json

import pytest

from optopus_studio import bench, compose, tune, worker
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchSpec, Variant
from tests.test_bench import SA, tsp_bench
from tests.test_candidates import WALK
from tests.test_recipes import problem  # noqa: F401
from tests.test_tune import run, with_variants

DESCENT = {"kind": "LocalSearch", "neighbor": "Move", "stop": {"max_iteration": 100}}
TABU = {"kind": "TabuSearch", "neighbor": "Move", "tabu_tenure": [2, 4], "stop": {}}
LEAVES = [Variant(label="LS", heuristic=DESCENT), Variant(label="Tabu", heuristic=TABU)]
TENURE = [{"name": "tabu_tenure.1", "type": "int", "low": 3, "high": 9}]
ITERATIONS = BenchSpec(max_duration_secs=None, max_iteration=2000)


def expand(home, grammar, spec=ITERATIONS, leaves=LEAVES):
    return compose.expand(Project.create(home), 1, leaves, grammar, spec)


def test_a_grammar_builds_every_composition_of_its_leaves(home):
    space, composed, note = expand(home, {"leaves": {"LS": [], "Tabu": TENURE}})
    labels = [v.label for v in composed]
    # One of each template in turn, the leaves in the order given.
    assert labels == [
        "Seq[LS>Tabu]",
        "Iter[LS]",
        "Restart[LS]",
        "VNS[LS]",
        "Seq[Tabu>LS]",
        "Iter[Tabu]",
        "Restart[Tabu]",
        "VNS[Tabu]",
    ]
    assert list(space) == ["LS", "Tabu", *labels]
    assert note.startswith("grammar: 2 leaves and 8 of 8 compositions, in the order of the leaves")
    by_label = {v.label: v.heuristic for v in composed}
    # A step runs a tenth of the budget, and a race may give it a hundredth to a half.
    sequential = by_label["Seq[LS>Tabu]"]
    assert [s["stop"] for s in sequential["steps"]] == [{"max_iteration": 200}] * 2
    assert space["Seq[LS>Tabu]"] == [
        {"name": "steps.0.stop.max_iteration", "type": "int", "low": 20, "high": 1000, "log": True},
        {"name": "steps.1.stop.max_iteration", "type": "int", "low": 20, "high": 1000, "log": True},
        {"name": "steps.1.tabu_tenure.1", "type": "int", "low": 3, "high": 9},
    ]
    assert by_label["Iter[Tabu]"]["perturbation"] == {
        "kind": "RandomWalk",
        "neighbor": "Move",
        "stop": {"max_iteration": 5},
    }
    assert [p["name"] for p in space["Iter[Tabu]"]] == [
        "search.stop.max_iteration",
        "perturbation.stop.max_iteration",
        "search.tabu_tenure.1",
    ]
    assert by_label["Restart[Tabu]"]["heuristic"]["stop"] == {"max_failed_update": 2000}
    assert [s["stop"]["max_iteration"] for s in by_label["VNS[LS]"]["shakes"]] == [2, 4, 8]
    # Every parameter is one the composition has, as tune checks a space.
    for label, parameters in space.items():
        if label in by_label:
            tune.parse_space(parameters, by_label[label], empty=True)


def test_a_time_budget_gives_the_steps_seconds_and_kicks_choose_their_neighborhood(home):
    grammar = {"leaves": {"Tabu": []}, "templates": ["iterated"], "kicks": ["Move", "Swap"]}
    space, composed, _ = expand(home, grammar, BenchSpec(max_duration_secs=2.0))
    assert composed[0].heuristic["search"]["stop"] == {"max_duration_secs": 0.2}
    assert space["Iter[Tabu]"] == [
        {
            "name": "search.stop.max_duration_secs",
            "type": "float",
            "low": 0.02,
            "high": 1.0,
            "log": True,
        },
        {
            "name": "perturbation.stop.max_iteration",
            "type": "int",
            "low": 1,
            "high": 50,
            "log": True,
        },
        {"name": "perturbation.neighbor", "choices": ["Move", "Swap"]},
    ]


@pytest.mark.parametrize("template", compose.TEMPLATES)
def test_every_template_builds_and_runs(template, home, problem):  # noqa: F811
    grammar = {"leaves": {"LS": [], "Tabu": TENURE}, "templates": [template], "kicks": ["Swap"]}
    _, composed, _ = expand(home, grammar)
    assert composed
    for variant in composed:
        heuristic = worker.build_heuristic({**variant.heuristic, "stop": {"max_iteration": 2000}})
        result = heuristic.run(problem, 1, 0).runs[0]
        # The optimum puts 11 in each bin.
        assert 11 <= result.best_objective <= 33, variant.label


def test_a_grammar_is_checked(home):
    with pytest.raises(ProjectError, match="give the grammar as"):
        expand(home, {"LS": []})
    with pytest.raises(ProjectError, match=r"no variants \['SA'\]; it has \['LS', 'Tabu'\]"):
        expand(home, {"leaves": {"SA": []}})
    with pytest.raises(ProjectError, match="unknown templates"):
        expand(home, {"leaves": {"LS": []}, "templates": ["memetic"]})
    with pytest.raises(ProjectError, match="builds no composition"):
        expand(home, {"leaves": {"LS": []}, "templates": ["sequential"]})
    with pytest.raises(ProjectError, match="the limit is 1 to 32"):
        expand(home, {"leaves": {"LS": []}, "limit": 100})
    # A leaf with no neighborhood can be restarted, and kicked only in one the grammar names.
    lkh = [Variant(label="LKH", heuristic={"kind": "LinKernighanHelsgaun", "stop": {}})]
    _, composed, _ = expand(home, {"leaves": {"LKH": []}}, leaves=lkh)
    assert [v.label for v in composed] == ["Restart[LKH]"]


def test_a_profile_of_the_leaves_orders_the_compositions(home):
    project = Project.create(home)

    def profiled(label, rank, early, found_at):
        return {
            "label": label,
            "error": None,
            "mean_rank": rank,
            "anytime": [early, 0.0, 0.0, 0.0],
            "best_found_at": found_at,
        }

    record = {
        "id": 1,
        "rev": 1,
        # LS leads early and stalls; Tabu ends best.
        "variants": [profiled("LS", 1.8, 0.01, 0.05), profiled("Tabu", 1.2, 0.2, 0.9)],
    }
    bench.keep_record(bench.profiles_dir(project), 1, record)
    grammar = {"leaves": {"LS": [], "Tabu": []}, "limit": 3}
    _, composed, note = compose.expand(project, 1, LEAVES, grammar, ITERATIONS)
    assert [v.label for v in composed] == ["Seq[LS>Tabu]", "Iter[LS]", "Restart[LS]"]
    assert "3 of 8 compositions, ordered by the latest profile of the leaves" in note
    # A profile of another revision, or one that did not run every leaf, says nothing here.
    _, composed, note = compose.expand(project, 2, LEAVES, grammar, ITERATIONS)
    assert "not profiled together" in note


def test_a_race_chooses_among_leaves_and_their_compositions(home):
    project, _ = tsp_bench(home, train=3, validation=2)
    descent = {"kind": "LocalSearch", "neighbor": "TwoOpt", "stop": {}}
    rev = with_variants(project, ("RW", WALK), ("LS", descent), ("SA", SA))
    grammar = {"leaves": {"RW": [], "LS": [], "SA": []}, "templates": ["iterated", "restart"]}
    with pytest.raises(ProjectError, match="over 9 variants: give at least 324"):
        run(project, rev, None, 100, grammar=grammar)
    with pytest.raises(ProjectError, match="leave variant out"):
        run(project, rev, None, 300, grammar=grammar, variant="RW")
    tuning, evaluation = run(project, rev, None, 400, grammar=grammar)
    assert list(tuning.space) == [
        "RW",
        "LS",
        "SA",
        "Iter[RW]",
        "Restart[RW]",
        "Iter[LS]",
        "Restart[LS]",
        "Iter[SA]",
        "Restart[SA]",
    ]
    assert tuning.default.variant == "RW"
    assert tuning.best.variant != "RW"
    text = tune.report(tuning, evaluation)
    assert "grammar: 3 leaves and 6 of 6 compositions" in text.splitlines()[1]
    # The winner, a leaf or a composition the revision's solve.json never held, is the files' now.
    solve = json.loads(project.read_file("solve.json"))
    assert "heuristics" not in solve
    assert solve["heuristic"] == tuning.heuristic(tuning.best)
    assert evaluation is not None
    assert evaluation.verdict == "better"
    assert bench.tunings(project)[0]["variants"] == list(tuning.space)
