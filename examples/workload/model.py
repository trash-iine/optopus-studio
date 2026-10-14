"""Assign every task to a worker who has its skill, so that the busiest worker finishes earliest.

The objective is a maximum, which no polynomial states, so the problem is written in Python. A
solution is ``(assignment, loads)``: the worker of each task, and each worker's hours, kept along
so a move is priced from the two workers it touches.
"""

import random

# Spreading the load also among the workers below the maximum gives the search a slope on the
# plateaus a pure maximum has. It is small enough never to outweigh an hour of the maximum.
SPREAD = 1e-3


def cost(loads):
    return max(loads) + SPREAD * sum(load * load for load in loads)


class Move:
    """Give one task to another worker who has its skill."""

    def neighbors(self, problem, solution):
        assignment, _ = solution
        return [
            (task, worker)
            for task, current in enumerate(assignment)
            for worker in problem.eligible[task]
            if worker != current
        ]

    def random_neighbor(self, problem, solution, rng):
        assignment, _ = solution
        movable = problem.movable
        if not movable:
            return None
        task = rng.choice(movable)
        options = [w for w in problem.eligible[task] if w != assignment[task]]
        return (task, rng.choice(options))

    def apply(self, problem, solution, move):
        assignment, loads = solution
        task, worker = move
        hours = problem.hours[task]
        new_loads = list(loads)
        new_loads[assignment[task]] -= hours
        new_loads[worker] += hours
        new_assignment = (*assignment[:task], worker, *assignment[task + 1 :])
        return (new_assignment, tuple(new_loads))

    def delta(self, problem, solution, move):
        _, loads = solution
        return cost(self.apply(problem, solution, move)[1]) - cost(loads)

    def tabu_keys(self, problem, move):
        return move[0]


class Workload:
    minimize = True

    def __init__(self, instance):
        self.workers = [w["name"] for w in instance["workers"]]
        self.hours = [float(t["hours"]) for t in instance["tasks"]]
        self.eligible = [
            [i for i, w in enumerate(instance["workers"]) if t["skill"] in w["skills"]]
            for t in instance["tasks"]
        ]
        tasks = instance["tasks"]
        missing = [t["name"] for t, e in zip(tasks, self.eligible, strict=True) if not e]
        if missing:
            raise ValueError(f"no worker has the skill for {missing}")
        self.movable = [t for t, e in enumerate(self.eligible) if len(e) > 1]
        self.neighborhoods = {"Move": Move()}

    def loads(self, assignment):
        loads = [0.0] * len(self.workers)
        for task, worker in enumerate(assignment):
            loads[worker] += self.hours[task]
        return tuple(loads)

    def new_solution(self, rng: random.Random):
        assignment = tuple(rng.choice(e) for e in self.eligible)
        return (assignment, self.loads(assignment))

    def objective(self, solution):
        return cost(solution[1])


def build(instance):
    return Workload(instance)


def encode_solution(instance, solution):
    assignment, loads = solution
    return {"assignment": list(assignment), "loads": list(loads)}
