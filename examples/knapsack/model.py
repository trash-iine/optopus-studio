"""Pack the most value within the weight capacity: a Formula over one binary per item."""

import optopus


def build(instance):
    items = instance["items"]
    # An app's user gives their own items (app.json), so say what is wrong in their terms. Rows
    # count from 2, as in the spreadsheet whose first row is the header.
    if not items:
        raise ValueError("there are no items to pack")
    for row, item in enumerate(items, start=2):
        if item["weight"] <= 0:
            raise ValueError(
                f"item {item['name']!r} (row {row}) weighs {item['weight']}; "
                "every weight must be positive"
            )
    # Penalty per unit of overweight: more than any item's value per unit of weight, so dropping
    # weight always beats carrying too much.
    weight = 1 + max(item["value"] / item["weight"] for item in items)
    return optopus.Formula(
        n_vars=len(items),
        objective=[([i], float(item["value"])) for i, item in enumerate(items)],
        direction="Maximize",
        constraints=[
            (
                [([i], float(item["weight"])) for i, item in enumerate(items)],
                "<=",
                [([], float(instance["capacity"]))],
                weight,
            )
        ],
    )
