use optimizer_core::{solve_best_loadout, BestLoadoutRequest};
use serde::Serialize;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

#[derive(Serialize)]
struct WorkerCapabilities {
    schema_version: u8,
    engine_id: &'static str,
    best_loadout_ready: bool,
    action_ev_ready: bool,
    exact_semantics: bool,
}

fn argument_value(args: &[String], name: &str) -> Result<PathBuf, String> {
    let index = args
        .iter()
        .position(|value| value == name)
        .ok_or_else(|| format!("missing argument: {name}"))?;
    args.get(index + 1)
        .map(PathBuf::from)
        .ok_or_else(|| format!("missing value for argument: {name}"))
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    serde_json::from_str(&text).map_err(|error| error.to_string())
}

fn write_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|error| error.to_string())?;
    fs::write(path, format!("{text}\n")).map_err(|error| error.to_string())
}

fn run_best_loadout(args: &[String]) -> Result<(), String> {
    let input = argument_value(args, "--input")?;
    let output = argument_value(args, "--output")?;
    let request: BestLoadoutRequest =
        serde_json::from_value(read_json(&input)?).map_err(|error| error.to_string())?;
    let result = solve_best_loadout(&request).map_err(|error| error.to_string())?;
    write_json(&output, &result)
}

fn reject_action_ev(args: &[String]) -> Result<(), String> {
    let input = argument_value(args, "--input")?;
    let error_path = argument_value(args, "--error")?;
    let request = read_json(&input)?;
    let run_id = request
        .get("run_id")
        .and_then(Value::as_str)
        .unwrap_or("rust-worker-request");
    write_json(
        &error_path,
        &json!({
            "schema_version": 1,
            "run_id": run_id,
            "status": "error",
            "engine": "rust_v0",
            "execution_mode": "worker_process",
            "error_type": "EngineNotReady",
            "message": "Rust Action EV engine is not enabled until cross-engine parity and benchmark gates pass.",
            "traceback": "",
            "finished_at": ""
        }),
    )?;
    Err("Rust Action EV engine is not ready".to_string())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.len() == 1 && args[0] == "--capabilities" {
        println!(
            "{}",
            serde_json::to_string_pretty(&WorkerCapabilities {
                schema_version: 1,
                engine_id: "rust_v0",
                best_loadout_ready: true,
                action_ev_ready: false,
                exact_semantics: true,
            })
            .expect("serialize capabilities")
        );
        return ExitCode::SUCCESS;
    }
    let result = match args.first().map(String::as_str) {
        Some("best-loadout") => run_best_loadout(&args[1..]),
        Some("action-ev") => reject_action_ev(&args[1..]),
        _ => Err(
            "usage: optimizer-worker --capabilities | best-loadout --input PATH --output PATH | action-ev --input PATH --error PATH"
                .to_string(),
        ),
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::from(2)
        }
    }
}
