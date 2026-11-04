"""The job shop's schedule, machine by machine."""


def schedule(instance, sequence):
    """Starts each operation as early as its job and its machine allow, in sequence order.

    Args:
        instance: instance.json's content.
        sequence: The solution: each job's index once per operation, in sequence order.

    Returns:
        A Gantt task per operation.
    """
    jobs = instance["jobs"]
    next_op = [0] * len(jobs)
    job_ready = [0] * len(jobs)
    machine_ready = [0] * len(instance["machines"])
    tasks = []
    for j in sequence:
        machine, duration = jobs[j]["operations"][next_op[j]]
        start = max(job_ready[j], machine_ready[machine])
        end = start + duration
        tasks.append(
            {
                "lane": instance["machines"][machine],
                "label": f"{jobs[j]['name']}-{next_op[j] + 1}",
                "start": start,
                "end": end,
                "group": jobs[j]["name"],
            }
        )
        next_op[j] += 1
        job_ready[j] = machine_ready[machine] = end
    return tasks


def to_view(instance, result):
    """What the canvas shows of the best run.

    It shows the makespan, the schedule, and each machine's utilization.

    Args:
        instance: instance.json's content.
        result: The solve, with the best run as ``best``.

    Returns:
        The views; a note when the solve failed.
    """
    best = result["best"]
    if best is None:
        return {"views": [{"type": "markdown", "text": "No schedule: the solve failed."}]}
    tasks = schedule(instance, best["solution"])
    makespan = max(t["end"] for t in tasks)
    busy = {}
    for t in tasks:
        busy[t["lane"]] = busy.get(t["lane"], 0) + t["end"] - t["start"]
    return {
        "views": [
            {
                "type": "kpi",
                "items": [
                    {"label": "Makespan", "value": makespan, "unit": "h"},
                    {"label": "Jobs", "value": len(instance["jobs"])},
                    {"label": "Machines", "value": len(instance["machines"])},
                ],
            },
            {"type": "gantt", "title": "Schedule", "tasks": tasks, "time_unit": "h"},
            {
                "type": "bar",
                "title": "Machine utilization (%)",
                "categories": instance["machines"],
                "series": [
                    {
                        "name": "busy",
                        "values": [
                            round(100 * busy.get(m, 0) / makespan, 1) for m in instance["machines"]
                        ],
                    }
                ],
            },
        ]
    }
