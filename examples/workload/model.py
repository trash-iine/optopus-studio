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
    """The objective of some loads: the maximum, and a little of their spread.

    Args:
        loads: Each worker's hours.

    Returns:
        The objective.
    """
    return max(loads) + SPREAD * sum(load * load for load in loads)


class Move:
    """Give one task to another worker who has its skill."""

    def neighbors(self, problem, solution):
        """Every move from a solution: each task to each other worker with its skill.

        Args:
            problem: The problem.
            solution: The solution, ``(assignment, loads)``.

        Returns:
            The moves.
        """
        assignment, _ = solution
        return [
            (task, worker)
            for task, current in enumerate(assignment)
            for worker in problem.eligible[task]
            if worker != current
        ]

    def random_neighbor(self, problem, solution, rng):
        """A move drawn at random from a solution.

        Args:
            problem: The problem.
            solution: The solution, ``(assignment, loads)``.
            rng: The random source.

        Returns:
            The move, or None when no task can move.
        """
        assignment, _ = solution
        movable = problem.movable
        if not movable:
            return None
        task = rng.choice(movable)
        options = [w for w in problem.eligible[task] if w != assignment[task]]
        return (task, rng.choice(options))

    def apply(self, problem, solution, move):
        """The solution a move leads to, its loads updated from the two workers it touches.

        Args:
            problem: The problem.
            solution: The solution, ``(assignment, loads)``.
            move: The move, ``(task, worker)``.

        Returns:
            The new solution.
        """
        assignment, loads = solution
        task, worker = move
        hours = problem.hours[task]
        new_loads = list(loads)
        new_loads[assignment[task]] -= hours
        new_loads[worker] += hours
        new_assignment = (*assignment[:task], worker, *assignment[task + 1 :])
        return (new_assignment, tuple(new_loads))

    def delta(self, problem, solution, move):
        """How much a move changes the objective.

        Args:
            problem: The problem.
            solution: The solution, ``(assignment, loads)``.
            move: The move, ``(task, worker)``.

        Returns:
            The change; negative is better.
        """
        _, loads = solution
        return cost(self.apply(problem, solution, move)[1]) - cost(loads)

    def tabu_keys(self, problem, move):
        """What a tabu search forbids for a while after a move: moving the same task again.

        Args:
            problem: The problem.
            move: The move, ``(task, worker)``.

        Returns:
            The task.
        """
        return move[0]


class Workload:
    """The workload problem, written in Python: tasks to workers with the skill.

    Attributes:
        minimize: The busiest worker's hours are minimized.
        workers: The workers' names.
        hours: Each task's hours.
        eligible: Each task's workers with its skill.
        movable: The tasks more than one worker can do.
        neighborhoods: The moves the search makes, by name.
    """

    minimize = True

    def __init__(self, instance):
        """Reads the instance.

        Args:
            instance: instance.json's content.

        Raises:
            ValueError: A task has no worker with its skill.
        """
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
        """Each worker's hours under an assignment.

        Args:
            assignment: Each task's worker.

        Returns:
            The hours, by worker.
        """
        loads = [0.0] * len(self.workers)
        for task, worker in enumerate(assignment):
            loads[worker] += self.hours[task]
        return tuple(loads)

    def new_solution(self, rng: random.Random):
        """A random solution: each task to a worker with its skill.

        Args:
            rng: The random source.

        Returns:
            The solution, ``(assignment, loads)``.
        """
        assignment = tuple(rng.choice(e) for e in self.eligible)
        return (assignment, self.loads(assignment))

    def objective(self, solution):
        """A solution's objective.

        Args:
            solution: The solution, ``(assignment, loads)``.

        Returns:
            The objective.
        """
        return cost(solution[1])


def build(instance):
    """Builds the workload problem from the instance.

    Args:
        instance: instance.json's content.

    Returns:
        The problem.
    """
    return Workload(instance)


def encode_solution(instance, solution):
    """The solution as JSON: each task's worker, and each worker's hours.

    Args:
        instance: instance.json's content.
        solution: The solution, ``(assignment, loads)``.

    Returns:
        ``{"assignment": [...], "loads": [...]}``.
    """
    assignment, loads = solution
    return {"assignment": list(assignment), "loads": list(loads)}


def decode_solution(instance, value):
    """The inverse of encode_solution, for a solve that starts from a given assignment.

    Args:
        instance: instance.json's content.
        value: The solution as encode_solution writes it.

    Returns:
        The solution, its loads computed again.

    Raises:
        ValueError: The assignment has the wrong length, or gives a task to a worker without its
            skill.
    """
    problem = Workload(instance)
    assignment = tuple(value["assignment"])
    if len(assignment) != len(problem.hours):
        raise ValueError(f"the assignment has {len(assignment)} tasks, not {len(problem.hours)}")
    for task, (worker, eligible) in enumerate(zip(assignment, problem.eligible, strict=True)):
        if worker not in eligible:
            raise ValueError(f"task {task} goes to worker {worker}, who lacks its skill")
    return (assignment, problem.loads(assignment))
