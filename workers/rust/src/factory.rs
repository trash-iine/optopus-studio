//! Heuristics from the JSON of `solve.json`, with optopus-py's argument names and defaults.
//!
//! A heuristic is `{"kind": <optopus-py class>, **constructor arguments}`; `stop` holds a
//! `StopCondition`'s arguments and a nested heuristic is another such object. The constructor
//! calls and argument orders follow optopus-py's `build_generic` and `build_nested`
//! (`src/runner.rs`), so a seeded run here takes the same path as the Python worker's.

use std::time::Duration;

use optopus::heuristic::{Iterated, ParallelTempering, PopulationAnnealing, Restart, Sequential};
use optopus::prelude::{
    BangBangSimulatedAnnealing, BeamSearch, EnabledTabu, Evaluate, Heuristic,
    LateAcceptanceHillClimbing, LocalSearch, MoveToNeighbor, RandomWalk, SimulatedAnnealing,
    StopCondition, TabuSearch, VariableNeighborhoodSearch,
};
use serde_json::{Map, Value};

use crate::StudioProblem;

/// What a move type needs to run under every generic heuristic.
pub trait Neighbor<P: StudioProblem>:
    MoveToNeighbor<P> + Evaluate + Clone + EnabledTabu + Send + Sync + 'static
{
}

impl<P, N> Neighbor<P> for N
where
    P: StudioProblem,
    N: MoveToNeighbor<P> + Evaluate + Clone + EnabledTabu + Send + Sync + 'static,
{
}

/// Receives the move type a `neighbor` name stands for, from [`StudioProblem::with_neighbor`].
pub trait NeighborVisitor<P: StudioProblem> {
    type Output;
    fn visit<N: Neighbor<P>>(self) -> Self::Output;
}

/// The error for a `neighbor` name a problem does not have.
pub fn unknown_neighbor(name: &str, valid: &[&str]) -> String {
    format!("unknown neighbor {name:?}; this problem has {valid:?}")
}

type Built<P> = Result<Box<dyn Heuristic<P>>, String>;

const GENERIC: &[(&str, &[&str])] = &[
    ("LocalSearch", &["neighbor", "stop"]),
    (
        "SimulatedAnnealing",
        &["neighbor", "initial_temperature", "cooling_rate", "stop"],
    ),
    (
        "BangBangSimulatedAnnealing",
        &[
            "neighbor",
            "initial_temperature",
            "cooling_rate",
            "min_wave_threshold",
            "max_wave_threshold",
            "stop",
        ],
    ),
    ("TabuSearch", &["neighbor", "tabu_tenure", "stop"]),
    (
        "LateAcceptanceHillClimbing",
        &["neighbor", "history_length", "stop"],
    ),
    ("RandomWalk", &["neighbor", "stop"]),
    ("BeamSearch", &["neighbor", "beam_width", "stop"]),
    (
        "PopulationAnnealing",
        &[
            "population_size",
            "stop",
            "initial_beta",
            "delta_beta",
            "sweeps_per_step",
            "reset_period",
            "neighbor",
            "sweep_length",
        ],
    ),
    (
        "ParallelTempering",
        &[
            "num_replicas",
            "stop",
            "beta_min",
            "beta_max",
            "sweeps_per_exchange",
            "neighbor",
            "sweep_length",
        ],
    ),
];

const NESTED: &[(&str, &[&str])] = &[
    ("Sequential", &["steps", "stop"]),
    ("Iterated", &["search", "perturbation", "stop"]),
    ("Restart", &["heuristic", "restart", "stop"]),
    ("VariableNeighborhoodSearch", &["search", "shakes", "stop"]),
];

