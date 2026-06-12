from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path
from threading import Lock
from uuid import uuid4

import anyio
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from teste import DEFAULT_VOICE, VOICE_IDS, VOICE_OPTIONS, KokoroTTS, normalize_output_path


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
GENERATED_DIR = BASE_DIR / "generated"
TESSDATA_CANDIDATES = [
    BASE_DIR / "tessdata",
    Path("/usr/share/tesseract-ocr/5/tessdata"),
    Path("/usr/share/tesseract-ocr/4.00/tessdata"),
    Path("/usr/share/tessdata"),
]
GENERATED_DIR.mkdir(exist_ok=True)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}

app = FastAPI(title="Kokoro TTS")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/tts/static", StaticFiles(directory=STATIC_DIR), name="tts-static")

tts_lock = Lock()
ocr_lock = Lock()
tts_service: KokoroTTS | None = None
ocr_reader = None


class GenerateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice: str = Field(
        default=DEFAULT_VOICE,
        min_length=2,
        max_length=120,
        pattern=r"^[A-Za-z0-9_,./\\:-]+$",
    )
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


def detect_device() -> dict[str, str | bool]:
    import torch

    if torch.cuda.is_available():
        return {
            "device": "cuda",
            "label": torch.cuda.get_device_name(0),
            "cuda": True,
        }
    return {
        "device": "cpu",
        "label": "CPU",
        "cuda": False,
    }


def get_tts_service() -> KokoroTTS:
    global tts_service

    if tts_service is None:
        device = str(detect_device()["device"])
        tts_service = KokoroTTS(device=device)
    return tts_service


def get_ocr_reader():
    global ocr_reader

    if ocr_reader is None:
        try:
            import easyocr
        except ImportError:
            return None

        use_gpu = bool(detect_device()["cuda"])
        ocr_reader = easyocr.Reader(["pt", "en"], gpu=use_gpu, verbose=False)
    return ocr_reader


