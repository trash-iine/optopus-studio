"""The knapsack's packing: what is in it and how full it is."""


def to_view(instance, result):
    """What the canvas shows of the best run.

    It shows the value and weight packed, and each item.

    Args:
        instance: instance.json's content.
        result: The solve, with the best run as ``best``.

    Returns:
        The views; a note when the solve failed.
    """
    items = instance["items"]
    best = result["best"]
    if best is None:
        return {"views": [{"type": "markdown", "text": "No packing: the solve failed."}]}
    chosen = [item for item, x in zip(items, best["solution"], strict=True) if x]
    weight = sum(item["weight"] for item in chosen)
    views = [
        {
            "type": "kpi",
            "items": [
                {"label": "Value", "value": sum(item["value"] for item in chosen)},
                {"label": "Weight", "value": weight, "unit": f"/ {instance['capacity']}"},
                {"label": "Items packed", "value": len(chosen)},
            ],
        },
        {
            "type": "table",
            "title": "Items",
            "columns": ["item", "value", "weight", "packed"],
            "rows": [
                [item["name"], item["value"], item["weight"], bool(x)]
                for item, x in zip(items, best["solution"], strict=True)
            ],
        },
    ]
    if weight > instance["capacity"]:
        views.append({"type": "markdown", "text": "**Over capacity**: the penalty is too weak."})
    return {"views": views}
