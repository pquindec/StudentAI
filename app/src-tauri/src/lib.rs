mod backend;
mod grants;
mod proxy;
mod recorder;

use backend::{Backend, BackendStatus};
use grants::Grants;
use recorder::Recorder;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::Duration;
use tauri::{AppHandle, DragDropEvent, Emitter, Manager, RunEvent, State, WindowEvent};
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

/// Importa un archivo local llamando al endpoint interno (solo el núcleo puede hacerlo).
async fn core_import(
    backend: &Backend,
    body: serde_json::Value,
) -> Result<(u16, serde_json::Value), String> {
    let bytes = serde_json::to_vec(&body).map_err(|e| e.to_string())?;
    let res = proxy::send(
        &backend.socket,
        &backend.token,
        hyper::Method::POST,
        IMPORT_PATH,
        Some(bytes),
        true,
    )
    .await?;
    log::info!("import -> {}", res.status);
    Ok((res.status, parse_body(&res.body)?))
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
        let (status, body) = core_import(
            &backend,
            serde_json::json!({
                "path": path,
                "subject_id": request.subject_id,
                "unit_ids": request.unit_ids,
                "session_ids": request.session_ids,
            }),
        )
        .await?;
        results.push(ImportResult { path, status, body });
    }
    Ok(results)
}

/// Guarda un texto exportado (TXT/SRT) donde el usuario elija en el diálogo nativo.
/// Devuelve la ruta elegida o `None` si canceló.
#[tauri::command]
async fn save_text_file(
    app: AppHandle,
    default_name: String,
    content: String,
) -> Result<Option<String>, String> {
    if content.len() > 64 * 1024 * 1024 {
        return Err("El archivo es demasiado grande".into());
    }
    let name: String = default_name
        .chars()
        .filter(|c| !matches!(c, '/' | '\\' | ':' | '\0'))
        .take(120)
        .collect();
    let ext = name.rsplit('.').next().unwrap_or("txt").to_string();
    let (tx, rx) = oneshot::channel();
    app.dialog()
        .file()
        .set_title("Exportar")
        .set_file_name(&name)
        .add_filter("Texto", &[ext.as_str()])
        .save_file(move |p| {
            let _ = tx.send(p);
        });
    let Some(picked) = rx
        .await
        .map_err(|_| "El diálogo se cerró inesperadamente")?
    else {
        return Ok(None);
    };
    let path = picked.into_path().map_err(|_| "Ruta no válida")?;
    std::fs::write(&path, content).map_err(|e| format!("No se pudo guardar: {e}"))?;
    Ok(path.to_str().map(str::to_owned))
}

// ---------------------------------------------------------------- grabación

#[tauri::command]
fn list_input_devices() -> Result<Vec<recorder::InputDevice>, String> {
    recorder::list_devices()
}

#[tauri::command]
fn recording_status(recorder: State<'_, Recorder>) -> recorder::Status {
    recorder.status()
}

#[derive(Deserialize)]
struct StartRecording {
    device_id: Option<String>,
    target: recorder::Target,
}

fn set_recording_title(app: &AppHandle, recording: bool) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.set_title(if recording {
            "● Grabando — AI Study Assistant"
        } else {
            "AI Study Assistant"
        });
    }
}

#[tauri::command]
async fn start_recording(
    app: AppHandle,
    backend: State<'_, Backend>,
    recorder: State<'_, Recorder>,
    request: StartRecording,
) -> Result<recorder::Status, String> {
    ensure_ready(&backend)?;
    let t = &request.target;
    if t.title.trim().is_empty() || t.title.len() > 300 {
        return Err("Escribe un título para la grabación".into());
    }
    // Comprueba la asignatura antes de grabar (mejor fallar ahora que al terminar la clase).
    let path = format!("/api/v1/subjects/{}", t.subject_id);
    proxy::validate_path(&path).map_err(|_| "Asignatura no válida")?;
    let res = proxy::send(
        &backend.socket,
        &backend.token,
        hyper::Method::GET,
        &path,
        None,
        false,
    )
    .await?;
    if res.status != 200 {
        return Err("La asignatura elegida no existe".into());
    }
    let status = recorder.start(app.clone(), request.device_id, request.target)?;
    set_recording_title(&app, true);
    log::info!("grabación iniciada");
    Ok(status)
}

#[tauri::command]
fn pause_recording(
    recorder: State<'_, Recorder>,
    resume: bool,
) -> Result<recorder::Status, String> {
    recorder.pause(resume)
}

#[derive(Serialize)]
struct RecordingImport {
    recording_id: String,
    status: u16,
    body: serde_json::Value,
    warning: Option<String>,
}

/// Une los segmentos y los importa como fuente `recording`. Si todo va bien, borra la carpeta
/// temporal; si no, la grabación sigue disponible para recuperarla.
async fn import_recording(
    backend: &Backend,
    recorder: &Recorder,
    id: &str,
    warning: Option<String>,
) -> Result<RecordingImport, String> {
    let (dir, target, rate) = recorder.pending(id)?;
    let (wav, _ms) = tauri::async_runtime::spawn_blocking(move || recorder::concat(&dir, rate))
        .await
        .map_err(|e| e.to_string())??;
    let wav_str = wav.to_str().ok_or("Ruta no válida")?.to_string();
    let (status, body) = core_import(
        backend,
        serde_json::json!({
            "path": wav_str,
            "subject_id": target.subject_id,
            "unit_ids": target.unit_ids,
            "session_ids": target.session_ids,
            "kind": "recording",
            "title": target.title,
        }),
    )
    .await?;
    if status == 201 {
        recorder.discard(id)?;
    } else {
        let _ = std::fs::remove_file(wav);
    }
    Ok(RecordingImport {
        recording_id: id.to_string(),
        status,
        body,
        warning,
    })
}

#[tauri::command]
async fn stop_recording(
    app: AppHandle,
    backend: State<'_, Backend>,
    recorder: State<'_, Recorder>,
) -> Result<RecordingImport, String> {
    let stopped = recorder.stop();
    set_recording_title(&app, false);
    let _ = app.emit(recorder::STATUS_EVENT, recorder.status());
    let (id, warning) = stopped?;
    log::info!("grabación detenida");
    import_recording(&backend, &recorder, &id, warning).await
}

#[tauri::command]
fn list_recoverable_recordings(recorder: State<'_, Recorder>) -> Vec<recorder::Recoverable> {
    recorder.recoverable()
}

#[tauri::command]
async fn recover_recording(
    backend: State<'_, Backend>,
    recorder: State<'_, Recorder>,
    id: String,
) -> Result<RecordingImport, String> {
    ensure_ready(&backend)?;
    import_recording(&backend, &recorder, &id, None).await
}

#[tauri::command]
fn discard_recording(recorder: State<'_, Recorder>, id: String) -> Result<(), String> {
    recorder.discard(&id)
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
            let root = app.path().app_data_dir()?.join("recordings");
            app.manage(Recorder::new(root));
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
            import_files,
            save_text_file,
            list_input_devices,
            recording_status,
            start_recording,
            pause_recording,
            stop_recording,
            list_recoverable_recordings,
            recover_recording,
            discard_recording
        ])
        .build(tauri::generate_context!())
        .expect("error al construir la aplicación");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            // Cierra los archivos de una grabación en curso: quedará como recuperable.
            if let Some(recorder) = handle.try_state::<Recorder>() {
                recorder.shutdown();
            }
            if let Some(backend) = handle.try_state::<Backend>() {
                backend.shutdown();
            }
        }
    });
}
