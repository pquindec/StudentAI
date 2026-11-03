fn main() {
    // Solo estos comandos propios existen para el frontend; cada uno necesita permiso
    // explícito en capabilities/default.json.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["api_request", "backend_status"]),
    ))
    .expect("failed to run tauri-build");
}
