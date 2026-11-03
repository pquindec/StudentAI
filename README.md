# AI Study Assistant

> Una aplicación para tomar, grabar y generar notas para poder realizar exámenes.

Asistente de estudio para macOS (Apple Silicon): graba o importa clases y documentos, los convierte en conocimiento estructurado y genera apuntes, resúmenes, exámenes y flashcards **fundamentados solo en tus fuentes**. La IA se ejecuta en local por defecto; la nube es opcional y siempre con consentimiento.

> Estado: **Fase 1 completada** (estructura y entorno). Ver `TASKS.md`.

## Arquitectura en una línea
Tauri 2 (Rust) + React/TypeScript → proxy Rust → **FastAPI en Unix socket privado** → SQLite · whisper.cpp · Ollama. Detalle en `ARCHITECTURE.md`.

## Estructura
```
app/            Frontend React + Tauri (src-tauri/ = núcleo Rust)
backend/        API FastAPI (Python 3.13, uv)
bench/          Benchmarks de modelos (Fase 0.5)
scripts/        check.sh (todas las pruebas) · build-backend-runtime.sh (empaquetado)
```

## Empezar
Ver `INSTALLATION.md`. Resumen:
```bash
cd backend && uv sync            # backend
cd ../app && npm install         # frontend
npm run tauri dev                # abre la app
../scripts/check.sh              # lint + tipos + pruebas
```

## Documentación
| Archivo | Contenido |
|---|---|
| `ARCHITECTURE.md` | Decisiones (ADR), procesos, modelo de datos, flujos, memoria, riesgos |
| `BENCHMARKS.md` | Medidas reales de modelos en el Mac M5 24 GB |
| `TASKS.md` | Plan por fases y estado |
| `INSTALLATION.md` | Requisitos e instalación |
| `API_DOCUMENTATION.md` | Contrato UI ↔ backend |
| `DATABASE.md` | Reglas de la base de datos y migraciones |
| `SECURITY.md` · `THREAT_MODEL.md` | Controles de seguridad y amenazas |
| `TESTING.md` | Estrategia y comandos de prueba |
| `CHANGELOG.md` | Historial de cambios |
| `CLAUDE.md` · `PROJECT_CONTEXT.md` | Instrucciones y contexto para Claude Code |
