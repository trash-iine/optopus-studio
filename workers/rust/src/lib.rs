//! The Rust side of optopus studio's worker protocol.
//!
//! A project's model, ported to Rust, implements [`StudioProblem`] and calls [`serve`] from
//! `main`. The binary then reads a `SolveRequest` on stdin and writes `WorkerEvent`s on stdout
//! exactly as the Python worker does (`src/optopus_studio/protocol.py`), so the backend and the
//! GUI cannot tell the two apart. Heuristics are built at run time from the request's JSON, with
//! the parameters and defaults of optopus-py, so changing `solve.json` needs no rebuild.

mod builtins;
mod factory;
mod live;
mod protocol;
mod serve;

pub use factory::{Neighbor, NeighborVisitor, build_heuristic, unknown_neighbor};
pub use protocol::{SolveRequest, Variant, WorkerEvent};
pub use serve::{derive_seed, serve};
pub use {optopus, serde_json};

/// Everything a port usually needs, in one `use optopus_studio_worker::prelude::*;`.
pub mod prelude {
    pub use crate::{Neighbor, NeighborVisitor, StudioProblem, serve, unknown_neighbor};
    pub use optopus::building_blocks::search::{TabuKey, TabuMemory};
    pub use optopus::error::OptError;
    pub use optopus::prelude::*;
    pub use optopus::rand::{self, Rng, rngs::SmallRng, seq::IndexedRandom};
    pub use serde_json::{Map, Value, json};
}

use optopus::prelude::{Evaluate, Heuristic, ProblemTrait, StopCondition};
use serde_json::{Map, Value};

/// A problem the studio can solve: a ported `model.py`.
pub trait StudioProblem: ProblemTrait<Solution: Evaluate> + Sized + Sync + 'static {
    /// The class name the GUI shows, as `type(problem).__name__` would be in Python.
    const NAME: &'static str;

    /// Whether [`objective`](Self::objective) ranks higher values first.
    fn higher_is_better(&self) -> bool;

    /// The objective reported for a solution, on the scale `model.py`'s problem reports it.
    fn objective(solution: &Self::Solution) -> f64;

    /// The solution as JSON, exactly as `model.py`'s `encode_solution` writes it, so the
    /// project's `view.py` reads both workers' results alike.
    fn encode(&self, solution: &Self::Solution) -> Value;

    /// The inverse of [`encode`](Self::encode). The studio checks a port by evaluating the
    /// Python worker's solutions with it.
    fn decode(&self, value: &Value) -> Result<Self::Solution, String>;

    /// Calls `visitor` with the move type a `neighbor` name stands for. A problem with one
    /// neighborhood is
    ///
    /// ```ignore
    /// match name {
    ///     "Move" => Ok(visitor.visit::<MoveTask>()),
    ///     _ => Err(unknown_neighbor(name, &["Move"])),
    /// }
    /// ```
    fn with_neighbor<V: NeighborVisitor<Self>>(name: &str, visitor: V)
    -> Result<V::Output, String>;

    /// A heuristic only this problem has (e.g. `LinKernighanHelsgaun` for a tour), or `None`
    /// to let the generic factory try `kind`.
    fn build_special(
        _kind: &str,
        _args: &Map<String, Value>,
        _stop: StopCondition,
    ) -> Option<Result<Box<dyn Heuristic<Self>>, String>> {
        None
    }
}
