//! [`StudioProblem`] for the built-in problems a port may build, so that its `main` only has to
//! make the problem from the instance. Their neighbors and special heuristics follow
//! optopus-py's `build_tsp` and `build_job_shop`; encode matches the binding's solution shape.

use optopus::prelude::{Heuristic, LinKernighanHelsgaunForTsp, StopCondition};
use optopus::problem::{
    JobShopRelocateNeighbor, JobShopScheduling, JobShopSolution, JobShopSwapNeighbor, Tsp,
    TspRelocateNeighbor, TspSolution, TspTwoOptNeighbor,
};
use serde_json::{Map, Value, json};

use crate::StudioProblem;
use crate::factory::{NeighborVisitor, unknown_neighbor};

fn indices(value: &Value) -> Result<Vec<usize>, String> {
    value
        .as_array()
        .ok_or("a solution must be a list of indices")?
        .iter()
        .map(|v| {
            v.as_u64()
                .map(|n| n as usize)
                .ok_or("a solution must be a list of indices".into())
        })
        .collect()
}

impl StudioProblem for Tsp {
    const NAME: &'static str = "Tsp";

    fn higher_is_better(&self) -> bool {
        false
    }

    fn objective(solution: &TspSolution) -> f64 {
        solution.objective
    }

    fn encode(&self, solution: &TspSolution) -> Value {
        json!(solution.tour)
    }

    fn decode(&self, value: &Value) -> Result<TspSolution, String> {
        let tour = indices(value)?;
        let objective = self
            .calculate_tour_length(&tour)
            .map_err(|e| e.to_string())?;
        Ok(TspSolution { tour, objective })
    }

    fn with_neighbor<V: NeighborVisitor<Self>>(
        name: &str,
        visitor: V,
    ) -> Result<V::Output, String> {
        match name {
            "TwoOpt" => Ok(visitor.visit::<TspTwoOptNeighbor>()),
            "Relocate" => Ok(visitor.visit::<TspRelocateNeighbor>()),
            _ => Err(unknown_neighbor(name, &["TwoOpt", "Relocate"])),
        }
    }

    fn build_special(
        kind: &str,
        args: &Map<String, Value>,
        stop: StopCondition,
    ) -> Option<Result<Box<dyn Heuristic<Self>>, String>> {
        (kind == "LinKernighanHelsgaun").then(|| {
            let get = |key: &str, default: usize| {
                args.get(key).map_or(Ok(default), |v| {
                    v.as_u64()
                        .map(|n| n as usize)
                        .ok_or(format!("{kind}: {key:?} must be a count"))
                })
            };
            let heuristic: Box<dyn Heuristic<Self>> = Box::new(LinKernighanHelsgaunForTsp::new(
                stop,
                get("num_neighbors", 5)?,
                get("max_depth", 5)?,
            ));
            Ok(heuristic)
        })
    }
}

impl StudioProblem for JobShopScheduling {
    const NAME: &'static str = "JobShopScheduling";

    fn higher_is_better(&self) -> bool {
        false
    }

    fn objective(solution: &JobShopSolution) -> f64 {
        f64::from(solution.objective)
    }

    fn encode(&self, solution: &JobShopSolution) -> Value {
        json!(solution.operations)
    }

    fn decode(&self, value: &Value) -> Result<JobShopSolution, String> {
        let operations = indices(value)?;
        let (objective, completion_times) =
            JobShopScheduling::decode(self, &operations).map_err(|e| e.to_string())?;
        Ok(JobShopSolution {
            operations,
            objective,
            completion_times,
        })
    }

    fn with_neighbor<V: NeighborVisitor<Self>>(
        name: &str,
        visitor: V,
    ) -> Result<V::Output, String> {
        match name {
            "Swap" => Ok(visitor.visit::<JobShopSwapNeighbor>()),
            "Relocate" => Ok(visitor.visit::<JobShopRelocateNeighbor>()),
            _ => Err(unknown_neighbor(name, &["Swap", "Relocate"])),
        }
    }
}
