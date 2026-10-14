# 0001. Keep the solver behind a process boundary, Python first

- Status: Accepted
- Date: 2026-10-14

## Context

The studio should iterate fast now (the agent writes a model, solves, redraws within one chat
turn) and get faster later by moving solvers to Rust. A Rust rewrite must not mean rewriting the
GUI or the agent's workflow.

## Options

1. Python only: the backend imports optopus and calls it in-process.
2. Rust from the start: the agent writes Rust problem definitions and the studio compiles them.
3. Python first, with the solver behind a fixed process boundary that a Rust program can speak.

## Decision

Option 3. The solver is a subprocess that reads one `SolveRequest` and writes `WorkerEvent`s as
JSON Lines (`protocol.py`, `schema/worker-event.json`). The solution it reports is plain JSON.
Turning a solution into what the canvas draws happens outside the solver, in the project's
`view.py`, run by the backend. `OPTOPUS_STUDIO_WORKER` selects the solver command.

Rust from the start was rejected because a compile (tens of seconds, minutes with the release
profile) sits inside every chat round trip, while built-in problems and `Formula` already run at
Rust speed through the bindings: only problems written in Python pay for Python.

## Consequences

- A Rust worker is a drop-in replacement: same request, same events, same `view.py`, no GUI change.
  Its runs can be checked against the Python worker's with the same seed by comparing
  `(iteration, objective)` along the trajectory, which, unlike time, reproduces exactly.
- Generated code runs in a subprocess with a timeout, so a hang or crash in it cannot take the
  server down.
- A worker cannot return Python objects; a problem written in Python needs `encode_solution`
  when its solution is not JSON already.
- Progress arrives per finished run. Live progress within a run needs a callback in the core
  (trash-iine/optopus) first.
