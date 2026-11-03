mod backend;
mod proxy;

use backend::{Backend, BackendStatus};
use serde::{Deserialize, Serialize};
use tauri::{Manager, RunEvent, State};

/// Tamaño máximo del cuerpo JSON enviado desde la UI (los archivos irán por otra vía).
const MAX_REQUEST_BYTES: usize = 1024 * 1024;

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

/// Único canal entre la UI y el backend: valida la petición y la reenvía por el socket.
#[tauri::command]
async fn api_request(
    backend: State<'_, Backend>,
    request: ApiRequest,
) -> Result<ApiResponse, String> {
    if backend.status() != BackendStatus::Ready {
        return Err("El servicio local aún no está listo".into());
    }
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
    let res = proxy::send(&backend.socket, &backend.token, method, &request.path, body).await?;
    log::info!("api {} {} -> {}", request.method, request.path, res.status);
    let body = if res.body.is_empty() {
        serde_json::Value::Null
    } else {
        serde_json::from_slice(&res.body).map_err(|_| "Respuesta no válida del backend")?
    };
    Ok(ApiResponse {
        status: res.status,
        body,
    })
}

#[tauri::command]
fn backend_status(backend: State<'_, Backend>) -> BackendStatus {
    backend.status()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            backend::start(app.handle()).map_err(|e| {
                log::error!("No se pudo iniciar el backend: {e}");
                e
            })?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![api_request, backend_status])
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
