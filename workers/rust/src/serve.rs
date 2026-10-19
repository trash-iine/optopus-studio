//! The worker's `main`: one solve per process, or evaluating solutions with `--evaluate`.
//!
//! The run loop is optopus-py's `run_all` (`src/runner.rs`) and the Python worker's `solve`
//! (`src/optopus_studio/worker.py`): the same per-run seeds, a fresh heuristic per run, the
//! same probe-recorded trajectory. A seeded run of a built-in problem under an iteration limit
//! therefore reproduces the Python worker's run exactly.

use std::io::BufRead;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::process::ExitCode;
use std::time::Instant;

use optopus::prelude::{Heuristic, SearchState};
use optopus::search_state::TrajectoryPoint;
use serde_json::{Value, json};

use crate::StudioProblem;
use crate::factory::build_heuristic;
use crate::live;
use crate::protocol::{SolveRequest, WorkerEvent};

/// The seed of run `run_index`, as optopus-py derives it. Run 0 uses the master seed.
pub fn derive_seed(master: u64, run_index: usize) -> u64 {
    master.wrapping_add((run_index as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15))
}

/// Runs the worker: reads one request on stdin and answers on stdout.
///
/// `build` makes the problem from `instance.json`, as `model.py`'s `build` does.
pub fn serve<P: StudioProblem>(build: impl Fn(&Value) -> Result<P, String>) -> ExitCode {
    let mut line = String::new();
    if let Err(e) = std::io::stdin().lock().read_line(&mut line) {
        fail("request", format!("cannot read stdin: {e}"));
        return ExitCode::from(2);
    }
    if std::env::args().any(|a| a == "--evaluate") {
        return evaluate(&line, build);
    }
    let request: SolveRequest = match serde_json::from_str(&line) {
        Ok(r) => r,
        Err(e) => {
            fail("request", e.to_string());
            return ExitCode::from(2);
        }
    };
    if request.variants.is_empty() || request.runs == 0 {
        fail(
            "request",
            "a solve needs at least one variant and one run".into(),
        );
        return ExitCode::from(2);
    }
    match solve(&request, build) {
        Ok(()) => ExitCode::SUCCESS,
        Err((stage, message)) => {
            fail(stage, message);
            ExitCode::FAILURE
        }
    }
}

fn fail(stage: &'static str, message: String) {
    WorkerEvent::Error {
        stage,
        message,
        traceback: None,
    }
    .emit();
}

/// Runs `f`, turning a panic into an error message.
fn guarded<T>(f: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(result) => result,
        Err(panic) => Err(panic
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| panic.downcast_ref::<&str>().map(|s| s.to_string()))
            .map_or_else(|| "panicked".to_string(), |m| format!("panicked: {m}"))),
    }
}

fn probe<P: StudioProblem>(solution: &P::Solution) -> f64 {
    let objective = P::objective(solution);
    live::improved(objective);
    objective
}

