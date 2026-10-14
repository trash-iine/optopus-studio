"""Pack the most value within the weight capacity: a Formula over one binary per item."""

import optopus


def build(instance):
    items = instance["items"]
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
