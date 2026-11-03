"""Límites frente a archivos excesivos o maliciosos (THREAT_MODEL T9)."""

MB = 1024 * 1024

MAX_BYTES = {
    "audio": 2048 * MB,
    "pdf": 200 * MB,
    "docx": 100 * MB,
    "rtf": 50 * MB,
    "txt": 20 * MB,
    "md": 20 * MB,
    "csv": 50 * MB,
}
MAX_PDF_PAGES = 2000
MAX_AUDIO_MS = 6 * 3600 * 1000  # 6 horas
MAX_PASTED_CHARS = 2_000_000

# DOCX (zip): defensa ante "zip bombs".
DOCX_MAX_ENTRIES = 10_000
DOCX_MAX_UNCOMPRESSED = 300 * MB
DOCX_MAX_RATIO = 200  # para entradas de más de 10 MB descomprimidas

CSV_MAX_ROWS = 100_000

# Extracción en subproceso aislado.
EXTRACT_TIMEOUT_S = 300
