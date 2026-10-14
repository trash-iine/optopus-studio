# 0005. A Rust worker is a per-project port, verified before it runs

- Status: Accepted
- Date: 2026-10-14

## Context

ADR 0001 kept the solver behind a process boundary so that a Rust solver could replace the
Python one. A built-in problem or a `Formula` already searches in Rust through the bindings; the
case that gains is a problem written in Python, whose every move goes through Python callbacks.
Such a problem exists only in its project's `model.py`, so no generic Rust binary can run it.

The core's own configuration-driven factory (`optopus::benchmark`) is crate-private and knows
only the built-in neighborhoods.

## Decision

- `workers/rust` is a library, `optopus-studio-worker`. It speaks the worker protocol, builds
  heuristics from `solve.json`'s JSON at run time with optopus-py's argument names and defaults,
  derives seeds and records trajectories as optopus-py does, and reports progress during a run
  from the core's objective probe.
- A project's port is one file, `rust/main.rs`: the problem implementing `StudioProblem`, a
  `build(instance)` and `main() { serve(build) }`. The agent writes it, guided by
  `workers/rust/GUIDE.md` and the ports in `examples/`. The studio wraps it in a crate, builds
  it into a shared target directory, and caches the binary by a hash of the port and the library.
- `"worker": "rust"` in `solve.json` selects it; `view.py`, `instance.json` and the heuristics
  stay as they are. A revision freezes `rust/main.rs` with the other files.
- Before switching, `verify_rust` runs both workers with the same seeds. The port must score the
  Python worker's solutions identically, reproduce a built-in problem's runs exactly or match a
  Python problem's results statistically (the port-to-rust skill's rule), and render with
  `view.py`.

## Consequences

- Changing `solve.json` never needs a rebuild; changing the model means changing both files and
  verifying again. `model.py` stays the reference.
- The Rust worker supports the generic and nested heuristics. Crossover-based and
  problem-specific heuristics need a `build_special` in the port (built in for `Tsp`).
- The first build compiles optopus (about 15 s); later ports rebuild in about a second.
- Only the Rust worker reports progress during a run. The Python worker reports each run as it
  finishes; reporting inside a run needs a callback in optopus-py's `run`.
