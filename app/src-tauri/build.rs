fn main() {
    // Solo estos comandos propios existen para el frontend; cada uno necesita permiso
    // explícito en capabilities/default.json.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "api_request",
            "backend_status",
            "pick_files",
            "import_files",
            "save_text_file",
            "list_input_devices",
            "recording_status",
            "start_recording",
            "pause_recording",
            "stop_recording",
            "list_recoverable_recordings",
            "recover_recording",
            "discard_recording",
        ]),
    ))
    .expect("failed to run tauri-build");
}
