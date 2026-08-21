"""EXIF/Metadaten aus JPG-Sidecars und RAW (Originale nur lesen)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ExifTags

from core.models import Capture

_FILE_NUMBER_RE = re.compile(r"(\d+)")

_EXIF_NAME_TO_ID = {name: tag for tag, name in ExifTags.TAGS.items()}


def file_number_from_stem(stem: str) -> int | None:
    match = _FILE_NUMBER_RE.search(stem)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _rational_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        den = float(value.denominator)
        if den == 0:
            return None
        return float(value.numerator) / den
    if isinstance(value, tuple) and len(value) == 2 and value[1]:
        return float(value[0]) / float(value[1])
    if isinstance(value, (list, tuple)) and value:
        return _rational_to_float(value[0])
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_exposure(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return ""
    if seconds >= 1:
        return f"{seconds:g} s"
    denom = round(1.0 / seconds)
    if denom <= 0:
        return f"{seconds:g} s"
    return f"1/{denom}"


def format_aperture(fnumber: float | None) -> str:
    if fnumber is None or fnumber <= 0:
        return ""
    return f"f/{fnumber:g}"


def _exif_get(exif: dict[int, Any], name: str) -> Any:
    tag = _EXIF_NAME_TO_ID.get(name)
    if tag is None:
        return None
    return exif.get(tag)


def _parse_exif_datetime(date_str: Any, subsec: Any) -> datetime | None:
    if not date_str:
        return None
    text = str(date_str).strip().replace("-", ":")
    try:
        dt = datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.fromisoformat(str(date_str).strip())
        except ValueError:
            return None
    if subsec not in (None, ""):
        try:
            frac = str(subsec).strip()
            micros = int((frac + "000000")[:6])
            dt = dt.replace(microsecond=micros)
        except ValueError:
            pass
    return dt


def read_jpeg_exif(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif is None:
                return result
            data = dict(exif)
            try:
                ifd = exif.get_ifd(ExifTags.IFD.Exif)
                data.update(ifd)
            except Exception:
                pass
    except OSError:
        return result

    result["camera"] = str(_exif_get(data, "Model") or "").strip()
    result["lens"] = str(_exif_get(data, "LensModel") or "").strip()
    iso = _exif_get(data, "ISOSpeedRatings")
    if iso is None:
        iso = _exif_get(data, "PhotographicSensitivity")
    if isinstance(iso, (list, tuple)) and iso:
        iso = iso[0]
    try:
        result["iso"] = int(iso) if iso is not None else None
    except (TypeError, ValueError):
        result["iso"] = None
    exposure_s = _rational_to_float(_exif_get(data, "ExposureTime"))
    result["exposure"] = format_exposure(exposure_s)
    result["aperture"] = format_aperture(_rational_to_float(_exif_get(data, "FNumber")))
    fl = _rational_to_float(_exif_get(data, "FocalLength"))
    result["focal_length_mm"] = fl
    dt = _parse_exif_datetime(
        _exif_get(data, "DateTimeOriginal") or _exif_get(data, "DateTime"),
        _exif_get(data, "SubsecTimeOriginal") or _exif_get(data, "SubsecTime"),
    )
    result["datetime"] = dt
    result["datetime_src"] = "exif" if dt is not None else ""
    return result


def read_raw_exif(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        import exifread
    except ImportError:
        return result
    try:
        with path.open("rb") as handle:
            tags = exifread.process_file(handle, details=False)
    except OSError:
        return result

    def _tag(name: str) -> Any:
        value = tags.get(name)
        return value.values if value is not None else None

    dt = _parse_exif_datetime(
        str(tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime") or ""),
        str(tags.get("EXIF SubSecTimeOriginal") or tags.get("EXIF SubSecTime") or ""),
    )
    if dt is not None:
        result["datetime"] = dt
        result["datetime_src"] = "exif"
    iso = _tag("EXIF ISOSpeedRatings")
    if isinstance(iso, list) and iso:
        iso = iso[0]
    try:
        result["iso"] = int(iso) if iso is not None else None
    except (TypeError, ValueError):
        pass
    exposure_s = _rational_to_float(_tag("EXIF ExposureTime"))
    if exposure_s is not None:
        result["exposure"] = format_exposure(exposure_s)
    fnumber = _rational_to_float(_tag("EXIF FNumber"))
    if fnumber is not None:
        result["aperture"] = format_aperture(fnumber)
    model = tags.get("Image Model")
    if model:
        result["camera"] = str(model).strip()
    return result


def mtime_datetime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime)


def build_capture(raw_path: Path | None, jpg_path: Path | None) -> Capture:
    primary = raw_path or jpg_path
    if primary is None:
        raise ValueError("RAW oder JPG noetig")
    stem = primary.stem
    meta: dict[str, Any] = {}
    if jpg_path is not None:
        meta.update(read_jpeg_exif(jpg_path))
    if raw_path is not None and not meta.get("datetime"):
        meta.update({k: v for k, v in read_raw_exif(raw_path).items() if v})
    dt = meta.get("datetime")
    src = str(meta.get("datetime_src") or "")
    if dt is None:
        dt = mtime_datetime(jpg_path or raw_path)  # type: ignore[arg-type]
        src = "mtime"
    return Capture(
        raw_path=raw_path,
        jpg_path=jpg_path,
        datetime=dt,
        datetime_src=src,
        exposure=str(meta.get("exposure") or ""),
        iso=meta.get("iso"),
        aperture=str(meta.get("aperture") or ""),
        focal_length_mm=meta.get("focal_length_mm"),
        camera=str(meta.get("camera") or ""),
        lens=str(meta.get("lens") or ""),
        file_number=file_number_from_stem(stem),
        stem=stem,
    )