type Failure = (&'static str, String);

fn solve<P: StudioProblem>(
    request: &SolveRequest,
    build: impl Fn(&Value) -> Result<P, String>,
) -> Result<(), Failure> {
    let problem = guarded(|| build(&request.instance)).map_err(|e| ("build", e))?;
    let higher = problem.higher_is_better();
    // Build every variant once up front, so a bad one fails before any run.
    for variant in &request.variants {
        build_heuristic::<P>(&variant.heuristic)
            .map_err(|e| ("heuristic", format!("{}: {e}", variant.label)))?;
    }
    WorkerEvent::Started {
        runs: request.runs,
        variants: request.variants.iter().map(|v| v.label.clone()).collect(),
        higher_is_better: higher,
        problem: P::NAME.to_string(),
        native: true,
    }
    .emit();

    let mut best: Option<(usize, f64)> = None;
    let mut index = 0;
    for (variant_index, variant) in request.variants.iter().enumerate() {
        for run_index in 0..request.runs {
            let seed = request.seed.map(|m| derive_seed(m, run_index));
            let mut heuristic =
                build_heuristic::<P>(&variant.heuristic).map_err(|e| ("heuristic", e))?;
            let event = guarded(|| {
                run_once(
                    &problem,
                    heuristic.as_mut(),
                    index,
                    variant_index,
                    seed,
                    higher,
                )
            })
            .map_err(|e| ("run", e))?;
            if let WorkerEvent::RunFinished { best_objective, .. } = &event {
                let better = best.is_none_or(|(_, b)| {
                    if higher {
                        *best_objective > b
                    } else {
                        *best_objective < b
                    }
                });
                if better {
                    best = Some((index, *best_objective));
                }
            }
            event.emit();
            index += 1;
        }
    }
    let (best_run, best_objective) = best.expect("at least one run");
    WorkerEvent::Done {
        best_run,
        best_objective,
    }
    .emit();
    Ok(())
}

fn run_once<P: StudioProblem>(
    problem: &P,
    heuristic: &mut dyn Heuristic<P>,
    run: usize,
    variant: usize,
    seed: Option<u64>,
    higher: bool,
) -> Result<WorkerEvent, String> {
    let start = Instant::now();
    let mut state = match seed {
        Some(s) => SearchState::new_with_seed(problem, s),
        None => SearchState::new(problem),
    };
    state.set_objective_probe(probe::<P>);
    let initial_objective = P::objective(&state.initial_solution);
    // A run the heuristic cannot continue fails the solve, as optopus-py raises it from `run`.
    live::watch(run, variant, start, higher, || heuristic.run(&mut state))
        .map_err(|e| e.to_string())?;
    let total_time = start.elapsed();
    Ok(WorkerEvent::RunFinished {
        run,
        variant,
        seed,
        best_objective: P::objective(&state.best_solution),
        initial_objective,
        solution: problem.encode(&state.best_solution),
        trajectory: monotone(&state.trajectory, start, higher),
        iterations: state.iteration,
        best_iteration: state.best_iteration,
        time_to_best_secs: state
            .best_time
            .saturating_duration_since(start)
            .as_secs_f64(),
        total_time_secs: total_time.as_secs_f64(),
        proven_optimal: None,
        dual_bound: None,
    })
}

/// The improvements as `(elapsed_secs, iteration, objective)`, keeping only those better than
/// the one before, as optopus-py's `monotone_trajectory` does.
fn monotone(points: &[TrajectoryPoint], start: Instant, higher: bool) -> Vec<(f64, u64, f64)> {
    let mut out: Vec<(f64, u64, f64)> = Vec::with_capacity(points.len());
    for p in points {
        let improves = out.last().is_none_or(|&(_, _, incumbent)| {
            if higher {
                p.objective > incumbent
            } else {
                p.objective < incumbent
            }
        });
        if improves {
            let elapsed = p.instant.saturating_duration_since(start).as_secs_f64();
            out.push((elapsed, p.iteration, p.objective));
        }
    }
    out
}

/// `--evaluate`: reads `{"instance", "solutions"}` and writes `{"objectives"}`, or `{"error"}`.
fn evaluate<P: StudioProblem>(line: &str, build: impl Fn(&Value) -> Result<P, String>) -> ExitCode {
    let answer = guarded(|| {
        let input: Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
        let problem = build(&input["instance"])?;
        let solutions = input["solutions"]
            .as_array()
            .ok_or("\"solutions\" must be a list")?;
        let objectives = solutions
            .iter()
            .map(|s| problem.decode(s).map(|solution| P::objective(&solution)))
            .collect::<Result<Vec<f64>, String>>()?;
        Ok(json!({ "objectives": objectives }))
    });
    let ok = answer.is_ok();
    let value = answer.unwrap_or_else(|e| json!({ "error": e }));
    println!("{value}");
    if ok {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}
