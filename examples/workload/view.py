"""The workload's assignment: each worker's tasks and hours."""


def to_view(instance, result):
    """What the canvas shows of the best run.

    It shows the loads, each worker's tasks, and any skill mismatch.

    Args:
        instance: instance.json's content.
        result: The solve, with the best run as ``best``.

    Returns:
        The views; a note when the solve failed.
    """
    best = result["best"]
    if best is None:
        return {"views": [{"type": "markdown", "text": "No assignment: the solve failed."}]}
    workers = [w["name"] for w in instance["workers"]]
    assignment = best["solution"]["assignment"]
    tasks, clock = [], [0.0] * len(workers)
    for task, worker in zip(instance["tasks"], assignment, strict=True):
        start = clock[worker]
        clock[worker] += task["hours"]
        tasks.append(
            {
                "lane": workers[worker],
                "label": task["name"],
                "start": start,
                "end": clock[worker],
                "group": task["skill"],
            }
        )
    wrong = [
        t["name"]
        for t, w in zip(instance["tasks"], assignment, strict=True)
        if t["skill"] not in instance["workers"][w]["skills"]
    ]
    busiest, mean = max(clock), sum(clock) / len(clock)
    views = [
        {
            "type": "kpi",
            "items": [
                {"label": "Busiest worker", "value": busiest, "unit": "h"},
                {"label": "Average load", "value": round(mean, 2), "unit": "h"},
                {"label": "Spread (max - min)", "value": busiest - min(clock), "unit": "h"},
            ],
        },
        {"type": "gantt", "title": "Tasks per worker", "tasks": tasks, "time_unit": "h"},
        {
            "type": "bar",
            "title": "Hours per worker",
            "categories": workers,
            "series": [{"name": "hours", "values": clock}],
        },
    ]
    if wrong:
        views.append({"type": "markdown", "text": f"**Skill mismatch**: {', '.join(wrong)}"})
    return {"views": views}
