"""Operations on machines, shortest makespan: the built-in JobShopScheduling."""

import optopus


def build(instance):
    """Builds the built-in job shop problem from the instance.

    Args:
        instance: instance.json's content.

    Returns:
        The problem.
    """
    jobs = [[tuple(op) for op in job["operations"]] for job in instance["jobs"]]
    return optopus.JobShopScheduling.from_jobs(jobs)


def encode_solution(instance, sequence):
    """The operation sequence as a list of job indices.

    Args:
        instance: instance.json's content.
        sequence: The problem's solution: each job's index once per operation, in sequence order.

    Returns:
        The sequence as a list.
    """
    # Job j appears once per operation; its k-th occurrence schedules its k-th operation.
    return list(sequence)
