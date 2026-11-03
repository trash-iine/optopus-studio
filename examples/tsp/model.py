"""A tour through every city, shortest total distance: the built-in Tsp."""

import optopus


def build(instance):
    """Builds the built-in Tsp over the cities' coordinates from the instance.

    Args:
        instance: instance.json's content.

    Returns:
        The problem.
    """
    points = [(city["x"], city["y"]) for city in instance["cities"]]
    return optopus.Tsp.from_coordinates(points)


def encode_solution(instance, tour):
    """The tour as a list of city indices.

    Args:
        instance: instance.json's content.
        tour: The problem's solution, the cities in visiting order.

    Returns:
        The tour as a list.
    """
    return list(tour)
