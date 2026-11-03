# Instalación (desarrollo)

## Requisitos
| Herramienta | Instalación | Para qué |
|---|---|---|
| Homebrew | https://brew.sh | gestor de paquetes |
| Node ≥ 24 | `brew install node` | frontend |
| uv | `brew install uv` | Python 3.13 y dependencias del backend |
| Rust | `brew install rustup` + `rustup default stable` | Tauri |
| FFmpeg, whisper.cpp | `brew install ffmpeg whisper-cpp` | audio (Fase 3) |
| **Ollama (app oficial)** | `brew install --cask ollama-app` o ollama.com | LLM local (Fase 4) |

> ⚠️ **No uses `brew install ollama` (fórmula)**: la 0.40.14 de Homebrew no incluye `libollama_xgrammar.dylib` y devuelve `501 structured output is unavailable`, necesario para los exámenes.

`rustup` de Homebrew no se añade al PATH; añade a `~/.zshrc`:
```bash
export PATH="/opt/homebrew/opt/rustup/bin:$HOME/.cargo/bin:$PATH"
```

## Puesta en marcha
```bash
cd backend && uv sync            # crea .venv con Python 3.13
cd ../app && npm install
npm run tauri dev                # primera compilación de Rust: ~1 min
```
La app usa el puerto **1420** para Vite en desarrollo.

## Modelos (cuando lleguen las fases 3–5)
```bash
ollama pull qwen3.5:9b && ollama pull qwen3.5:4b && ollama pull qwen3-embedding:0.6b
```
Los modelos de whisper los gestionará la app (con verificación de SHA-256).

## Construir el .app (prueba de empaquetado)
```bash
scripts/build-backend-runtime.sh
cd app && npm run tauri build -- --config src-tauri/tauri.bundle.conf.json
# → app/src-tauri/target/release/bundle/macos/AI Study Assistant.app (~114 MB, firma ad-hoc)
```

## Desinstalar datos
Borra `~/Library/Application Support/com.aistudyassistant.desktop/` y `~/Library/Logs/com.aistudyassistant.desktop/`.
