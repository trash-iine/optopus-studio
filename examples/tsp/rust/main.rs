//! model.py in Rust: a tour through every city, on the built-in Tsp.

use optopus_studio_worker::optopus::problem::Tsp;
use optopus_studio_worker::prelude::*;

fn build(instance: &Value) -> Result<Tsp, String> {
    let cities = instance["cities"]
        .as_array()
        .ok_or("instance needs \"cities\"")?;
    let points = cities
        .iter()
        .map(|c| match (c["x"].as_f64(), c["y"].as_f64()) {
            (Some(x), Some(y)) => Ok((x, y)),
            _ => Err(format!("a city needs numeric x and y: {c}")),
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(Tsp::new(String::new(), points))
}

fn main() -> std::process::ExitCode {
    serve(build)
}
