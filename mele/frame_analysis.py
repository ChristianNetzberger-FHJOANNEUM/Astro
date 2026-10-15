"""JPEG-Vorschau und Rohdatenstatistik einer gespeicherten Aufnahme.

Der Aufnahmeauftrag ruft das nicht auf. Ein Probe-Light und der
Session-Abschluss starten den Lauf danach, in einem eigenen Thread.
Die RW2-Datei wird nur gelesen. Stretch gilt nur für das JPEG.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from mele.astro_manager import get_session
from mele.preview_service import (
    find_capture_files,
    find_latest_capture,
    generate_preview,
    load_cfa_raw,
    preview_path_for,
)

log = logging.getLogger(__name__)

SOURCE_LIGHT_PREVIEW = "light_preview"
MONITOR_SOURCES = (
    SOURCE_LIGHT_PREVIEW,
    "phd2_fullframe",
    "phd2_star",
    "plate_solve",
)
HISTOGRAM_BINS = 64
_MAD_TO_SIGMA = 1.4826

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(session_dir: str) -> threading.Lock:
    with _guard:
        lock = _locks.get(session_dir)
        if lock is None:
            lock = threading.Lock()
            _locks[session_dir] = lock
        return lock


def statistics_from_linear(
    values: np.ndarray,
    *,
    black_level: float,
    white_level: float,
) -> dict[str, Any]:
    """Lineare Bayer-Rohwerte, ohne Debayer und ohne Stretch.

    Hintergrund-Median und Rauschen stammen aus den Pixeln bis zum
    80.-Perzentil. Das Rauschen ist der MAD mal 1,4826. Der
    Sättigungsanteil zählt Pixel ab 99 Prozent des Weißwerts der Datei.
    """
    flat = np.asarray(values, dtype=np.float32).ravel()
    finite = flat[np.isfinite(flat)]
    if finite.size == 0:
        raise ValueError("keine auswertbaren Pixel")
    black = float(black_level)
    white = float(white_level)
    cutoff = float(np.percentile(finite, 80))
    background = finite[finite <= cutoff]
    if background.size < 8:
        background = finite
    median = float(np.median(background))
    noise = _MAD_TO_SIGMA * float(np.median(np.abs(background - median)))
    maximum = float(np.max(finite))
    percentile = float(np.percentile(finite, 99.9))
    if white > 0:
        saturated = float(np.count_nonzero(finite >= (white * 0.99)) / finite.size)
        high = max(white, maximum, 1.0)
    else:
        saturated = 0.0
        high = max(maximum, 1.0)
    counts, _edges = np.histogram(finite, bins=HISTOGRAM_BINS, range=(0.0, high))
    return {
        "black_level": black,
        "white_level": white,
        "background_median": round(median, 2),
        "background_noise": round(noise, 2),
        "max_raw": round(maximum, 2),
        "saturated_fraction": round(saturated, 6),
        "percentile_99_9": round(percentile, 2),
        "histogram_bins": [int(count) for count in counts],
        "histogram_min": 0.0,
        "histogram_max": round(high, 2),
        "pixel_count": int(finite.size),
    }


def analyze_capture_file(path: str | Path) -> dict[str, Any]:
    """Schwarz- und Weißwert aus der RW2, Histogramm aus den linearen Rohdaten."""
    array, header = load_cfa_raw(path)
    return statistics_from_linear(
        array,
        black_level=float(header.get("BLACK") or 0.0),
        white_level=float(header.get("WHITE") or 0.0),
    )


def analysis_path_for(source: Path, session_dir: str | Path) -> Path:
    dest = preview_path_for(source, session_dir, color=True)
    return dest.with_name(f"{source.stem}.analysis.json")


def resolve_capture(session_dir: str | Path, file_name: str | None = None) -> Path | None:
    root = Path(session_dir)
    wanted = Path(file_name).name if file_name else ""
    if wanted:
        for path in find_capture_files(root):
            if path.name == wanted:
                return path
    return find_latest_capture(root)


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def ensure_session_preview(
    session_dir: str | Path,
    *,
    session_id: int,
    exposure_s: float | None = None,
    iso: int | None = None,
    file_name: str | None = None,
) -> dict[str, Any] | None:
    """JPEG und Statistik derselben Datei. Vorhandenes Ergebnis wird nicht neu gerechnet."""
    root = Path(session_dir)
    with _lock_for(str(root)):
        source = resolve_capture(root, file_name)
        if source is None:
            return None
        record_path = analysis_path_for(source, root)
        jpeg = preview_path_for(source, root, color=True)
        existing = _read_record(record_path) if record_path.is_file() else None
        if existing and existing.get("analysis") and jpeg.is_file():
            return existing
        record = _build_record(
            source,
            root,
            session_id=int(session_id),
            exposure_s=exposure_s if exposure_s is not None else (existing or {}).get("exposure_s"),
            iso=iso if iso is not None else (existing or {}).get("iso"),
        )
        _write_record(record_path, record)
        return record


def _build_record(
    source: Path,
    session_dir: Path,
    *,
    session_id: int,
    exposure_s: float | None,
    iso: int | None,
) -> dict[str, Any]:
    preview = generate_preview(source, session_dir=session_dir, color=True)
    analysis: dict[str, Any] | None = None
    analysis_error = ""
    try:
        analysis = analyze_capture_file(source)
    except Exception as exc:  # noqa: BLE001
        analysis_error = str(exc) or "Rohdaten nicht lesbar"
        log.warning("RAW-Statistik fehlgeschlagen für %s: %s", source.name, analysis_error)
    return {
        "ok": True,
        "image_id": source.name,
        "source": SOURCE_LIGHT_PREVIEW,
        "session_id": int(session_id),
        "file_name": source.name,
        "exposure_s": exposure_s,
        "iso": iso,
        "width": int(preview.width),
        "height": int(preview.height),
        "stretch": dict(preview.stretch or {}),
        "analysis": analysis,
        "analysis_error": analysis_error,
    }


def schedule_session_preview(
    session_dir: str | Path,
    *,
    session_id: int,
    exposure_s: float | None = None,
    iso: int | None = None,
    file_name: str | None = None,
) -> None:
    """Startet die Vorschau neben dem Aufnahmeauftrag. Fehler bleiben in diesem Thread."""
    root = str(session_dir or "").strip()
    if not root:
        return

    def work() -> None:
        try:
            ensure_session_preview(
                root,
                session_id=int(session_id),
                exposure_s=exposure_s,
                iso=iso,
                file_name=file_name,
            )
        except Exception:  # noqa: BLE001
            log.exception("Vorschau für Session %s nicht erzeugt", session_id)

    threading.Thread(target=work, name="light-preview", daemon=True).start()


def _public_record(record: dict[str, Any], *, session_id: int, preview_url: str) -> dict[str, Any]:
    analysis = record.get("analysis") if isinstance(record.get("analysis"), dict) else None
    return {
        "ok": True,
        "image_id": record.get("image_id") or record.get("file_name") or "",
        "source": SOURCE_LIGHT_PREVIEW,
        "session_id": int(session_id),
        "file_name": record.get("file_name") or "",
        "exposure_s": record.get("exposure_s"),
        "iso": record.get("iso"),
        "width": record.get("width"),
        "height": record.get("height"),
        "stretch": record.get("stretch") if isinstance(record.get("stretch"), dict) else {},
        "analysis": analysis,
        "analysis_error": str(record.get("analysis_error") or ""),
        "preview_ready": True,
        "preview_url": preview_url,
    }


def read_light_preview(
    session_id: int,
    *,
    db_path: Path,
    source: str = SOURCE_LIGHT_PREVIEW,
) -> tuple[int, dict[str, Any]]:
    """Liest nur. Ein fehlendes JPEG startet keine Berechnung."""
    wanted = str(source or SOURCE_LIGHT_PREVIEW).strip() or SOURCE_LIGHT_PREVIEW
    if wanted != SOURCE_LIGHT_PREVIEW:
        return 404, {
            "ok": False,
            "source": wanted,
            "error": "Quelle noch nicht vorhanden",
        }
    session = get_session(int(session_id), db_path=db_path)
    if session is None:
        return 404, {"ok": False, "error": "Session fehlt", "source": SOURCE_LIGHT_PREVIEW}
    root = Path(str(session.local_path or ""))
    capture = resolve_capture(root) if root.is_dir() else None
    if capture is None:
        return 404, {
            "ok": False,
            "pending": True,
            "source": SOURCE_LIGHT_PREVIEW,
            "session_id": int(session_id),
            "error": "Kein RAW",
        }
    jpeg = preview_path_for(capture, root, color=True)
    record = _read_record(analysis_path_for(capture, root))
    if not jpeg.is_file():
        return 404, {
            "ok": False,
            "pending": True,
            "source": SOURCE_LIGHT_PREVIEW,
            "session_id": int(session_id),
            "image_id": capture.name,
            "error": "Preview noch nicht bereit",
        }
    stamp = int(jpeg.stat().st_mtime)
    preview_url = f"/astro/capture/preview/file?session_id={int(session_id)}&v={stamp}"
    if not record or not record.get("analysis"):
        return 200, {
            "ok": True,
            "image_id": capture.name,
            "source": SOURCE_LIGHT_PREVIEW,
            "session_id": int(session_id),
            "file_name": capture.name,
            "preview_ready": True,
            "preview_url": preview_url,
            "analysis": None,
            "analysis_error": "" if record is None else str(record.get("analysis_error") or ""),
            "pending": True,
        }
    return 200, _public_record(record, session_id=int(session_id), preview_url=preview_url)


def light_preview_file(session_id: int, *, db_path: Path) -> tuple[int, dict[str, Any] | Path]:
    session = get_session(int(session_id), db_path=db_path)
    if session is None:
        return 404, {"ok": False, "error": "Session fehlt"}
    root = Path(str(session.local_path or ""))
    capture = resolve_capture(root) if root.is_dir() else None
    if capture is None:
        return 404, {"ok": False, "error": "Kein RAW"}
    jpeg = preview_path_for(capture, root, color=True)
    if not jpeg.is_file():
        return 404, {"ok": False, "error": "Preview noch nicht bereit"}
    return 200, jpeg
