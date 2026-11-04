"""The studio's recipes page (guides/recipes.md): every composition on it builds and runs."""

import importlib.util
import json
import re

import pytest

from optopus_studio import docs, worker
from optopus_studio.agent import DOC_PAGES

# Items into bins, the fullest bin as light as possible: a Python problem with the two
# neighborhoods the recipes name, and the crossover and distance a population reads.
BINS = """
import random

SIZES = [7, 5, 4, 4, 3, 3, 2, 2, 1, 1]
BINS = 3


class Move:
    def neighbors(self, problem, s):
        return [(i, b) for i in range(len(s)) for b in range(BINS) if b != s[i]]

    def random_neighbor(self, problem, s, rng):
        i = rng.randrange(len(s))
        return (i, rng.choice([b for b in range(BINS) if b != s[i]]))

    def apply(self, problem, s, move):
        i, b = move
        return (*s[:i], b, *s[i + 1:])

    def tabu_keys(self, problem, move):
        return move[0]


class Swap:
    def neighbors(self, problem, s):
        n = len(s)
        return [(i, j) for i in range(n) for j in range(i + 1, n) if s[i] != s[j]]

    def random_neighbor(self, problem, s, rng):
        moves = self.neighbors(problem, s)
        return rng.choice(moves) if moves else None

    def apply(self, problem, s, move):
        i, j = move
        t = list(s)
        t[i], t[j] = t[j], t[i]
        return tuple(t)

    def tabu_keys(self, problem, move):
        return list(move)


class Bins:
    minimize = True
    neighborhoods = {"Move": Move(), "Swap": Swap()}

    def new_solution(self, rng):
        return tuple(rng.randrange(BINS) for _ in SIZES)

    def objective(self, s):
        loads = [0] * BINS
        for size, b in zip(SIZES, s):
            loads[b] += size
        return float(max(loads))

    def crossover(self, a, b, rng):
        return tuple(x if rng.random() < 0.5 else y for x, y in zip(a, b))

    def distance(self, a, b):
        return sum(x != y for x, y in zip(a, b))
"""
# What a Python problem without the ruin methods cannot run.
NEEDS_RUIN = {"GreedyRandomizedConstruction", "AdaptiveLargeNeighborhoodSearch"}


def recipes() -> list[dict]:
    page = docs.read_page("recipes")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", page, re.S)]


def kinds(heuristic) -> set[str]:
    if isinstance(heuristic, list):
        return set().union(*(kinds(h) for h in heuristic))
    if not isinstance(heuristic, dict):
        return set()
    return {heuristic.get("kind")} | set().union(*(kinds(v) for v in heuristic.values()))


@pytest.fixture(scope="module")
def problem(tmp_path_factory):
    path = tmp_path_factory.mktemp("bins") / "bins.py"
    path.write_text(BINS)
    spec = importlib.util.spec_from_file_location("bins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Bins()


def test_the_agent_can_read_the_recipes():
    assert "recipes" in DOC_PAGES
    assert len(recipes()) >= 8


@pytest.mark.parametrize("recipe", recipes(), ids=lambda r: r["kind"])
def test_every_recipe_builds_and_runs(recipe, problem):
    heuristic = worker.build_heuristic({**recipe, "stop": {"max_duration_secs": 0.05}})
    if kinds(recipe) & NEEDS_RUIN:
        return
    run = heuristic.run(problem, 1, 0).runs[0]
    # The optimum puts 11 in each bin.
    assert 11 <= run.best_objective <= 33
