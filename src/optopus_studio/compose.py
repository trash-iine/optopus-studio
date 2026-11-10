"""Compositions of heuristics, generated from a small grammar for ``tune`` to race (docs/adr/0021).

``tune`` chooses among the variants the agent wrote (docs/adr/0014), and a profile's readings
name compositions worth writing (docs/adr/0015). Writing them is still the agent's: a
``Sequential`` of this and that, each step with a stop, then the same around another pair. A
*grammar* does that part: the agent names the *leaves*, variants of solve.json with their
parameters, and ``expand`` builds the compositions of depth one over them:

- ``sequential``: ``Sequential`` of two leaves, in both orders, each step with a stop of its own;
- ``iterated``: ``Iterated`` with a leaf as the search and a short ``RandomWalk`` as the kick;
- ``restart``: ``Restart`` of a leaf from random solutions, an attempt ending when it stalls;
- ``vns``: ``VariableNeighborhoodSearch`` with a leaf as the search and three growing shakes.

Each composition comes with its parameters: the leaf's own, moved to where the leaf sits, and
the ones the composition adds (the steps' stops, the kick's strength and neighborhood). The
leaves and the compositions are then one space for the race, which chooses the structure and
sets its numbers together.

When the leaves were profiled, the compositions the profile's numbers favor come first (a
``Sequential`` from the leaf that leads early to the one that ends best, a leaf that stalls
inside ``Iterated``), and only the first ``limit`` are raced.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from optopus_studio import bench
from optopus_studio.projects import Project, ProjectError
from optopus_studio.protocol import BenchSpec, Variant

TEMPLATES = ("sequential", "iterated", "restart", "vns")
# The compositions a race takes besides the leaves, unless the grammar says otherwise.
LIMIT = 12
MAX_LIMIT = 32
# The share of the benchmark's budget a step of a composition runs for before it is tuned, and
# the shares a race may give it.
STEP_SHARE = 0.1
STEP_SHARES = (0.01, 0.5)
# A kick's length in moves, and the lengths a race may give it.
KICK, KICKS = 5, (1, 50)
# The iterations without a new best after which an attempt of a restart ends.
STALL, STALLS = 2000, (50, 50000)
# A profile's share of the budget below which a leaf's best came early: it stalls.
EARLY = 0.25


@dataclass
class Composed:
    """One composition, as a variant to race.

    Attributes:
        label: Its label, which names the template and the leaves.
        heuristic: The heuristic's dict.
        space: Its parameters, as ``tune`` takes them.
        score: Where a profile of the leaves ranks it, lower first; 0 without a profile.
    """

    label: str
    heuristic: dict[str, Any]
    space: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


def _step_stop(spec: BenchSpec) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """The stop a step of a composition starts with, and the range a race may give it.

    A step's stop is in the benchmark's own measure: iterations when the budget counts them,
    seconds otherwise.

    Args:
        spec: The benchmark's spec.

    Returns:
        The stop's key, the stop, and the rest of the parameter that tunes it.
    """
    low, high = STEP_SHARES
    if spec.max_iteration is not None:
        n = spec.max_iteration
        value = max(1, round(n * STEP_SHARE))
        tuned = {"type": "int", "low": max(1, round(n * low)), "high": max(2, round(n * high))}
        return "max_iteration", {"max_iteration": value}, {**tuned, "log": True}
    seconds = spec.max_duration_secs
    assert seconds is not None
    tuned = {"type": "float", "low": seconds * low, "high": seconds * high, "log": True}
    return "max_duration_secs", {"max_duration_secs": seconds * STEP_SHARE}, tuned


def _moved(space: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """A leaf's parameters, at the place the leaf takes in a composition.

    Args:
        space: The leaf's parameters.
        prefix: The path of the leaf in the composition, such as ``steps.0``.

    Returns:
        The parameters, their names under that path.
    """
    return [{**p, "name": f"{prefix}.{p['name']}"} for p in space]


def _as_step(heuristic: dict[str, Any], stop: dict[str, Any]) -> dict[str, Any]:
    """A leaf's heuristic as a step of a composition, with a stop of its own.

    Args:
        heuristic: The leaf's heuristic.
        stop: The step's stop.

    Returns:
        A copy with that stop.
    """
    return {**copy.deepcopy(heuristic), "stop": dict(stop)}


def _neighbors(leaf: Variant, kicks: list[str]) -> list[str]:
    """The neighborhoods a kick around a leaf may use.

    Args:
        leaf: The leaf.
        kicks: The neighborhoods the grammar names for kicks.

    Returns:
        Those, or the leaf's own neighborhood when the grammar names none; none when the leaf
        has no neighborhood either.
    """
    own = leaf.heuristic.get("neighbor")
    return kicks or ([own] if isinstance(own, str) else [])


def _walk(neighbor: str, length: int) -> dict[str, Any]:
    """A random walk of some moves, as a kick or a shake.

    Args:
        neighbor: The neighborhood it moves in.
        length: Its moves.

    Returns:
        The heuristic.
    """
    return {"kind": "RandomWalk", "neighbor": neighbor, "stop": {"max_iteration": length}}


def _build(
    template: str,
    leaves: list[Variant],
    spaces: dict[str, list[dict[str, Any]]],
    spec: BenchSpec,
    kicks: list[str],
) -> list[Composed]:
    """Every composition one template makes of the leaves.

    Args:
        template: The template's name.
        leaves: The leaves.
        spaces: Each leaf's parameters, by label.
        spec: The benchmark's spec, for the steps' stops.
        kicks: The neighborhoods the grammar names for kicks.

    Returns:
        The compositions; none where a leaf lacks what the template needs.
    """
    key, stop, tuned = _step_stop(spec)
    kick = {"type": "int", "low": KICKS[0], "high": KICKS[1], "log": True}
    made = []
    if template == "sequential":
        for a in leaves:
            for b in leaves:
                if a is b:
                    continue
                steps = [_as_step(a.heuristic, stop), _as_step(b.heuristic, stop)]
                space = [
                    {"name": f"steps.0.stop.{key}", **tuned},
                    {"name": f"steps.1.stop.{key}", **tuned},
                    *_moved(spaces[a.label], "steps.0"),
                    *_moved(spaces[b.label], "steps.1"),
                ]
                made.append(
                    Composed(
                        f"Seq[{a.label}>{b.label}]", {"kind": "Sequential", "steps": steps}, space
                    )
                )
        return made
    for leaf in leaves:
        moves = _neighbors(leaf, kicks)
        if template == "restart":
            attempt = _as_step(leaf.heuristic, {"max_failed_update": STALL})
            heuristic = {"kind": "Restart", "heuristic": attempt, "restart": {"max_iteration": 0}}
            stall = {"type": "int", "low": STALLS[0], "high": STALLS[1], "log": True}
            space = [
                {"name": "heuristic.stop.max_failed_update", **stall},
                *_moved(spaces[leaf.label], "heuristic"),
            ]
            made.append(Composed(f"Restart[{leaf.label}]", heuristic, space))
        elif not moves:
            # A kick needs a neighborhood, and this leaf names none.
            continue
        elif template == "iterated":
            heuristic = {
                "kind": "Iterated",
                "search": _as_step(leaf.heuristic, stop),
                "perturbation": _walk(moves[0], KICK),
            }
            space = [
                {"name": f"search.stop.{key}", **tuned},
                {"name": "perturbation.stop.max_iteration", **kick},
                *_moved(spaces[leaf.label], "search"),
            ]
            if len(moves) > 1:
                space.append({"name": "perturbation.neighbor", "choices": moves})
            made.append(Composed(f"Iter[{leaf.label}]", heuristic, space))
        elif template == "vns":
            heuristic = {
                "kind": "VariableNeighborhoodSearch",
                "search": _as_step(leaf.heuristic, stop),
                "shakes": [_walk(moves[0], length) for length in (2, 4, 8)],
            }
            space = [{"name": f"search.stop.{key}", **tuned}, *_moved(spaces[leaf.label], "search")]
            made.append(Composed(f"VNS[{leaf.label}]", heuristic, space))
    return made


def _profile_of(project: Project, rev: int, labels: list[str]) -> dict[str, dict[str, Any]] | None:
    """The latest profile of revision ``rev`` that ran every leaf, by leaf.

    Args:
        project: The project.
        rev: The revision.
        labels: The leaves' labels.

    Returns:
        Each leaf's entry of the profile's record, or None when no profile ran them all.
    """
    for record in reversed(bench.profiles(project)):
        ran = {v["label"]: v for v in record["variants"] if v["error"] is None}
        if record["rev"] == rev and all(label in ran for label in labels):
            return ran
    return None


def _score(template: str, leaves: list[str], ran: dict[str, dict[str, Any]]) -> float:
    """Where a profile of the leaves ranks a composition: lower is more promising.

    A ``Sequential`` is ranked by how early its first leaf leads and how well its second ends;
    the others by how well their leaf ends, ahead when it stalls, which is what they are for.

    Args:
        template: The composition's template.
        leaves: The labels of the leaves it is made of, in order.
        ran: Each leaf's entry of the profile's record.

    Returns:
        The score.
    """

    def place(label: str, value: Any) -> int:
        """A leaf's place among the leaves by some measure, 0 the best.

        Args:
            label: The leaf's label.
            value: The measure, lower the better.

        Returns:
            The place.
        """
        return sorted(ran, key=value).index(label)

    def ends(label: str) -> float:
        """How well a leaf ends: its mean rank in the profile.

        Args:
            label: The leaf's label.

        Returns:
            The mean rank.
        """
        return ran[label]["mean_rank"]

    def leads(label: str) -> float:
        """How early a leaf leads: its gap to the best at the first share of the budget.

        Args:
            label: The leaf's label.

        Returns:
            The gap.
        """
        return ran[label]["anytime"][0]

    if template == "sequential":
        first, second = leaves
        return place(first, leads) + place(second, ends)
    (leaf,) = leaves
    found_at = ran[leaf]["best_found_at"]
    stalls = found_at is not None and found_at < EARLY
    return place(leaf, ends) + (0.0 if stalls else 1.5)


def expand(
    project: Project, rev: int, variants: list[Variant], grammar: Any, spec: BenchSpec
) -> tuple[dict[str, list[dict[str, Any]]], list[Variant], str]:
    """The space a grammar spans: its leaves and the compositions built of them.

    Args:
        project: The project, for a profile of the leaves.
        rev: The revision whose variants the leaves are.
        variants: The variants of that revision's solve.json.
        grammar: The grammar, as the agent gave it: ``leaves`` (each label with its
            parameters, the incumbent first), and ``templates``, ``kicks`` and ``limit`` if given.
        spec: The benchmark's spec.

    Returns:
        Each variant's parameters by label, the leaves first; the compositions as variants to add
        to solve.json; and a line saying what was built, and what a profile had to say.

    Raises:
        ProjectError: The grammar is malformed, names an unknown leaf or template, or builds
            nothing.
    """
    if not isinstance(grammar, dict) or not isinstance(grammar.get("leaves"), dict):
        raise ProjectError(
            "give the grammar as {'leaves': {label: parameters, ...}}, the incumbent's first"
        )
    spaces = grammar["leaves"]
    known = {v.label: v for v in variants}
    unknown = [label for label in spaces if label not in known]
    if unknown or not spaces:
        raise ProjectError(
            f"revision {rev} has no variants {unknown}; it has {list(known)}: put the heuristics "
            "to compose as variants of solve.json and run_solver"
        )
    templates = grammar.get("templates") or list(TEMPLATES)
    bad = [t for t in templates if t not in TEMPLATES]
    if bad:
        raise ProjectError(f"unknown templates {bad}; expected some of {list(TEMPLATES)}")
    limit = int(grammar.get("limit") or LIMIT)
    if not 1 <= limit <= MAX_LIMIT:
        raise ProjectError(f"the limit is 1 to {MAX_LIMIT} compositions, not {limit}")
    kicks = [str(k) for k in grammar.get("kicks") or []]
    leaves = [known[label] for label in spaces]

    ran = _profile_of(project, rev, list(spaces))
    groups = [_build(template, leaves, spaces, spec, kicks) for template in templates]
    if ran:
        for template, group in zip(templates, groups, strict=True):
            for c in group:
                inside = c.label[c.label.index("[") + 1 : -1].split(">")
                c.score = _score(template, inside, ran)
        ordered = sorted((c for group in groups for c in group), key=lambda c: c.score)
    else:
        # Without a profile, one of each template in turn, the leaves in the order given.
        longest = max(map(len, groups), default=0)
        ordered = [group[i] for i in range(longest) for group in groups if i < len(group)]
    if not ordered:
        raise ProjectError(
            "the grammar builds no composition: 'sequential' needs two leaves, and 'iterated' "
            "and 'vns' a leaf with a 'neighbor', or 'kicks' naming the neighborhoods to kick in"
        )
    chosen = ordered[:limit]
    clash = [c.label for c in chosen if c.label in known]
    if clash:
        raise ProjectError(f"solve.json already has variants named {clash}; rename them")
    space = {**spaces, **{c.label: c.space for c in chosen}}
    basis = (
        "ordered by the latest profile of the leaves"
        if ran
        else "in the order of the leaves, which were not profiled together"
    )
    note = (
        f"grammar: {len(spaces)} leaves and {len(chosen)} of {len(ordered)} compositions, {basis}: "
        + ", ".join(c.label for c in chosen)
    )
    return space, [Variant(label=c.label, heuristic=c.heuristic) for c in chosen], note
