//! Supervisor del backend Python: lo arranca, le entrega el token por stdin, espera a que
//! responda y lo detiene al cerrar la app.

use serde::Serialize;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::AsyncWriteExt;
use tokio::process::{ChildStdin, Command};
use tokio::sync::oneshot;

use crate::proxy;

/// macOS limita la ruta de un Unix socket a 104 bytes (incluido el terminador).
const MAX_SOCKET_PATH: usize = 100;
pub const STATUS_EVENT: &str = "backend://status";

#[derive(Clone, Serialize, Debug, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum BackendStatus {
    Starting,
    Ready,
    Failed { message: String },
    Stopped,
}

pub struct Backend {
    pub socket: PathBuf,
    pub token: String,
    status: Mutex<BackendStatus>,
    stdin: Mutex<Option<ChildStdin>>,
    shutdown: Mutex<Option<oneshot::Sender<()>>>,
}

impl Backend {
    pub fn status(&self) -> BackendStatus {
        self.status.lock().expect("status lock").clone()
    }

    fn set_status(&self, app: &AppHandle, status: BackendStatus) {
        log::info!("backend: {status:?}");
        *self.status.lock().expect("status lock") = status.clone();
        let _ = app.emit(STATUS_EVENT, status);
    }

    /// Cierra stdin (el backend sale solo) y, si no lo hace en 3 s, lo mata.
    pub fn shutdown(&self) {
        self.stdin.lock().expect("stdin lock").take();
        if let Some(tx) = self.shutdown.lock().expect("shutdown lock").take() {
            let _ = tx.send(());
        }
    }
}

/// Token de sesión: 32 bytes del generador aleatorio del sistema, en hexadecimal.
fn new_token() -> std::io::Result<String> {
    let mut buf = [0u8; 32];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut buf)?;
    Ok(buf.iter().map(|b| format!("{b:02x}")).collect())
}

/// Cómo lanzar el backend: en desarrollo, el venv de `backend/`; empaquetado, el Python
/// embebido en los recursos de la app.
fn backend_command(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../backend");
        let python = dir.join(".venv/bin/python");
        if !python.exists() {
            return Err(format!(
                "No existe {} — ejecuta `uv sync` en backend/",
                python.display()
            ));
        }
        let mut cmd = Command::new(python);
        cmd.args(["-m", "app.main"]).current_dir(dir);
        Ok(cmd)
    } else {
        let res = app
            .path()
            .resource_dir()
            .map_err(|e| e.to_string())?
            .join("backend-runtime");
        let mut cmd = Command::new(res.join("python/bin/python3"));
        // -I: modo aislado (ignora variables PYTHON* y el directorio de usuario).
        cmd.arg("-I").arg(res.join("launch.py")).current_dir(&res);
        Ok(cmd)
    }
}

pub fn start(app: &AppHandle) -> Result<(), String> {
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let socket = data_dir.join("run").join("backend.sock");
    if socket.as_os_str().len() > MAX_SOCKET_PATH {
        return Err(format!(
            "Ruta del socket demasiado larga: {}",
            socket.display()
        ));
    }
    let logs = data_dir.join("logs");
    std::fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(logs.join("backend.log"))
        .map_err(|e| e.to_string())?;

    let token = new_token().map_err(|e| e.to_string())?;
    let mut cmd = backend_command(app)?;
    cmd.arg("--data-dir")
        .arg(&data_dir)
        .arg("--socket")
        .arg(&socket)
        .env_clear()
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin")
        .env("HOME", std::env::var("HOME").unwrap_or_default())
        .env("LANG", "es_ES.UTF-8")
        .stdin(Stdio::piped())
        .stdout(log_file.try_clone().map_err(|e| e.to_string())?)
        .stderr(log_file)
        .kill_on_drop(true);

    let (tx, rx) = oneshot::channel();
    app.manage(Backend {
        socket,
        token: token.clone(),
        status: Mutex::new(BackendStatus::Starting),
        stdin: Mutex::new(None),
        shutdown: Mutex::new(Some(tx)),
    });

    // Todo lo que usa tokio (procesos, sockets) se ejecuta dentro del runtime de Tauri.
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let backend = handle.state::<Backend>();
        let fail = |message: String| {
            backend.set_status(&handle, BackendStatus::Failed { message });
        };

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => return fail(format!("No se pudo iniciar el backend: {e}")),
        };
        // 1. Entregar el token (primera línea de stdin). stdin queda abierto: cuando la app
        //    lo cierra (o muere), el backend termina solo.
        let Some(mut stdin) = child.stdin.take() else {
            return fail("stdin del backend no disponible".into());
        };
        if stdin
            .write_all(format!("{token}\n").as_bytes())
            .await
            .and(stdin.flush().await)
            .is_err()
        {
            return fail("No se pudo entregar el token al backend".into());
        }
        *backend.stdin.lock().expect("stdin lock") = Some(stdin);

        // 2. Esperar a /health (máx. 30 s), vigilando que el proceso siga vivo.
        let mut ready = false;
        for _ in 0..150 {
            if let Ok(Some(code)) = child.try_wait() {
                backend.set_status(
                    &handle,
                    BackendStatus::Failed {
                        message: format!(
                            "El backend terminó al arrancar ({code}). Revisa logs/backend.log"
                        ),
                    },
                );
                return;
            }
            if let Ok(r) = proxy::send(
                &backend.socket,
                &backend.token,
                hyper::Method::GET,
                "/api/v1/health",
                None,
                false,
            )
            .await
                && r.status == 200
            {
                ready = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        if !ready {
            backend.set_status(
                &handle,
                BackendStatus::Failed {
                    message: "El backend no respondió en 30 s".into(),
                },
            );
            let _ = child.kill().await;
            return;
        }
        backend.set_status(&handle, BackendStatus::Ready);

        // 3. Vigilar hasta que termine o se pida apagarlo.
        tokio::select! {
            status = child.wait() => {
                let message = format!("El backend se detuvo inesperadamente ({status:?})");
                backend.set_status(&handle, BackendStatus::Failed { message });
            }
            _ = rx => {
                if tokio::time::timeout(Duration::from_secs(3), child.wait()).await.is_err() {
                    log::warn!("backend: no salió en 3 s, se fuerza la parada");
                    let _ = child.kill().await;
                }
                backend.set_status(&handle, BackendStatus::Stopped);
            }
        }
    });
    Ok(())
}
