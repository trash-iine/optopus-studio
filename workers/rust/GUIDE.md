# Porting a model to Rust

A project's `rust/main.rs` is its `model.py` in Rust. The studio wraps it in a crate that depends
on `optopus-studio-worker` (this directory), builds it, and runs it instead of the Python worker
when `solve.json` says `"worker": "rust"`. `solve.json`, `instance.json` and `view.py` stay as
they are: heuristics are still built from `solve.json` at run time, and the port must encode
solutions exactly as `model.py`'s `encode_solution` does, because `view.py` reads them.

## When it pays

- A problem **written in Python** runs every move through Python callbacks; a port runs the same
  search 10-100x faster. This is the case to port.
- A **built-in problem** or a **Formula** already searches in Rust through the bindings. A port
  only saves process start-up; say so rather than porting.

## The file

```rust
use optopus_studio_worker::prelude::*;

// ... the problem, its solution and its moves ...

fn build(instance: &Value) -> Result<MyProblem, String> {
    // what model.py's build(instance) does, reading the same instance.json
}

fn main() -> std::process::ExitCode {
    serve(build)
}
```

`prelude` brings `optopus::prelude::*` (traits, `Evaluable`, heuristics), `TabuKey` /
`TabuMemory`, `OptError`, `rand::{Rng, rngs::SmallRng, seq::IndexedRandom}` and
`serde_json::{Value, Map, json}`. No other crate is available.

For a built-in problem, `build` returns it directly (`optopus_studio_worker::optopus::problem::Tsp`
and `JobShopScheduling` are already `StudioProblem`s), and the file is only `build` and `main`.

For a problem written in Python, implement, mirroring the Python class:

| Python | Rust |
|---|---|
| the solution value | a `#[derive(Clone)]` struct with `impl Evaluate` returning `Evaluable::Minimize(cost)` or `Evaluable::Maximize(value)`; cache the objective in it |
| `new_solution(rng)` | `impl ProblemTrait { type Solution; fn new_solution(&self, rng: &mut impl Rng) }` |
| a neighborhood | a `#[derive(Clone)]` move struct per neighborhood |
| `delta(problem, s, move)` | store the change in the move when it is made, and `impl Evaluate for Move` returning it with the problem's direction (`Minimize(delta)` for a cost) |
| `apply(problem, s, move)` | `MoveToNeighbor::apply_to_solution`, in place, keeping the cached objective right |
| `neighbors(problem, s)` | `MoveToNeighbor::iter` |
| `random_neighbor(problem, s, rng)` | `MoveToNeighbor::random_neighbor` (uniform over the same moves as `iter`, `None` exactly when it is empty) |
| `tabu_keys(problem, move)` | `impl EnabledTabu` with `TabuKey::DenseVar(i)` for one small int, `TabuKey::Pair(i, j)` or `TabuKey::Triple(i, j, k)` for a tuple, and `fn tabu_policy(&self) -> Option<&dyn EnabledTabu> { Some(self) }` in `MoveToNeighbor` |
| `minimize`, `objective`, `encode_solution` | `impl StudioProblem` |

`StudioProblem` asks for:

- `const NAME` — the Python class name.
- `higher_is_better(&self)` — `not minimize`.
- `objective(s)` — what Python's `objective` returns, as `f64`.
- `encode(&self, s)` — exactly what `encode_solution` returns (same keys, same order of lists).
- `decode(&self, value)` — the inverse; the studio checks the port by scoring the Python
  worker's solutions with it.
- `with_neighbor(name, visitor)` — `match name { "Move" => Ok(visitor.visit::<Move>()), _ =>
  Err(unknown_neighbor(name, &["Move"])) }`, one arm per neighborhood name in `model.py`.

Override `move_to_be_better_than(&self, problem, src, other)` with the cached objective
(`src.cost + self.delta < other.cost` for a cost), or the core clones the solution for it.

Every move type also needs `EnabledTabu`; a neighborhood without `tabu_keys` keys on whatever
identifies the move.

## Checking it

`build_rust` compiles the file and returns the compiler's errors. `verify_rust` then runs both
workers with the same seeds and checks that the port scores the Python solutions identically,
that it searches as well (exactly the same runs for a built-in problem), that `view.py` renders
its result, and how much faster it is. Switch `solve.json` to `"worker": "rust"` only after it
passes.

The complete ports of `examples/tsp` (a built-in problem) and `examples/workload` (a problem
written in Python) follow.
