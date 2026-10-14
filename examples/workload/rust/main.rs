//! model.py in Rust: give every task to a worker who has its skill, so that the busiest worker
//! finishes earliest. Same solution, objective and Move neighborhood as the Python problem.

use optopus_studio_worker::prelude::*;

/// Spreading the load among the workers below the maximum gives the search a slope on the
/// plateaus a pure maximum has.
const SPREAD: f64 = 1e-3;

fn cost(loads: &[f64]) -> f64 {
    let max = loads.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    max + SPREAD * loads.iter().map(|l| l * l).sum::<f64>()
}

struct Workload {
    workers: usize,
    hours: Vec<f64>,
    eligible: Vec<Vec<usize>>,
    movable: Vec<usize>,
}

#[derive(Clone)]
struct Assignment {
    worker_of: Vec<usize>,
    loads: Vec<f64>,
    cost: f64,
}

impl Evaluate for Assignment {
    fn evaluate(&self) -> Evaluable<f64> {
        Evaluable::Minimize(self.cost)
    }
}

impl Workload {
    fn assignment(&self, worker_of: Vec<usize>) -> Assignment {
        let mut loads = vec![0.0; self.workers];
        for (task, &worker) in worker_of.iter().enumerate() {
            loads[worker] += self.hours[task];
        }
        let cost = cost(&loads);
        Assignment {
            worker_of,
            loads,
            cost,
        }
    }
}

impl ProblemTrait for Workload {
    type Solution = Assignment;

    fn new_solution(&self, rng: &mut impl Rng) -> Assignment {
        let worker_of = self
            .eligible
            .iter()
            .map(|e| e[rng.random_range(0..e.len())])
            .collect();
        self.assignment(worker_of)
    }
}

/// Give one task to another worker who has its skill.
#[derive(Clone)]
struct Move {
    task: usize,
    worker: usize,
    /// The cost after the move minus before.
    delta: f64,
}

impl Move {
    fn new(problem: &Workload, s: &Assignment, task: usize, worker: usize) -> Self {
        let mut loads = s.loads.clone();
        loads[s.worker_of[task]] -= problem.hours[task];
        loads[worker] += problem.hours[task];
        Move {
            task,
            worker,
            delta: cost(&loads) - s.cost,
        }
    }
}

impl Evaluate for Move {
    fn evaluate(&self) -> Evaluable<f64> {
        Evaluable::Minimize(self.delta)
    }
}

impl MoveToNeighbor<Workload> for Move {
    fn apply_to_solution(&self, problem: &Workload, s: &mut Assignment) -> Result<(), OptError> {
        let hours = problem.hours[self.task];
        s.loads[s.worker_of[self.task]] -= hours;
        s.loads[self.worker] += hours;
        s.worker_of[self.task] = self.worker;
        s.cost = cost(&s.loads);
        Ok(())
    }

    fn iter(problem: &Workload, s: &Assignment) -> impl Iterator<Item = Self> + Send {
        (0..problem.hours.len()).flat_map(move |task| {
            problem.eligible[task]
                .iter()
                .filter(move |&&w| w != s.worker_of[task])
                .map(move |&w| Move::new(problem, s, task, w))
        })
    }

    fn random_neighbor(problem: &Workload, s: &Assignment, rng: &mut SmallRng) -> Option<Self> {
        let &task = problem.movable.choose(rng)?;
        let others: Vec<usize> = problem.eligible[task]
            .iter()
            .copied()
            .filter(|&w| w != s.worker_of[task])
            .collect();
        let &worker = others.choose(rng)?;
        Some(Move::new(problem, s, task, worker))
    }

    fn tabu_policy(&self) -> Option<&dyn EnabledTabu> {
        Some(self)
    }

    fn move_to_be_better_than(&self, _: &Workload, src: &Assignment, other: &Assignment) -> bool {
        src.cost + self.delta < other.cost
    }
}

impl EnabledTabu for Move {
    /// Keyed on the task, as the Python tabu_keys is.
    fn is_move_enabled(&self, tabu: &TabuMemory, iteration: u64) -> bool {
        tabu.is_enabled(TabuKey::DenseVar(self.task), iteration)
    }

    fn add_to_tabu_map(&self, tabu: &mut TabuMemory, iteration: u64, rng: &mut SmallRng) {
        tabu.forbid(TabuKey::DenseVar(self.task), iteration, rng);
    }
}

impl StudioProblem for Workload {
    const NAME: &'static str = "Workload";

    fn higher_is_better(&self) -> bool {
        false
    }

    fn objective(s: &Assignment) -> f64 {
        s.cost
    }

    fn encode(&self, s: &Assignment) -> Value {
        json!({ "assignment": s.worker_of, "loads": s.loads })
    }

    fn decode(&self, value: &Value) -> Result<Assignment, String> {
        let worker_of = value["assignment"]
            .as_array()
            .ok_or("a solution needs \"assignment\"")?
            .iter()
            .map(|w| w.as_u64().map(|w| w as usize).filter(|&w| w < self.workers))
            .collect::<Option<Vec<usize>>>()
            .ok_or("\"assignment\" must list worker indices")?;
        if worker_of.len() != self.hours.len() {
            return Err("\"assignment\" needs one worker per task".into());
        }
        Ok(self.assignment(worker_of))
    }

    fn with_neighbor<V: NeighborVisitor<Self>>(
        name: &str,
        visitor: V,
    ) -> Result<V::Output, String> {
        match name {
            "Move" => Ok(visitor.visit::<Move>()),
            _ => Err(unknown_neighbor(name, &["Move"])),
        }
    }
}

fn build(instance: &Value) -> Result<Workload, String> {
    let workers = instance["workers"]
        .as_array()
        .ok_or("instance needs \"workers\"")?;
    let tasks = instance["tasks"]
        .as_array()
        .ok_or("instance needs \"tasks\"")?;
    let has_skill = |w: &Value, skill: &Value| {
        w["skills"]
            .as_array()
            .is_some_and(|skills| skills.contains(skill))
    };
    let mut hours = Vec::new();
    let mut eligible = Vec::new();
    for t in tasks {
        hours.push(
            t["hours"]
                .as_f64()
                .ok_or("a task needs numeric \"hours\"")?,
        );
        let e: Vec<usize> = (0..workers.len())
            .filter(|&i| has_skill(&workers[i], &t["skill"]))
            .collect();
        if e.is_empty() {
            return Err(format!("no worker has the skill for {}", t["name"]));
        }
        eligible.push(e);
    }
    let movable = (0..eligible.len())
        .filter(|&t| eligible[t].len() > 1)
        .collect();
    Ok(Workload {
        workers: workers.len(),
        hours,
        eligible,
        movable,
    })
}

fn main() -> std::process::ExitCode {
    serve(build)
}