/// Builds the heuristic `spec` describes for problem `P`.
pub fn build_heuristic<P: StudioProblem>(spec: &Value) -> Built<P> {
    let args = spec
        .as_object()
        .ok_or("a heuristic must be a JSON object")?;
    let kind = args
        .get("kind")
        .and_then(Value::as_str)
        .ok_or("a heuristic needs a \"kind\"")?;
    let stop = stop_condition(args.get("stop"))?;

    if let Some(allowed) = lookup(NESTED, kind) {
        check_keys(kind, args, allowed)?;
        return build_nested::<P>(kind, args, stop);
    }
    if let Some(built) = P::build_special(kind, args, stop.clone()) {
        return built;
    }
    let Some(allowed) = lookup(GENERIC, kind) else {
        let mut known: Vec<&str> = GENERIC.iter().chain(NESTED).map(|(k, _)| *k).collect();
        known.sort_unstable();
        return Err(format!(
            "unknown heuristic kind {kind:?}; this worker has {known:?}"
        ));
    };
    check_keys(kind, args, allowed)?;
    // optopus-py defaults the neighbor of the two replica methods to "Flip".
    let default = matches!(kind, "PopulationAnnealing" | "ParallelTempering").then_some("Flip");
    let neighbor = match args.get("neighbor") {
        Some(v) => v.as_str().ok_or("\"neighbor\" must be a string")?,
        None => default.ok_or_else(|| format!("{kind} needs a \"neighbor\""))?,
    };
    P::with_neighbor(neighbor, Generic { kind, args, stop })?
}

fn lookup<'a>(table: &'a [(&str, &'a [&str])], kind: &str) -> Option<&'a [&'a str]> {
    table
        .iter()
        .find(|(k, _)| *k == kind)
        .map(|(_, keys)| *keys)
}

fn check_keys(kind: &str, args: &Map<String, Value>, allowed: &[&str]) -> Result<(), String> {
    for key in args.keys().filter(|k| *k != "kind") {
        if !allowed.contains(&key.as_str()) {
            return Err(format!(
                "{kind} has no argument {key:?}; it takes {allowed:?}"
            ));
        }
    }
    Ok(())
}

fn build_nested<P: StudioProblem>(
    kind: &str,
    args: &Map<String, Value>,
    stop: StopCondition,
) -> Built<P> {
    let one = |key: &str| -> Built<P> {
        build_heuristic::<P>(
            args.get(key)
                .ok_or_else(|| format!("{kind} needs {key:?}"))?,
        )
    };
    let many = |key: &str| -> Result<Vec<Box<dyn Heuristic<P>>>, String> {
        args.get(key)
            .and_then(Value::as_array)
            .ok_or_else(|| format!("{kind} needs {key:?} as a list of heuristics"))?
            .iter()
            .map(build_heuristic::<P>)
            .collect()
    };
    Ok(match kind {
        "Sequential" => Box::new(Sequential::new(stop, many("steps")?)),
        "Iterated" => Box::new(Iterated::new(stop, one("search")?, one("perturbation")?)),
        "Restart" => Box::new(Restart::new(
            stop,
            one("heuristic")?,
            stop_condition(args.get("restart"))?,
        )),
        "VariableNeighborhoodSearch" => Box::new(VariableNeighborhoodSearch::new(
            stop,
            one("search")?,
            many("shakes")?,
        )),
        _ => unreachable!("NESTED lists {kind}"),
    })
}

struct Generic<'a> {
    kind: &'a str,
    args: &'a Map<String, Value>,
    stop: StopCondition,
}

impl<P: StudioProblem> NeighborVisitor<P> for Generic<'_> {
    type Output = Built<P>;

    fn visit<N: Neighbor<P>>(self) -> Built<P> {
        let Generic { kind, args, stop } = self;
        let a = Args { kind, args };
        Ok(match kind {
            "LocalSearch" => Box::new(LocalSearch::<N>::new(stop)),
            "SimulatedAnnealing" => Box::new(SimulatedAnnealing::<N>::new(
                stop,
                a.f64("initial_temperature")?,
                a.f64("cooling_rate")?,
            )),
            "BangBangSimulatedAnnealing" => Box::new(BangBangSimulatedAnnealing::<N>::new(
                stop,
                a.f64("initial_temperature")?,
                a.f64("cooling_rate")?,
                a.f64("min_wave_threshold")?,
                a.f64("max_wave_threshold")?,
            )),
            "TabuSearch" => Box::new(TabuSearch::<N>::new(stop, a.pair("tabu_tenure")?)),
            "LateAcceptanceHillClimbing" => Box::new(LateAcceptanceHillClimbing::<N>::new(
                stop,
                a.usize("history_length")?,
            )),
            "RandomWalk" => Box::new(RandomWalk::<N>::new(stop)),
            "BeamSearch" => Box::new(BeamSearch::<P, N>::new(stop, a.usize("beam_width")?)),
            "PopulationAnnealing" => {
                let pa = PopulationAnnealing::<P, N>::new(
                    stop,
                    a.usize("population_size")?,
                    a.f64_or("initial_beta", 0.1)?,
                    a.f64_or("delta_beta", 0.02)?,
                    a.usize_or("sweeps_per_step", 50)?,
                    // optopus-py: 0 disables resetting.
                    Some(a.usize_or("reset_period", 400)?).filter(|&n| n > 0),
                );
                match a.opt_usize("sweep_length")? {
                    Some(length) => Box::new(pa.with_sweep_length(length)),
                    None => Box::new(pa),
                }
            }
            "ParallelTempering" => {
                let pt = ParallelTempering::<P, N>::new(
                    stop,
                    a.usize("num_replicas")?,
                    a.f64_or("beta_min", 0.1)?,
                    a.f64_or("beta_max", 5.0)?,
                    a.usize_or("sweeps_per_exchange", 1)?,
                );
                match a.opt_usize("sweep_length")? {
                    Some(length) => Box::new(pt.with_sweep_length(length)),
                    None => Box::new(pt),
                }
            }
            _ => unreachable!("GENERIC lists {kind}"),
        })
    }
}

