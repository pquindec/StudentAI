mod backend;
mod grants;
mod proxy;

use backend::{Backend, BackendStatus};
use grants::Grants;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Duration;
use tauri::{AppHandle, DragDropEvent, Manager, RunEvent, State, WindowEvent};
use tauri_plugin_dialog::DialogExt;
use tokio::sync::oneshot;

/// Tamaño máximo del cuerpo JSON enviado desde la UI (los archivos van por `import_files`).
const MAX_REQUEST_BYTES: usize = 1024 * 1024;
const MAX_IMPORT_FILES: usize = 200;
const IMPORT_PATH: &str = "/api/v1/internal/sources/import-file";

/// Extensiones admitidas (deben coincidir con `backend/app/pipelines/files.py`).
const DOC_EXT: &[&str] = &["pdf", "docx", "txt", "md", "markdown", "rtf", "csv"];
const AUDIO_EXT: &[&str] = &[
    "mp3", "wav", "m4a", "aac", "flac", "ogg", "oga", "opus", "webm", "aiff", "aif", "wma", "m4b",
    "mp4",
];

#[derive(Deserialize)]
struct ApiRequest {
    method: String,
    path: String,
    body: Option<serde_json::Value>,
}

#[derive(Serialize)]
struct ApiResponse {
    status: u16,
    body: serde_json::Value,
}

fn ensure_ready(backend: &Backend) -> Result<(), String> {
    if backend.status() != BackendStatus::Ready {
        return Err("El servicio local aún no está listo".into());
    }
    Ok(())
}

fn parse_body(raw: &[u8]) -> Result<serde_json::Value, String> {
    if raw.is_empty() {
        Ok(serde_json::Value::Null)
    } else {
        serde_json::from_slice(raw).map_err(|_| "Respuesta no válida del backend".into())
    }
}

/// Único canal genérico entre la UI y el backend: valida la petición y la reenvía por el socket.
#[tauri::command]
async fn api_request(
    backend: State<'_, Backend>,
    request: ApiRequest,
) -> Result<ApiResponse, String> {
    ensure_ready(&backend)?;
    let method = proxy::parse_method(&request.method)?;
    proxy::validate_path(&request.path)?;
    let body = match request.body {
        Some(v) => {
            let bytes = serde_json::to_vec(&v).map_err(|e| e.to_string())?;
            if bytes.len() > MAX_REQUEST_BYTES {
                return Err("La petición es demasiado grande".into());
            }
            Some(bytes)
        }
        None => None,
    };
    let res = proxy::send(
        &backend.socket,
        &backend.token,
        method,
        &request.path,
        body,
        false,
    )
    .await?;
    log::info!("api {} {} -> {}", request.method, request.path, res.status);
    Ok(ApiResponse {
        status: res.status,
        body: parse_body(&res.body)?,
    })
}

#[tauri::command]
fn backend_status(backend: State<'_, Backend>) -> BackendStatus {
    backend.status()
}

/// Abre el selector nativo de archivos; las rutas elegidas quedan autorizadas para importarse.
#[tauri::command]
async fn pick_files(app: AppHandle, grants: State<'_, Grants>) -> Result<Vec<String>, String> {
    let all: Vec<&str> = DOC_EXT.iter().chain(AUDIO_EXT).copied().collect();
    let (tx, rx) = oneshot::channel();
    app.dialog()
        .file()
        .set_title("Importar materiales")
        .add_filter("Documentos y audio", &all)
        .add_filter("Documentos", DOC_EXT)
        .add_filter("Audio", AUDIO_EXT)
        .pick_files(move |picked| {
            let _ = tx.send(picked);
        });
    let picked = rx
        .await
        .map_err(|_| "El selector se cerró inesperadamente")?;
    let paths: Vec<PathBuf> = picked
        .unwrap_or_default()
        .into_iter()
        .filter_map(|f| f.into_path().ok())
        .collect();
    grants.add(paths.iter().cloned());
    Ok(paths
        .iter()
        .filter_map(|p| p.to_str().map(str::to_owned))
        .collect())
}

#[derive(Deserialize)]
struct ImportRequest {
    subject_id: String,
    #[serde(default)]
    unit_ids: Vec<String>,
    #[serde(default)]
    session_ids: Vec<String>,
    paths: Vec<String>,
}

#[derive(Serialize)]
struct ImportResult {
    path: String,
    status: u16,
    body: serde_json::Value,
}

/// Espera un momento por si el evento de arrastrar y soltar llega a la UI antes que al núcleo.
async fn wait_grant(grants: &Grants, path: &std::path::Path) -> bool {
    for _ in 0..20 {
        if grants.take(path) {
            return true;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    false
}

/// Importa archivos elegidos por el usuario. Solo acepta rutas autorizadas en `Grants`.
#[tauri::command]
async fn import_files(
    backend: State<'_, Backend>,
    grants: State<'_, Grants>,
    request: ImportRequest,
) -> Result<Vec<ImportResult>, String> {
    ensure_ready(&backend)?;
    if request.paths.len() > MAX_IMPORT_FILES {
        return Err(format!(
            "Puedes importar como máximo {MAX_IMPORT_FILES} archivos a la vez"
        ));
    }
    let mut results = Vec::with_capacity(request.paths.len());
    for path in request.paths {
        if !wait_grant(&grants, std::path::Path::new(&path)).await {
            log::warn!("import rechazado: ruta no autorizada");
            results.push(ImportResult {
                path,
                status: 403,
                body: serde_json::json!({"error": {
                    "code": "not_allowed",
                    "message": "Vuelve a seleccionar el archivo para importarlo",
                }}),
            });
            continue;
        }
        let body = serde_json::to_vec(&serde_json::json!({
            "path": path,
            "subject_id": request.subject_id,
            "unit_ids": request.unit_ids,
            "session_ids": request.session_ids,
        }))
        .map_err(|e| e.to_string())?;
        let res = proxy::send(
            &backend.socket,
            &backend.token,
            hyper::Method::POST,
            IMPORT_PATH,
            Some(body),
            true,
        )
        .await?;
        log::info!("import -> {}", res.status);
        results.push(ImportResult {
            path,
            status: res.status,
            body: parse_body(&res.body)?,
        });
    }
    Ok(results)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_dialog::init())
        .manage(Grants::default())
        .setup(|app| {
            backend::start(app.handle()).map_err(|e| {
                log::error!("No se pudo iniciar el backend: {e}");
                e
            })?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Soltar archivos sobre la ventana es un gesto explícito del usuario: autoriza esas rutas.
            if let WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) = event {
                window.state::<Grants>().add(paths.iter().cloned());
            }
        })
        .invoke_handler(tauri::generate_handler![
            api_request,
            backend_status,
            pick_files,
            import_files
        ])
        .build(tauri::generate_context!())
        .expect("error al construir la aplicación");

    app.run(|handle, event| {
        if let RunEvent::Exit = event
            && let Some(backend) = handle.try_state::<Backend>()
        {
            backend.shutdown();
        }
    });
}
