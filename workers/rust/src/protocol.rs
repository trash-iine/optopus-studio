//! The worker protocol, mirrored from `src/optopus_studio/protocol.py`.
//!
//! The Python models are the source; `tests/test_rust_worker.py` validates this side's output
//! against them.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Variant {
    pub label: String,
    pub heuristic: Value,
}

fn one() -> usize {
    1
}

fn zero() -> Option<u64> {
    Some(0)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SolveRequest {
    /// The Python worker's `model.py`; a Rust worker is the model, so it ignores this.
    #[serde(default)]
    pub model_path: Option<String>,
    pub instance: Value,
    pub variants: Vec<Variant>,
    #[serde(default = "one")]
    pub runs: usize,
    #[serde(default = "zero")]
    pub seed: Option<u64>,
}

#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WorkerEvent {
    Started {
        runs: usize,
        variants: Vec<String>,
        higher_is_better: bool,
        problem: String,
        /// Whether the search runs in compiled code; always so in a Rust worker.
        native: bool,
    },
    Progress {
        run: usize,
        variant: usize,
        elapsed_secs: f64,
        objective: f64,
    },
    RunFinished {
        run: usize,
        variant: usize,
        seed: Option<u64>,
        best_objective: f64,
        initial_objective: f64,
        solution: Value,
        trajectory: Vec<(f64, u64, f64)>,
        iterations: u64,
        best_iteration: u64,
        time_to_best_secs: f64,
        total_time_secs: f64,
        /// What a `BranchAndBound` run proved; the factory builds none, so always `None`.
        proven_optimal: Option<bool>,
        dual_bound: Option<f64>,
    },
    Done {
        best_run: usize,
        best_objective: f64,
    },
    Error {
        stage: &'static str,
        message: String,
        traceback: Option<String>,
    },
}

impl WorkerEvent {
    /// Writes the event as one JSON line on stdout.
    pub fn emit(&self) {
        use std::io::Write;
        let line = serde_json::to_string(self).expect("events serialize");
        let mut out = std::io::stdout().lock();
        // A closed pipe means the backend gave up on this solve; nothing is left to tell it.
        let _ = writeln!(out, "{line}").and_then(|()| out.flush());
    }
}
