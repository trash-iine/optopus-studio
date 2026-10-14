import math


def to_view(instance, result):
    cities = instance["cities"]
    points = [{"id": i, "x": c["x"], "y": c["y"], "label": c["name"]} for i, c in enumerate(cities)]
    best = result["best"]
    if best is None:
        return {"views": [{"type": "route_map", "title": "Cities", "points": points, "routes": []}]}
    tour = best["solution"]
    legs = [
        math.dist(
            (cities[a]["x"], cities[a]["y"]),
            (cities[b]["x"], cities[b]["y"]),
        )
        for a, b in zip(tour, tour[1:] + tour[:1], strict=True)
    ]
    return {
        "views": [
            {
                "type": "kpi",
                "items": [
                    {"label": "Tour length", "value": round(sum(legs), 2)},
                    {"label": "Cities", "value": len(cities)},
                    {"label": "Longest leg", "value": round(max(legs), 2)},
                ],
            },
            {
                "type": "route_map",
                "title": "Best tour",
                "points": points,
                "routes": [{"path": tour, "label": "tour"}],
            },
            {
                "type": "table",
                "title": "Visiting order",
                "columns": ["#", "city", "leg to next"],
                "rows": [
                    [k + 1, cities[c]["name"], round(leg, 2)]
                    for k, (c, leg) in enumerate(zip(tour, legs, strict=True))
                ],
            },
        ]
    }
