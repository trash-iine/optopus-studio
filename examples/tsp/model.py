"""A tour through every city, shortest total distance: the built-in Tsp."""

import optopus


def build(instance):
    points = [(city["x"], city["y"]) for city in instance["cities"]]
    return optopus.Tsp.from_coordinates(points)


def encode_solution(instance, tour):
    return list(tour)
