"""Kleine JPG-Vorschauen lokal cachen, Originale auf der NAS nicht streamen."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

THUMB_MAX_PX = 640


def thumb_file(source: Path, thumbs_dir: Path) -> Path:
    digest = hashlib.sha1(str(source).encode("utf-8", errors="replace")).hexdigest()[:16]
    return thumbs_dir / f"{digest}.jpg"


def ensure_thumb(source: str | Path, thumbs_dir: Path, max_px: int = THUMB_MAX_PX) -> Path | None:
    src = Path(source)
    if not src.is_file():
        return None
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    dest = thumb_file(src, thumbs_dir)
    try:
        src_mtime = src.stat().st_mtime
        if dest.is_file() and dest.stat().st_mtime >= src_mtime:
            return dest
        with Image.open(src) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((max_px, max_px))
            rgb.save(dest, "JPEG", quality=80, optimize=True)
        return dest
    except OSError:
        return None


def thumb_url(source: str | None, thumbs_dir: Path) -> str | None:
    if not source:
        return None
    dest = ensure_thumb(source, thumbs_dir)
    if dest is None:
        return None
    return "/thumbs/" + dest.name
