from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf


SAMPLE_RATE = 24000
LANG_CODE = "p"  # Brazilian Portuguese (pt-br)
DEFAULT_VOICE = "pf_dora"
REPO_ID = "hexgrad/Kokoro-82M"
MP3_BITRATE = "192k"
VOICE_OPTIONS = [
    {
        "id": "pf_dora",
        "label": "Dora",
        "description": "Voz feminina oficial em portugues do Brasil.",
    },
    {
        "id": "pm_alex",
        "label": "Alex",
        "description": "Voz masculina oficial em portugues do Brasil.",
    },
    {
        "id": "pm_santa",
        "label": "Santa",
        "description": "Voz masculina oficial em portugues do Brasil.",
    },
    {
        "id": "pf_dora,pm_alex",
        "label": "Dora + Alex",
        "description": "Mistura experimental de duas vozes pt-BR.",
    },
    {
        "id": "pf_dora,pm_santa",
        "label": "Dora + Santa",
        "description": "Mistura experimental de duas vozes pt-BR.",
    },
    {
        "id": "pm_alex,pm_santa",
        "label": "Alex + Santa",
        "description": "Mistura experimental de duas vozes pt-BR.",
    },
]
VOICE_IDS = {voice["id"] for voice in VOICE_OPTIONS}
ProgressCallback = Callable[[int, str], None]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera um arquivo MP3 com TTS em portugues do Brasil usando Kokoro."
    )
    parser.add_argument(
        "texto",
        nargs="*",
        help="Texto a converter em voz. Tambem pode usar --text, --input-file ou stdin.",
    )
    parser.add_argument("-t", "--text", help="Texto a converter em voz.")
    parser.add_argument(
        "-i",
        "--input-file",
        type=Path,
        help="Arquivo de texto UTF-8 para converter em voz.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("saida.mp3"),
        help="Arquivo de saida .mp3 ou .wav. Padrao: saida.mp3",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help=f"Voz do Kokoro. Padrao: {DEFAULT_VOICE}",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Velocidade da fala. Padrao: 1.0",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="Dispositivo do modelo. Padrao: auto, usando CUDA quando disponivel.",
    )
    return parser.parse_args()


def read_text(args: argparse.Namespace) -> str:
    sources = [
        args.text is not None,
        args.input_file is not None,
        bool(args.texto),
    ]
    if sum(sources) > 1:
        raise SystemExit("Use apenas uma fonte de texto: argumento, --text ou --input-file.")

    if args.text is not None:
        text = args.text
    elif args.input_file is not None:
        text = args.input_file.read_text(encoding="utf-8-sig")
    elif args.texto:
        text = " ".join(args.texto)
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = input("Digite o texto em portugues do Brasil: ")

    text = text.strip()
    if not text:
        raise SystemExit("Nenhum texto foi informado.")
    return text


def audio_to_numpy(audio) -> np.ndarray:
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def normalize_output_path(output: Path) -> Path:
    if not output.suffix:
        output = output.with_suffix(".mp3")
    if output.suffix.lower() not in {".mp3", ".wav"}:
        raise SystemExit("A saida deve ser um arquivo .mp3 ou .wav.")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def resolve_device(device: str) -> str:
    import torch

    if device == "auto":
        if torch.cuda.is_available():
            cuda_name = torch.cuda.get_device_name(0)
            print(f"Usando GPU CUDA: {cuda_name}")
            return "cuda"
        print("CUDA nao disponivel; usando CPU.")
        return "cpu"

    if device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA foi solicitado, mas o PyTorch nao encontrou GPU disponivel.")

    return device


def write_audio_file(output: Path, audio: np.ndarray) -> None:
    suffix = output.suffix.lower()
    if suffix == ".mp3":
        write_mp3_file(output, audio)
    elif suffix == ".wav":
        sf.write(output, audio, SAMPLE_RATE, subtype="PCM_16")
    else:
        raise ValueError(f"Formato de saida nao suportado: {suffix}")


def write_mp3_file(output: Path, audio: np.ndarray) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        sf.write(output, audio, SAMPLE_RATE, format="MP3", subtype="MPEG_LAYER_III")
        return

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        sf.write(temp_path, audio, SAMPLE_RATE, subtype="PCM_16")
        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(temp_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            MP3_BITRATE,
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            str(output),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def collect_audio_chunks(
    pipeline,
    text: str,
    voice: str,
    speed: float,
    progress_callback: ProgressCallback | None = None,
) -> np.ndarray:
    generator = pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")

    chunks: list[np.ndarray] = []
    for index, result in enumerate(generator, start=1):
        if result.audio is None:
            continue
        chunks.append(audio_to_numpy(result.audio))
        graphemes = result.graphemes[:80]
        if progress_callback is not None:
            progress_callback(index, graphemes)
        else:
            print(f"Trecho {index} gerado: {graphemes}")

    if not chunks:
        raise RuntimeError("O Kokoro nao gerou audio para o texto informado.")

    return np.concatenate(chunks)


class KokoroTTS:
    def __init__(self, device: str = "auto") -> None:
        self.device = resolve_device(device)
        self._pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code=LANG_CODE, repo_id=REPO_ID, device=self.device)
        return self._pipeline

    def create_audio_file(
        self,
        text: str,
        output: Path,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        audio = collect_audio_chunks(
            pipeline=self.pipeline,
            text=text,
            voice=voice,
            speed=speed,
            progress_callback=progress_callback,
        )
        write_audio_file(output, audio)


def text_to_audio_file(text: str, output: Path, voice: str, speed: float, device: str) -> None:
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code=LANG_CODE, repo_id=REPO_ID, device=device)
    audio = collect_audio_chunks(pipeline=pipeline, text=text, voice=voice, speed=speed)
    write_audio_file(output, audio)


def main() -> None:
    args = parse_args()
    text = read_text(args)
    output = normalize_output_path(args.output)
    device = resolve_device(args.device)

    try:
        text_to_audio_file(
            text=text,
            output=output,
            voice=args.voice,
            speed=args.speed,
            device=device,
        )
    except FileNotFoundError as exc:
        missing = str(exc.filename or exc)
        if "espeak" in missing.lower():
            raise SystemExit(
                "O Kokoro usa espeak-ng para portugues do Brasil, mas ele nao foi "
                "encontrado no PATH. Instale o espeak-ng e execute novamente."
            ) from exc
        raise

    print(f"Arquivo criado: {output.resolve()}")


if __name__ == "__main__":
    main()
