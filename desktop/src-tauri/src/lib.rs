use serde_json::Value;
use std::env;
use std::io::{BufRead, BufReader, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use thiserror::Error;

#[derive(Debug, Error)]
enum BackendClientError {
    #[error("无法启动 Python 后端：{0}")]
    Spawn(#[source] std::io::Error),
    #[error("后端输入流不可用")]
    MissingStdin,
    #[error("后端输出流不可用")]
    MissingStdout,
    #[error("向后端发送请求失败：{0}")]
    Write(#[source] std::io::Error),
    #[error("读取后端响应失败：{0}")]
    Read(#[source] std::io::Error),
    #[error("后端在返回响应前退出")]
    UnexpectedExit,
    #[error("后端返回了无效 JSON：{0}")]
    InvalidJson(#[source] serde_json::Error),
}

#[derive(Clone)]
struct BackendConfig {
    project_root: PathBuf,
    resource_dir: Option<PathBuf>,
    uses_bundled_resources: bool,
    python_executable: PathBuf,
    packaged_backend: Option<PathBuf>,
    packaged_action_worker: Option<PathBuf>,
}

impl BackendConfig {
    fn from_app(app: &AppHandle) -> Self {
        let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let development_project_root = env::var_os("GEAR_OPTIMIZER_PROJECT_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                manifest_dir
                    .parent()
                    .and_then(Path::parent)
                    .map(Path::to_path_buf)
                    .unwrap_or(manifest_dir)
            });
        let python_executable = env::var_os("GEAR_OPTIMIZER_PYTHON")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("python"));
        let resource_dir = app.path().resource_dir().ok();
        let explicit_backend = env::var_os("GEAR_OPTIMIZER_BACKEND").map(PathBuf::from);
        let bundled_backend = resource_dir.as_ref().and_then(|directory| {
            let candidate = directory.join(if cfg!(windows) {
                "gear-optimizer-backend.exe"
            } else {
                "gear-optimizer-backend"
            });
            candidate.exists().then_some(candidate)
        });
        let uses_bundled_resources = explicit_backend.is_none() && bundled_backend.is_some();
        let packaged_backend = explicit_backend.or(bundled_backend);
        let packaged_action_worker = uses_bundled_resources.then(|| {
            resource_dir
                .as_ref()
                .expect("bundled backend requires a resource directory")
                .join(if cfg!(windows) {
                    "gear-optimizer-action-worker.exe"
                } else {
                    "gear-optimizer-action-worker"
                })
        });
        let project_root = if uses_bundled_resources {
            resource_dir
                .clone()
                .unwrap_or_else(|| development_project_root.clone())
        } else {
            development_project_root
        };
        Self {
            project_root,
            resource_dir,
            uses_bundled_resources,
            python_executable,
            packaged_backend,
            packaged_action_worker,
        }
    }

    fn command(&self) -> Command {
        if let Some(path) = &self.packaged_backend {
            let mut command = Command::new(path);
            if self.uses_bundled_resources {
                let resource_dir = self
                    .resource_dir
                    .as_ref()
                    .expect("bundled backend requires a resource directory");
                command.current_dir(resource_dir);
                command.env("GEAR_OPTIMIZER_PROJECT_ROOT", resource_dir);
            }
            if let Some(action_worker) = &self.packaged_action_worker {
                command.env("GEAR_OPTIMIZER_ACTION_WORKER", action_worker);
            }
            return command;
        }
        let mut command = Command::new(&self.python_executable);
        command.args(["-m", "gear_optimizer.desktop_backend"]);
        command.current_dir(&self.project_root);
        let source_path = self.project_root.join("src");
        let python_path = match env::var_os("PYTHONPATH") {
            Some(existing) => {
                let mut paths = vec![source_path];
                paths.extend(env::split_paths(&existing));
                env::join_paths(paths).unwrap_or(existing)
            }
            None => source_path.into_os_string(),
        };
        command.env("PYTHONPATH", python_path);
        command
    }
}

struct BackendClient {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl BackendClient {
    fn spawn(config: &BackendConfig) -> Result<Self, BackendClientError> {
        let mut command = config.command();
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(BackendClientError::Spawn)?;
        let stdin = child.stdin.take().ok_or(BackendClientError::MissingStdin)?;
        let stdout = child
            .stdout
            .take()
            .ok_or(BackendClientError::MissingStdout)?;
        Ok(Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
        })
    }

    fn request(&mut self, request: &Value) -> Result<Value, BackendClientError> {
        serde_json::to_writer(&mut self.stdin, request).map_err(BackendClientError::InvalidJson)?;
        self.stdin
            .write_all(b"\n")
            .map_err(BackendClientError::Write)?;
        self.stdin.flush().map_err(BackendClientError::Write)?;

        let mut response = String::new();
        self.stdout
            .read_line(&mut response)
            .map_err(BackendClientError::Read)?;
        if response.is_empty() {
            return Err(BackendClientError::UnexpectedExit);
        }
        serde_json::from_str(&response).map_err(BackendClientError::InvalidJson)
    }

    fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for BackendClient {
    fn drop(&mut self) {
        self.stop();
    }
}

struct BackendState {
    config: BackendConfig,
    client: Mutex<Option<BackendClient>>,
}

impl BackendState {
    fn new(app: &AppHandle) -> Self {
        Self {
            config: BackendConfig::from_app(app),
            client: Mutex::new(None),
        }
    }
}

#[tauri::command]
fn backend_request(request: Value, state: State<'_, BackendState>) -> Result<Value, String> {
    let mut guard = state
        .client
        .lock()
        .map_err(|_| "后端进程锁已损坏，请重启应用。".to_string())?;
    if guard.is_none() {
        *guard = Some(BackendClient::spawn(&state.config).map_err(|error| error.to_string())?);
    }
    let result = guard
        .as_mut()
        .expect("backend client initialized")
        .request(&request);
    if result.is_err() {
        if let Some(client) = guard.as_mut() {
            client.stop();
        }
        *guard = None;
    }
    result.map_err(|error| error.to_string())
}

#[tauri::command]
fn backend_restart(state: State<'_, BackendState>) -> Result<(), String> {
    let mut guard = state
        .client
        .lock()
        .map_err(|_| "后端进程锁已损坏，请重启应用。".to_string())?;
    if let Some(client) = guard.as_mut() {
        client.stop();
    }
    *guard = None;
    Ok(())
}

fn safe_relative_path(value: &str) -> Result<PathBuf, String> {
    let path = Path::new(value);
    if path.as_os_str().is_empty()
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("资源路径必须是仓库内的相对路径。".to_string());
    }
    Ok(path.to_path_buf())
}

#[tauri::command]
fn resolve_asset_path(
    relative_path: String,
    state: State<'_, BackendState>,
) -> Result<String, String> {
    let relative = safe_relative_path(&relative_path)?;
    let mut roots = vec![state.config.project_root.as_path()];
    if let Some(resource_dir) = state.config.resource_dir.as_deref() {
        roots.push(resource_dir);
    }
    for root in roots {
        let candidate = root.join(&relative);
        if candidate.is_file() {
            return Ok(candidate.to_string_lossy().into_owned());
        }
    }
    Err(format!("资源不存在：{relative_path}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(BackendState::new(app.handle()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_request,
            backend_restart,
            resolve_asset_path
        ])
        .run(tauri::generate_context!())
        .expect("error while running BOX gear optimizer desktop application");
}

#[cfg(test)]
mod tests {
    use super::safe_relative_path;

    #[test]
    fn asset_paths_must_stay_inside_resources() {
        assert!(safe_relative_path("assets/zzz/agents/icons/test.png").is_ok());
        assert!(safe_relative_path("../secret.txt").is_err());
        assert!(safe_relative_path("C:/secret.txt").is_err());
    }
}
