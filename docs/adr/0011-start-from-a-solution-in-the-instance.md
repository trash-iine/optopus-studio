# 0011. Start a solve from a solution kept in instance.json

- Status: Accepted
- Date: 2026-10-19

## Context

optopus-py's `run` takes `initial_solution=`, which starts every run from a given solution
instead of a random one. A user has two uses for it: scoring a plan of their own, such as the
current schedule, against what the search finds, and searching further from an earlier result.
Either way the solution must reach the worker, and a revision should still solve the same way
from its own files (ADR 0004).

## Options

1. solve.json holds the solution itself.
2. solve.json names a revision, and the solve starts from that revision's best solution.
3. solve.json names a key of instance.json, which holds the solution.

## Decision

Option 3. `"initial_solution": "<key>"` in solve.json starts every run from `instance[key]`. The
value is in the form `encode_solution` writes, which is how the result shows it, so the user can
give a plan as a file (`import_upload`) and the agent can reuse a result (`import_solution(rev,
key)` copies a revision's best solution). The worker turns it back with `model.py`'s optional
`decode_solution(instance, value)`, or the Rust port's `decode`, and passes it to every run.

The first option makes the agent copy a solution through `write_file`, which costs tokens in
proportion to its size and lets the agent mistype it. The second makes a revision depend on
another revision's result, so it no longer solves the same way on its own, and cannot be
packaged as an app without it.

## Consequences

- A revision freezes the solution it started from with its data. An app's input can replace that
  key like any other, so its user can bring their own plan.
- The worker protocol gains `SolveRequest.initial_solution` and a `start` stage, at which a solve
  stops when the solution cannot be decoded or does not fit the problem.
- A model whose `encode_solution` changes the solution's form needs `decode_solution` to start
  from one. The system prompt and the Rust guide say so.