/// Typed access to a heuristic's arguments, with errors that name them.
struct Args<'a> {
    kind: &'a str,
    args: &'a Map<String, Value>,
}

impl Args<'_> {
    fn get(&self, key: &str) -> Result<&Value, String> {
        self.args
            .get(key)
            .ok_or_else(|| format!("{} needs {key:?}", self.kind))
    }

    fn f64(&self, key: &str) -> Result<f64, String> {
        number(self.kind, key, self.get(key)?)
    }

    fn f64_or(&self, key: &str, default: f64) -> Result<f64, String> {
        self.args
            .get(key)
            .map_or(Ok(default), |v| number(self.kind, key, v))
    }

    fn usize(&self, key: &str) -> Result<usize, String> {
        count(self.kind, key, self.get(key)?)
    }

    fn usize_or(&self, key: &str, default: usize) -> Result<usize, String> {
        self.args
            .get(key)
            .map_or(Ok(default), |v| count(self.kind, key, v))
    }

    fn opt_usize(&self, key: &str) -> Result<Option<usize>, String> {
        match self.args.get(key) {
            None | Some(Value::Null) => Ok(None),
            Some(v) => count(self.kind, key, v).map(Some),
        }
    }

    fn pair(&self, key: &str) -> Result<(u64, u64), String> {
        let bad = || format!("{}: {key:?} must be [min, max]", self.kind);
        let items = self.get(key)?.as_array().ok_or_else(bad)?;
        match items.as_slice() {
            [lo, hi] => Ok((lo.as_u64().ok_or_else(bad)?, hi.as_u64().ok_or_else(bad)?)),
            _ => Err(bad()),
        }
    }
}

fn number(kind: &str, key: &str, value: &Value) -> Result<f64, String> {
    value
        .as_f64()
        .ok_or_else(|| format!("{kind}: {key:?} must be a number"))
}

fn count(kind: &str, key: &str, value: &Value) -> Result<usize, String> {
    value
        .as_u64()
        .map(|n| n as usize)
        .ok_or_else(|| format!("{kind}: {key:?} must be a non-negative integer"))
}

/// A `StopCondition` from `{"max_iteration", "max_duration_secs", "max_failed_update"}`.
pub(crate) fn stop_condition(value: Option<&Value>) -> Result<StopCondition, String> {
    let empty = Map::new();
    let args = match value {
        None | Some(Value::Null) => &empty,
        Some(v) => v
            .as_object()
            .ok_or("a stop condition must be a JSON object")?,
    };
    check_keys(
        "stop",
        args,
        &["max_iteration", "max_duration_secs", "max_failed_update"],
    )?;
    let int = |key: &str| -> Result<Option<u64>, String> {
        args.get(key)
            .filter(|v| !v.is_null())
            .map(|v| {
                v.as_u64()
                    .ok_or_else(|| format!("stop: {key:?} must be a non-negative integer"))
            })
            .transpose()
    };
    let seconds = args
        .get("max_duration_secs")
        .filter(|v| !v.is_null())
        .map(|v| {
            v.as_f64()
                .filter(|s| s.is_finite() && *s >= 0.0)
                .ok_or("stop: \"max_duration_secs\" must be a non-negative number")
        })
        .transpose()?;
    Ok(StopCondition::new(
        int("max_iteration")?,
        seconds.map(Duration::from_secs_f64),
        int("max_failed_update")?,
    ))
}