def image_bytes_to_array(image_bytes: bytes):
    import numpy as np
    from PIL import Image, ImageOps

    image = Image.open(BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGB")
    return np.asarray(image)


def clean_ocr_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def lines_from_text(text: str, confidence: float | None = None) -> list[dict[str, float | str]]:
    lines: list[dict[str, float | str]] = []
    for line in text.splitlines():
        clean_line = " ".join(line.split())
        if not clean_line:
            continue
        item: dict[str, float | str] = {"text": clean_line}
        if confidence is not None:
            item["confidence"] = confidence
        lines.append(item)
    return lines


def find_tesseract() -> str | None:
    candidates = [
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def find_tessdata_dir() -> Path | None:
    for candidate in TESSDATA_CANDIDATES:
        if (candidate / "por.traineddata").exists():
            return candidate
    return None


def extract_text_with_tesseract(image_bytes: bytes) -> str:
    from PIL import Image, ImageOps

    tesseract = find_tesseract()
    tessdata_dir = find_tessdata_dir()
    if tesseract is None or tessdata_dir is None:
        return ""

    temp_path: Path | None = None
    try:
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        if min(image.size) < 900:
            image = image.resize((image.width * 2, image.height * 2))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        image.save(temp_path)

        command = [
            tesseract,
            str(temp_path),
            "stdout",
            "--tessdata-dir",
            str(tessdata_dir),
            "-l",
            "por",
            "--oem",
            "1",
            "--psm",
            "6",
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            return ""
        return clean_ocr_text(result.stdout)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def extract_text_with_easyocr(image_bytes: bytes) -> dict[str, str | list[dict[str, float | str]]]:
    image = image_bytes_to_array(image_bytes)

    with ocr_lock:
        reader = get_ocr_reader()
        if reader is None:
            return {
                "text": "",
                "lines": [],
            }
        results = reader.readtext(
            image,
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            text_threshold=0.55,
            low_text=0.35,
            link_threshold=0.35,
        )

    lines: list[dict[str, float | str]] = []
    for _, text, confidence in results:
        clean_text = " ".join(text.split())
        if clean_text:
            lines.append(
                {
                    "text": clean_text,
                    "confidence": round(float(confidence), 3),
                }
            )

    return {
        "text": "\n".join(str(line["text"]) for line in lines),
        "lines": lines,
    }


def extract_text_from_image(image_bytes: bytes) -> dict[str, str | list[dict[str, float | str]]]:
    text = extract_text_with_tesseract(image_bytes)
    if text:
        return {
            "engine": "tesseract",
            "text": text,
            "lines": lines_from_text(text),
        }
    result = extract_text_with_easyocr(image_bytes)
    result["engine"] = "easyocr"
    return result


def extract_text_from_images(image_payloads: list[bytes]) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    texts: list[str] = []
    engines: list[str] = []

    for index, image_bytes in enumerate(image_payloads, start=1):
        result = extract_text_from_image(image_bytes)
        text = str(result.get("text", "")).strip()
        engine = str(result.get("engine", "ocr"))
        pages.append(
            {
                "index": index,
                "engine": engine,
                "text": text,
                "lines": result.get("lines", []),
            }
        )
        if text:
            texts.append(text)
        if engine not in engines:
            engines.append(engine)

    return {
        "engine": " + ".join(engines) if engines else "ocr",
        "text": "\n\n".join(texts),
        "pages": pages,
    }


def clean_old_files(max_age_hours: int = 12) -> None:
    cutoff = time.time() - (max_age_hours * 60 * 60)
    for path in GENERATED_DIR.glob("*.mp3"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def generate_mp3(text: str, voice: str, speed: float) -> dict[str, str | float]:
    if voice not in VOICE_IDS:
        raise ValueError("Escolha uma voz da lista.")

    clean_old_files()
    output = normalize_output_path(GENERATED_DIR / f"{uuid4().hex}.mp3")

    with tts_lock:
        service = get_tts_service()
        service.create_audio_file(
            text=text,
            output=output,
            voice=voice,
            speed=speed,
            progress_callback=lambda index, chunk: print(f"Web trecho {index}: {chunk}"),
        )

    return {
        "audio_url": f"audio/{output.name}",
        "filename": output.name,
        "voice": voice,
        "speed": speed,
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/tts/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/tts")
def tts_redirect() -> RedirectResponse:
    return RedirectResponse(url="/tts/")


@app.get("/api/status")
@app.get("/tts/api/status")
def status() -> dict[str, str | bool]:
    return detect_device()


@app.get("/health")
@app.get("/tts/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/voices")
@app.get("/tts/api/voices")
def voices() -> dict[str, str | list[dict[str, str]]]:
    return {
        "default_voice": DEFAULT_VOICE,
        "voices": VOICE_OPTIONS,
    }


async def read_image_uploads(files: list[UploadFile]) -> list[bytes]:
    if not files:
        raise HTTPException(status_code=400, detail="Envie pelo menos uma imagem.")

    payloads: list[bytes] = []
    for file in files:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Envie imagens PNG, JPG, WEBP, BMP ou TIFF.")

        image_bytes = await file.read()
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=400, detail="Cada imagem deve ter no maximo 10 MB.")
        payloads.append(image_bytes)

    return payloads


@app.post("/api/ocr")
@app.post("/tts/api/ocr")
async def ocr(
    images: list[UploadFile] | None = File(default=None),
    image: UploadFile | None = File(default=None),
) -> dict[str, object]:
    files = images or []
    if image is not None:
        files = [image, *files]

    image_payloads = await read_image_uploads(files)

    try:
        return await anyio.to_thread.run_sync(extract_text_from_images, image_payloads)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha no OCR: {exc}") from exc


@app.post("/api/generate")
@app.post("/tts/api/generate")
async def generate(request: GenerateRequest) -> dict[str, str | float]:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Informe um texto.")

    try:
        return await anyio.to_thread.run_sync(
            generate_mp3,
            text,
            request.voice,
            request.speed,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/audio/{filename}")
@app.get("/tts/audio/{filename}")
def audio(filename: str) -> FileResponse:
    if re.fullmatch(r"[a-f0-9]{32}\.mp3", filename) is None:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    path = (GENERATED_DIR / filename).resolve()
    if path.parent != GENERATED_DIR.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    return FileResponse(path, media_type="audio/mpeg", filename=filename)
