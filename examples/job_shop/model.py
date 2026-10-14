"""Operations on machines, shortest makespan: the built-in JobShopScheduling."""

import optopus


def build(instance):
    jobs = [[tuple(op) for op in job["operations"]] for job in instance["jobs"]]
    return optopus.JobShopScheduling.from_jobs(jobs)


def encode_solution(instance, sequence):
    # Job j appears once per operation; its k-th occurrence schedules its k-th operation.
    return list(sequence)
