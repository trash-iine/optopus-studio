# 0006. The Python worker reports progress through optopus-py's on_improvement

- Status: Accepted
- Date: 2026-10-14

## Context

ADR 0005 left the Python worker reporting each run only when it finishes, since a run happens
inside one `heuristic.run` call. A problem written in Python is exactly the case whose runs are
long, so its progress matters most.

## Decision

optopus-py's `run` takes an `on_improvement(run, elapsed_secs, objective)` callable, fed by the
core's objective probe: the first improvement at once, then the latest at most every 0.1 s
(trash-iine/optopus-py, branch `feat/run-progress-callback`). The worker passes one that writes
a `progress` event, under a lock since it may run on optopus's ticker thread, and only when the
installed optopus has the argument, so an older optopus still works without progress.

## Consequences

- Both workers report progress the same way, so the GUI's live view no longer depends on the
  worker. ADR 0005's note that only the Rust worker reports progress no longer holds.
- The sibling optopus-py checkout (ADR 0002) must carry that branch until it is released.
