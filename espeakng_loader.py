from __future__ import annotations

import ctypes.util
import os
import sys
from glob import glob
from pathlib import Path


def _first_existing(paths: list[str]) -> str | None:
    for path in paths:
        if path and Path(path).exists():
            return path
    return None


def get_library_path() -> str:
    env_path = os.environ.get("ESPEAKNG_LIBRARY")
    if env_path and Path(env_path).exists():
        return env_path

    candidates = [
        *_site_package_candidates("espeak-ng.dll"),
        *glob("/usr/lib/*/libespeak-ng.so*"),
        "/usr/local/lib/libespeak-ng.so.1",
        "/usr/local/lib/libespeak-ng.so",
        "/usr/lib/libespeak-ng.so.1",
        "/usr/lib/libespeak-ng.so",
    ]
    found = _first_existing(candidates)
    if found:
        return found

    return ctypes.util.find_library("espeak-ng") or "libespeak-ng.so.1"


def get_data_path() -> str:
    env_path = os.environ.get("ESPEAKNG_DATA")
    if env_path and Path(env_path).exists():
        return env_path

    candidates = [
        *_site_package_candidates("espeak-ng-data"),
        *glob("/usr/lib/*/espeak-ng-data"),
        "/usr/share/espeak-ng-data",
        "/usr/local/share/espeak-ng-data",
    ]
    found = _first_existing(candidates)
    if found:
        return found

    return "/usr/share/espeak-ng-data"


def _site_package_candidates(name: str) -> list[str]:
    current_file = Path(__file__).resolve()
    candidates: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        root = Path(entry).resolve()
        if root == current_file.parent:
            continue
        candidate = root / "espeakng_loader" / name
        if candidate.exists():
            candidates.append(str(candidate))
    return candidates
