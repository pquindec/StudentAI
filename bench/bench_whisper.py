"""Benchmark de whisper.cpp: velocidad (RTF), precisión (WER/CER) y pico de memoria.

Uso: .venv/bin/python bench_whisper.py [modelo ...]
"""
import json
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import jiwer

ROOT = Path(__file__).parent
MODELS = ROOT / ".models"
CORPUS = ROOT / "corpus"
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)

AUDIOS = {
    "es": (CORPUS / "es_noisy.wav", CORPUS / "es_lecture.txt"),
    "en": (CORPUS / "en_noisy.wav", CORPUS / "en_lecture.txt"),
}
DEFAULT_MODELS = ["base", "small", "medium", "large-v3-turbo-q5_0"]


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def duration(wav: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout)


def run(model: str, lang: str, threads: int = 6) -> dict:
    wav, ref = AUDIOS[lang]
    prefix = OUT / f"whisper_{model}_{lang}"
    cmd = [
        "/usr/bin/time", "-l", "whisper-cli",
        "-m", str(MODELS / f"ggml-{model}.bin"),
        "-f", str(wav), "-l", lang, "-t", str(threads),
        "--vad", "-vm", str(MODELS / "ggml-silero-v5.1.2.bin"),
        "-oj", "-of", str(prefix), "-np",
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        return {"model": model, "lang": lang, "error": proc.stderr[-500:]}
    peak = re.search(r"(\d+)\s+peak memory footprint", proc.stderr)
    data = json.loads(Path(f"{prefix}.json").read_text())
    hyp = " ".join(seg["text"] for seg in data["transcription"])
    reference = norm(ref.read_text())
    hypothesis = norm(hyp)
    audio_s = duration(wav)
    return {
        "model": model,
        "lang": lang,
        "audio_s": round(audio_s, 1),
        "elapsed_s": round(elapsed, 1),
        "rtf": round(elapsed / audio_s, 3),
        "sec_per_audio_min": round(elapsed / audio_s * 60, 1),
        "wer": round(jiwer.wer(reference, hypothesis), 3),
        "cer": round(jiwer.cer(reference, hypothesis), 3),
        "peak_mem_mb": round(int(peak.group(1)) / 1e6) if peak else None,
        "segments": len(data["transcription"]),
    }


if __name__ == "__main__":
    models = sys.argv[1:] or DEFAULT_MODELS
    results = []
    for m in models:
        for lang in AUDIOS:
            r = run(m, lang)
            print(json.dumps(r, ensure_ascii=False), flush=True)
            results.append(r)
    (OUT / "whisper.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
