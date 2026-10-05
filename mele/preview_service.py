"""Session-Preview: FITS → gestretchtes JPEG (Farbe/Debayer + Fokus-ROI).

Original-FITS bleiben unverändert. Previews landen unter ``{session}/preview/``.
Schwere Arbeit (Debayer 24 MP, ROI) läuft im NiceGUI-``io_bound``-Thread —
kein separater Hintergrundprozess nötig; Übersicht bleibt ~1600 px, volle
Auflösung nur im ROI-Ausschnitt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.visualization import AsinhStretch, PercentileInterval
from PIL import Image

FITS_SUFFIXES = {".fits", ".fit", ".fts", ".FIT", ".FITS", ".FTS"}
DEFAULT_MAX_WIDTH = 1600
DEFAULT_MAX_HEIGHT = 1200
DEFAULT_PERCENTILE = 99.5
DEFAULT_ROI_SIZE = 512
DEFAULT_FOCUS_SCALE = 2.0
PREVIEW_SUBDIR = "preview"
JPEG_QUALITY = 90

STRETCH_MODES = frozenset({"auto", "asinh", "linear"})
BAYER_PATTERNS = frozenset({"RGGB", "BGGR", "GRBG", "GBRG"})


@dataclass
class StretchParams:
    """Anzeige-Stretch; FITS-Pixelwerte bleiben unberührt."""

    mode: str = "auto"  # auto | asinh | linear
    percentile: float = DEFAULT_PERCENTILE
    black: float | None = None
    white: float | None = None
    asinh_a: float = 0.1

    def normalized(self) -> StretchParams:
        mode = str(self.mode or "auto").strip().lower()
        if mode not in STRETCH_MODES:
            mode = "auto"
        pct = float(self.percentile) if self.percentile is not None else DEFAULT_PERCENTILE
        pct = min(100.0, max(50.0, pct))
        a = float(self.asinh_a) if self.asinh_a is not None else 0.1
        a = min(1.0, max(0.001, a))
        return StretchParams(
            mode=mode,
            percentile=pct,
            black=self.black,
            white=self.white,
            asinh_a=a,
        )


@dataclass
class PreviewResult:
    preview_path: Path
    source_path: Path
    header: dict[str, Any] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    source_width: int = 0
    source_height: int = 0
    stretch: dict[str, Any] = field(default_factory=dict)
    created: bool = False
    color: bool = False
    bayer: str | None = None
    roi: dict[str, Any] | None = None
    kind: str = "overview"  # overview | focus

    def to_dict(self) -> dict[str, Any]:
        return {
            "preview_path": str(self.preview_path),
            "source_path": str(self.source_path),
            "header": self.header,
            "width": self.width,
            "height": self.height,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "stretch": self.stretch,
            "created": self.created,
            "color": self.color,
            "bayer": self.bayer,
            "roi": self.roi,
            "kind": self.kind,
        }


class PreviewError(ValueError):
    """Preview konnte nicht erzeugt werden."""


def preview_dir_for(session_dir: str | Path) -> Path:
    return Path(session_dir) / PREVIEW_SUBDIR


def preview_path_for(
    source: Path,
    session_dir: str | Path | None = None,
    *,
    color: bool = True,
) -> Path:
    """JPEG-Ziel: ``…preview.jpg`` (Farbe) bzw. ``…preview.grey.jpg``."""
    base = Path(session_dir) if session_dir is not None else source.parent
    suffix = ".preview.jpg" if color else ".preview.grey.jpg"
    return preview_dir_for(base) / f"{source.stem}{suffix}"


def focus_path_for(source: Path, session_dir: str | Path | None = None) -> Path:
    """Fokus-ROI-JPEG: ``{session}/preview/{stem}.focus.jpg``."""
    base = Path(session_dir) if session_dir is not None else source.parent
    return preview_dir_for(base) / f"{source.stem}.focus.jpg"


def find_latest_focus(session_dir: str | Path) -> Path | None:
    dest = preview_dir_for(session_dir)
    if not dest.is_dir():
        return None
    jpgs = sorted(
        (p for p in dest.glob("*.focus.jpg") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return jpgs[0] if jpgs else None


def is_fits_path(path: Path) -> bool:
    return path.suffix in FITS_SUFFIXES


def find_fits_files(session_dir: str | Path) -> list[Path]:
    """FITS im Session-Ordner (nicht unter ``preview/``), neueste zuerst."""
    root = Path(session_dir)
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or not is_fits_path(path):
            continue
        try:
            if PREVIEW_SUBDIR in path.relative_to(root).parts:
                continue
        except ValueError:
            continue
        found.append(path)
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found


def find_latest_fits(session_dir: str | Path) -> Path | None:
    files = find_fits_files(session_dir)
    return files[0] if files else None


def find_latest_preview(
    session_dir: str | Path,
    *,
    color: bool | None = None,
) -> Path | None:
    """Neuestes Overview-JPEG. ``color=None`` → egal; sonst Farbe bzw. Grau."""
    dest = preview_dir_for(session_dir)
    if not dest.is_dir():
        return None
    if color is True:
        pattern = "*.preview.jpg"
        candidates = [
            p for p in dest.glob(pattern) if p.is_file() and not p.name.endswith(".preview.grey.jpg")
        ]
    elif color is False:
        candidates = [p for p in dest.glob("*.preview.grey.jpg") if p.is_file()]
    else:
        candidates = [
            p
            for p in dest.iterdir()
            if p.is_file()
            and (p.name.endswith(".preview.jpg") or p.name.endswith(".preview.grey.jpg"))
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("ascii", errors="replace")
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return None
        return value
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if hasattr(value, "dtype") and hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def fits_header_dict(header: fits.Header) -> dict[str, Any]:
    """FITS-Header als JSON-taugliches Dict (noch keine DB-/Analyse-Logik)."""
    result: dict[str, Any] = {}
    comments: list[str] = []
    history: list[str] = []
    for card in header.cards:
        key = str(card.keyword or "")
        if key in ("", "COMMENT"):
            text = str(card.value or "").strip()
            if text:
                comments.append(text)
            continue
        if key == "HISTORY":
            text = str(card.value or "").strip()
            if text:
                history.append(text)
            continue
        result[key] = _json_safe(card.value)
    if comments:
        result["_COMMENT"] = comments
    if history:
        result["_HISTORY"] = history
    return result


def read_fits_header(path: str | Path) -> dict[str, Any]:
    """Nur Header lesen — FITS-Pixeldaten bleiben unberührt."""
    # memmap=False: NINA/Lumix-FITS oft mit BZERO/BSCALE/BLANK
    with fits.open(path, memmap=False, mode="readonly") as hdul:
        primary = hdul[0]
        assert primary is not None
        hdr = primary.header
        # Manche NINA-Stacks legen Bilddaten in Extension 1
        if (primary.data is None or getattr(primary.data, "size", 0) == 0) and len(hdul) > 1:
            ext = hdul[1]
            if ext is not None and ext.header:
                merged = fits_header_dict(hdr)
                merged.update(fits_header_dict(ext.header))
                return merged
        return fits_header_dict(hdr)


def _prepare_array(data: np.ndarray) -> np.ndarray:
    """Roharray → float32 2D (Mono) oder HxWx3 (RGB). Debayer-Hook später."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        # (C,H,W) oder (H,W,C)
        if arr.shape[0] in (3, 4) and arr.shape[0] < min(arr.shape[1], arr.shape[2]):
            arr = np.transpose(arr[:3], (1, 2, 0))
        elif arr.shape[-1] in (3, 4):
            arr = arr[..., :3]
        else:
            # unbekannte 3D-Form → Mittelung über erste Achse
            arr = np.mean(arr, axis=0)
        return np.asarray(arr, dtype=np.float32)
    raise PreviewError(f"Unsupported FITS array shape: {arr.shape}")


def bayer_pattern_from_header(header: dict[str, Any]) -> str | None:
    raw = header.get("BAYERPAT") or header.get("COLORTYP") or header.get("BAYER") or ""
    pat = str(raw).strip().upper().replace("'", "")
    if pat in BAYER_PATTERNS:
        return pat
    return None


def _bayer_offsets(header: dict[str, Any]) -> tuple[int, int]:
    try:
        x = int(header.get("XBAYROFF") or 0)
    except (TypeError, ValueError):
        x = 0
    try:
        y = int(header.get("YBAYROFF") or 0)
    except (TypeError, ValueError):
        y = 0
    return x & 1, y & 1


def _cfa_quads(
    cfa: np.ndarray,
    *,
    x_offset: int = 0,
    y_offset: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    src = np.asarray(cfa, dtype=np.float32)
    if y_offset or x_offset:
        src = src[y_offset:, x_offset:]
    h, w = src.shape
    h2 = h - (h % 2)
    w2 = w - (w % 2)
    if h2 < 2 or w2 < 2:
        raise PreviewError("CFA too small for debayer")
    src = src[:h2, :w2]
    a = src[0::2, 0::2]
    b = src[0::2, 1::2]
    c = src[1::2, 0::2]
    d = src[1::2, 1::2]
    return a, b, c, d


def debayer_halfres(
    cfa: np.ndarray,
    pattern: str,
    *,
    x_offset: int = 0,
    y_offset: int = 0,
) -> np.ndarray:
    """Sehr schnelles Debayer: 1 RGB-Pixel pro 2×2-Zelle → Hx/2 × Wx/2 × 3."""
    pat = str(pattern).strip().upper()
    if pat not in BAYER_PATTERNS:
        raise PreviewError(f"Unsupported Bayer pattern: {pattern}")
    a, b, c, d = _cfa_quads(cfa, x_offset=x_offset, y_offset=y_offset)
    if pat == "RGGB":
        r, g, bl = a, (b + c) * 0.5, d
    elif pat == "BGGR":
        r, g, bl = d, (b + c) * 0.5, a
    elif pat == "GRBG":
        r, g, bl = b, (a + d) * 0.5, c
    else:  # GBRG
        r, g, bl = c, (a + d) * 0.5, b
    return np.stack([r, g, bl], axis=-1).astype(np.float32, copy=False)


def debayer_bilinear(
    cfa: np.ndarray,
    pattern: str,
    *,
    x_offset: int = 0,
    y_offset: int = 0,
) -> np.ndarray:
    """Bilinear auf voller Auflösung — nur für kleine ROI-Crops gedacht."""
    pat = str(pattern).strip().upper()
    if pat not in BAYER_PATTERNS:
        raise PreviewError(f"Unsupported Bayer pattern: {pattern}")
    # Half-res, dann nearest auf volle CFA-Größe (für Fokus ausreichend & schnell)
    half = debayer_halfres(cfa, pat, x_offset=x_offset, y_offset=y_offset)
    src = np.asarray(cfa, dtype=np.float32)
    if y_offset or x_offset:
        src = src[y_offset:, x_offset:]
    h2 = src.shape[0] - (src.shape[0] % 2)
    w2 = src.shape[1] - (src.shape[1] % 2)
    # 2× nearest upsample
    full = np.repeat(np.repeat(half, 2, axis=0), 2, axis=1)
    return full[:h2, :w2, :].astype(np.float32, copy=False)


def maybe_debayer(
    data: np.ndarray,
    header: dict[str, Any],
    *,
    quality: str = "half",
) -> tuple[np.ndarray, str | None]:
    """Bayer-CFA → RGB wenn ``BAYERPAT`` gesetzt; sonst Daten unverändert.

    ``quality``: ``half`` (schnell, Übersicht) oder ``full`` (ROI/Fokus).
    """
    if data.ndim != 2:
        return data, None
    pat = bayer_pattern_from_header(header)
    if pat is None:
        return data, None
    x_off, y_off = _bayer_offsets(header)
    if quality == "full" and max(data.shape) <= 2048:
        rgb = debayer_bilinear(data, pat, x_offset=x_off, y_offset=y_off)
    else:
        rgb = debayer_halfres(data, pat, x_offset=x_off, y_offset=y_off)
    return rgb, pat


def load_source_image(
    path: str | Path,
    *,
    debayer: bool = True,
) -> tuple[np.ndarray, dict[str, Any], str | None]:
    """Eingabebild laden. Phase 1: nur FITS; Hook für RAW/TIFF später.

    Returns:
        (array, header, bayer_pattern|None) — array 2D Mono oder HxWx3 RGB.
    """
    src = Path(path)
    if not src.is_file():
        raise PreviewError(f"Datei fehlt: {src}")
    if is_fits_path(src):
        return _load_fits_image(src, debayer=debayer)
    raise PreviewError(f"Format noch nicht unterstützt: {src.suffix} (Phase 1: nur FITS)")


def _load_fits_image(
    path: Path,
    *,
    debayer: bool = True,
) -> tuple[np.ndarray, dict[str, Any], str | None]:
    # readonly — Original wird nie geschrieben.
    # memmap=False nötig bei BZERO/BSCALE/BLANK (typisch NINA/Kamera-FITS).
    with fits.open(path, memmap=False, mode="readonly") as hdul:
        hdu = hdul[0]
        assert hdu is not None
        data = hdu.data
        header = fits_header_dict(hdu.header)
        if data is None or getattr(data, "size", 0) == 0:
            if len(hdul) > 1 and hdul[1] is not None and hdul[1].data is not None:
                hdu = hdul[1]
                data = hdu.data
                header.update(fits_header_dict(hdu.header))
        if data is None or getattr(data, "size", 0) == 0:
            raise PreviewError(f"Keine Bilddaten in FITS: {path}")
        arr = np.array(data, dtype=np.float32, copy=True)
    arr = _prepare_array(arr)
    pat: str | None = None
    if debayer:
        arr, pat = maybe_debayer(arr, header)
    return arr, header, pat


def load_cfa_raw(path: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Roh-CFA/Mono ohne Debayer (für ROI-Crop vor Debayer)."""
    arr, header, _ = load_source_image(path, debayer=False)
    return arr, header


def _limits(
    data: np.ndarray,
    params: StretchParams,
) -> tuple[float, float]:
    if params.black is not None and params.white is not None:
        lo, hi = float(params.black), float(params.white)
        if hi <= lo:
            hi = lo + 1.0
        return lo, hi
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    interval = PercentileInterval(params.percentile)
    lo, hi = interval.get_limits(finite)
    if params.black is not None:
        lo = float(params.black)
    if params.white is not None:
        hi = float(params.white)
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def apply_stretch(data: np.ndarray, params: StretchParams | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Linear/Asinh-Stretch → float [0,1] (gleiche Shape wie Input).

    Bewusst ohne ``ImageNormalize``/matplotlib — nur Interval + Stretch.
    """
    p = (params or StretchParams()).normalized()
    lo, hi = _limits(data, p)
    span = hi - lo
    if span <= 0:
        span = 1.0
    scaled = np.clip((data - lo) / span, 0.0, 1.0)

    if p.mode == "linear":
        out = scaled
        mode_used = "linear"
    else:
        # auto und asinh nutzen Asinh (für Deep-Sky sinnvoll)
        out = np.asarray(AsinhStretch(a=p.asinh_a)(scaled), dtype=np.float32)
        mode_used = "asinh" if p.mode == "asinh" else "auto"

    out = np.nan_to_num(out, nan=0.0, posinf=1.0, neginf=0.0)
    out = np.clip(out, 0.0, 1.0).astype(np.float32, copy=False)
    meta = {
        "mode": mode_used,
        "requested_mode": p.mode,
        "percentile": p.percentile,
        "black": lo,
        "white": hi,
        "asinh_a": p.asinh_a,
    }
    return out, meta


def array_to_uint8_image(stretched: np.ndarray) -> Image.Image:
    u8 = (stretched * 255.0).clip(0, 255).astype(np.uint8)
    if u8.ndim == 2:
        return Image.fromarray(u8, mode="L")
    if u8.ndim == 3 and u8.shape[-1] == 3:
        return Image.fromarray(u8, mode="RGB")
    raise PreviewError(f"Unexpected image array shape: {u8.shape}")


def write_preview_jpeg(
    image: Image.Image,
    dest: Path,
    *,
    max_width: int | None = DEFAULT_MAX_WIDTH,
    max_height: int | None = DEFAULT_MAX_HEIGHT,
    quality: int = JPEG_QUALITY,
    scale: float = 1.0,
) -> tuple[int, int]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = image.convert("RGB") if image.mode not in ("L", "RGB") else image
    if image.mode == "L":
        img = image
    img = img.copy()
    if scale and abs(float(scale) - 1.0) > 1e-6:
        nw = max(1, int(round(img.width * float(scale))))
        nh = max(1, int(round(img.height * float(scale))))
        img = img.resize((nw, nh), Image.Resampling.NEAREST)
    if max_width is not None and max_height is not None:
        img.thumbnail(
            (max(1, int(max_width)), max(1, int(max_height))),
            Image.Resampling.LANCZOS,
        )
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    img.save(tmp, format="JPEG", quality=int(quality), optimize=True)
    tmp.replace(dest)
    return img.size  # (w, h)


def _stale_mono_preview(dest: Path, header: dict[str, Any]) -> bool:
    """Altes Graustufen-Preview neu erzeugen, wenn Bayer-Farbe möglich ist."""
    if bayer_pattern_from_header(header) is None:
        return False
    try:
        with Image.open(dest) as existing:
            return existing.mode == "L"
    except OSError:
        return True


def generate_preview(
    source: str | Path,
    *,
    session_dir: str | Path | None = None,
    stretch: StretchParams | None = None,
    force: bool = False,
    color: bool = True,
    max_width: int = DEFAULT_MAX_WIDTH,
    max_height: int = DEFAULT_MAX_HEIGHT,
) -> PreviewResult:
    """FITS → JPEG unter ``preview/``. Originaldatei wird nie verändert.

    ``color=True``: Debayer bei Bayer-CFA. ``color=False``: schnelles Graustufen
    (CFA/Mono ohne Debayer) — typisch 2–3× schneller.
    """
    src = Path(source)
    if not src.is_file():
        raise PreviewError(f"Quelle fehlt: {src}")
    sess = Path(session_dir) if session_dir is not None else src.parent
    want_color = bool(color)
    dest = preview_path_for(src, sess, color=want_color)
    params = (stretch or StretchParams()).normalized()

    if dest.is_file() and not force:
        header = read_fits_header(src) if is_fits_path(src) else {}
        # Nur Farb-Cache invalidieren, wenn versehentlich Graustufen dort liegt
        stale = want_color and _stale_mono_preview(dest, header)
        if not stale:
            with Image.open(dest) as existing:
                w, h = existing.size
                is_color = existing.mode == "RGB"
            return PreviewResult(
                preview_path=dest,
                source_path=src,
                header=header,
                width=w,
                height=h,
                source_width=int(header.get("NAXIS1") or 0),
                source_height=int(header.get("NAXIS2") or 0),
                stretch=asdict(params),
                created=False,
                color=is_color,
                bayer=bayer_pattern_from_header(header),
                kind="overview",
            )

    data, header, bayer = load_source_image(src, debayer=want_color)
    # Quellgröße aus Header (CFA), nicht aus ggf. half-res Debayer-Array
    src_w = int(header.get("NAXIS1") or 0)
    src_h = int(header.get("NAXIS2") or 0)
    if src_w <= 0 or src_h <= 0:
        if data.ndim == 2:
            src_h, src_w = data.shape
        else:
            src_h, src_w = data.shape[0], data.shape[1]
            if bayer:
                src_w *= 2
                src_h *= 2
    # SW-Übersicht: 2×2 mitteln (wie Half-Res-Debayer) — sonst Stretch auf 24 MP
    if not want_color and data.ndim == 2 and min(data.shape) >= 4:
        h2 = data.shape[0] - (data.shape[0] % 2)
        w2 = data.shape[1] - (data.shape[1] % 2)
        d = data[:h2, :w2]
        data = (
            d[0::2, 0::2] + d[0::2, 1::2] + d[1::2, 0::2] + d[1::2, 1::2]
        ) * 0.25
    is_color = data.ndim == 3

    stretched, stretch_meta = apply_stretch(data, params)
    stretch_meta["color"] = want_color
    if bayer and want_color:
        stretch_meta["debayer"] = bayer
        stretch_meta["debayer_quality"] = "half"
    elif not want_color:
        stretch_meta["grey_bin"] = 2
    image = array_to_uint8_image(stretched)
    width, height = write_preview_jpeg(
        image,
        dest,
        max_width=max_width,
        max_height=max_height,
    )
    return PreviewResult(
        preview_path=dest,
        source_path=src,
        header=header,
        width=width,
        height=height,
        source_width=int(src_w),
        source_height=int(src_h),
        stretch=stretch_meta,
        created=True,
        color=is_color,
        bayer=bayer_pattern_from_header(header),
        kind="overview",
    )


def _clamp_roi(
    x: int,
    y: int,
    w: int,
    h: int,
    src_w: int,
    src_h: int,
) -> tuple[int, int, int, int]:
    w = max(8, min(int(w), src_w))
    h = max(8, min(int(h), src_h))
    x = max(0, min(int(x), src_w - w))
    y = max(0, min(int(y), src_h - h))
    # gerade für Bayer-Crop
    x -= x % 2
    y -= y % 2
    w -= w % 2
    h -= h % 2
    w = max(8, w)
    h = max(8, h)
    if x + w > src_w:
        x = max(0, src_w - w)
        x -= x % 2
    if y + h > src_h:
        y = max(0, src_h - h)
        y -= y % 2
    return x, y, w, h


def generate_roi_preview(
    source: str | Path,
    *,
    session_dir: str | Path | None = None,
    x: int,
    y: int,
    width: int = DEFAULT_ROI_SIZE,
    height: int = DEFAULT_ROI_SIZE,
    stretch: StretchParams | None = None,
    scale: float = DEFAULT_FOCUS_SCALE,
) -> PreviewResult:
    """Fokus-ROI: Ausschnitt aus FITS in voller Auflösung (Debayer nur im Crop)."""
    src = Path(source)
    if not src.is_file():
        raise PreviewError(f"Quelle fehlt: {src}")
    sess = Path(session_dir) if session_dir is not None else src.parent
    dest = focus_path_for(src, sess)
    params = (stretch or StretchParams()).normalized()

    cfa, header = load_cfa_raw(src)
    if cfa.ndim != 2:
        # bereits RGB — Crop direkt
        src_h, src_w = cfa.shape[0], cfa.shape[1]
        rx, ry, rw, rh = _clamp_roi(x, y, width, height, src_w, src_h)
        patch = cfa[ry : ry + rh, rx : rx + rw]
        bayer = bayer_pattern_from_header(header)
    else:
        src_h, src_w = cfa.shape
        rx, ry, rw, rh = _clamp_roi(x, y, width, height, src_w, src_h)
        patch = cfa[ry : ry + rh, rx : rx + rw]
        bayer = bayer_pattern_from_header(header)
        if bayer is not None:
            # Pattern-Phase relativ zum globalen (0,0) verschieben
            x_off, y_off = _bayer_offsets(header)
            # Effektives Pattern am Crop-Ursprung
            phase_x = (rx + x_off) & 1
            phase_y = (ry + y_off) & 1
            # Pattern um phase verschieben: RGGB mit phase (1,0) → GRBG usw.
            shifted = {
                (0, 0): {
                    "RGGB": "RGGB",
                    "BGGR": "BGGR",
                    "GRBG": "GRBG",
                    "GBRG": "GBRG",
                },
                (1, 0): {
                    "RGGB": "GRBG",
                    "BGGR": "GBRG",
                    "GRBG": "RGGB",
                    "GBRG": "BGGR",
                },
                (0, 1): {
                    "RGGB": "GBRG",
                    "BGGR": "GRBG",
                    "GRBG": "BGGR",
                    "GBRG": "RGGB",
                },
                (1, 1): {
                    "RGGB": "BGGR",
                    "BGGR": "RGGB",
                    "GRBG": "GBRG",
                    "GBRG": "GRBG",
                },
            }
            local_pat = shifted[(phase_x, phase_y)][bayer]
            patch = debayer_bilinear(patch, local_pat, x_offset=0, y_offset=0)

    stretched, stretch_meta = apply_stretch(patch, params)
    if bayer:
        stretch_meta["debayer"] = bayer
    image = array_to_uint8_image(stretched)
    out_w, out_h = write_preview_jpeg(
        image,
        dest,
        max_width=None,
        max_height=None,
        scale=float(scale),
    )
    color = image.mode == "RGB" or (hasattr(patch, "ndim") and patch.ndim == 3)
    return PreviewResult(
        preview_path=dest,
        source_path=src,
        header=header,
        width=out_w,
        height=out_h,
        source_width=int(src_w),
        source_height=int(src_h),
        stretch=stretch_meta,
        created=True,
        color=bool(color),
        bayer=bayer,
        kind="focus",
        roi={
            "x": rx,
            "y": ry,
            "width": rw,
            "height": rh,
            "scale": float(scale),
            "coord_space": "source",
        },
    )


def preview_coords_to_source(
    *,
    px: float,
    py: float,
    preview_w: int,
    preview_h: int,
    source_w: int,
    source_h: int,
    display_w: float | None = None,
    display_h: float | None = None,
) -> tuple[float, float]:
    """Klick in angezeigtem/preview-Pixelraum → Quellkoordinaten."""
    # object-fit: contain: display_* = gerenderte Bildgröße im Element
    dw = float(display_w or preview_w)
    dh = float(display_h or preview_h)
    if dw <= 0 or dh <= 0 or preview_w <= 0 or preview_h <= 0:
        return 0.0, 0.0
    # zuerst vom Display zurück auf Preview-Bitmap
    scale = min(dw / preview_w, dh / preview_h)
    rendered_w = preview_w * scale
    rendered_h = preview_h * scale
    off_x = (dw - rendered_w) / 2.0
    off_y = (dh - rendered_h) / 2.0
    bx = (float(px) - off_x) / scale
    by = (float(py) - off_y) / scale
    bx = min(max(bx, 0.0), float(preview_w))
    by = min(max(by, 0.0), float(preview_h))
    sx = bx * source_w / preview_w
    sy = by * source_h / preview_h
    return sx, sy


def generate_roi_from_preview_click(
    source: str | Path,
    *,
    session_dir: str | Path | None = None,
    preview_x: float,
    preview_y: float,
    preview_w: int,
    preview_h: int,
    display_w: float | None = None,
    display_h: float | None = None,
    roi_size: int = DEFAULT_ROI_SIZE,
    stretch: StretchParams | None = None,
    scale: float = DEFAULT_FOCUS_SCALE,
) -> PreviewResult:
    """ROI um Klickpunkt (Preview-/Display-Koordinaten)."""
    header = read_fits_header(source) if is_fits_path(Path(source)) else {}
    src_w = int(header.get("NAXIS1") or 0)
    src_h = int(header.get("NAXIS2") or 0)
    if src_w <= 0 or src_h <= 0:
        cfa, header = load_cfa_raw(source)
        src_h, src_w = cfa.shape[:2]
    sx, sy = preview_coords_to_source(
        px=preview_x,
        py=preview_y,
        preview_w=preview_w,
        preview_h=preview_h,
        source_w=src_w,
        source_h=src_h,
        display_w=display_w,
        display_h=display_h,
    )
    half = max(8, int(roi_size) // 2)
    return generate_roi_preview(
        source,
        session_dir=session_dir,
        x=int(sx) - half,
        y=int(sy) - half,
        width=int(roi_size),
        height=int(roi_size),
        stretch=stretch,
        scale=scale,
    )


def preview_for_session(
    session_dir: str | Path,
    *,
    stretch: StretchParams | None = None,
    force: bool = False,
    color: bool = True,
    max_width: int = DEFAULT_MAX_WIDTH,
    max_height: int = DEFAULT_MAX_HEIGHT,
) -> PreviewResult:
    """Neuestes FITS der Session → Preview (ggf. erzeugen)."""
    root = Path(session_dir)
    if not root.is_dir():
        raise PreviewError(f"Session-Ordner fehlt: {root}")
    fits_path = find_latest_fits(root)
    if fits_path is None:
        raise PreviewError("Kein FITS in Session")
    return generate_preview(
        fits_path,
        session_dir=root,
        stretch=stretch,
        force=force,
        color=color,
        max_width=max_width,
        max_height=max_height,
    )


def wait_for_fits(
    session_dir: str | Path,
    *,
    timeout_s: float = 90.0,
    poll_s: float = 1.0,
    min_size_bytes: int = 1024,
) -> Path | None:
    """Wartet bis ein FITS im Session-Ordner liegt (NINA schreibt asynchron)."""
    import time

    root = Path(session_dir)
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    last_seen: Path | None = None
    while True:
        found = find_latest_fits(root)
        if found is not None:
            try:
                size = found.stat().st_size
            except OSError:
                size = 0
            if size >= min_size_bytes:
                # kurze Stabilität: Größe nicht mehr wachsend
                time.sleep(min(0.4, poll_s))
                try:
                    size2 = found.stat().st_size
                except OSError:
                    size2 = size
                if size2 >= size and size2 >= min_size_bytes:
                    return found
            last_seen = found
        if time.monotonic() >= deadline:
            return last_seen if last_seen and last_seen.is_file() else None
        time.sleep(max(0.2, float(poll_s)))


def wait_and_preview(
    session_dir: str | Path,
    *,
    timeout_s: float = 90.0,
    stretch: StretchParams | None = None,
    force: bool = True,
    color: bool = True,
) -> PreviewResult:
    """Nach Capture: auf FITS warten, dann JPEG erzeugen."""
    fits_path = wait_for_fits(session_dir, timeout_s=timeout_s)
    if fits_path is None:
        raise PreviewError("Kein FITS nach Capture (Timeout)")
    return generate_preview(
        fits_path,
        session_dir=session_dir,
        stretch=stretch,
        force=force,
        color=color,
    )


def session_preview_status(
    session_dir: str | Path,
    *,
    color: bool | None = None,
) -> dict[str, Any]:
    """Leichte Info ohne Erzeugung (für UI-Polling später)."""
    root = Path(session_dir)
    fits_path = find_latest_fits(root) if root.is_dir() else None
    preview = find_latest_preview(root, color=color) if root.is_dir() else None
    focus = find_latest_focus(root) if root.is_dir() else None
    return {
        "session_dir": str(root),
        "has_fits": fits_path is not None,
        "fits_path": str(fits_path) if fits_path else None,
        "has_preview": preview is not None,
        "preview_path": str(preview) if preview else None,
        "has_focus": focus is not None,
        "focus_path": str(focus) if focus else None,
        "color": color,
    }


def roi_preview_for_session(
    session_dir: str | Path,
    *,
    x: int | None = None,
    y: int | None = None,
    width: int = DEFAULT_ROI_SIZE,
    height: int = DEFAULT_ROI_SIZE,
    preview_x: float | None = None,
    preview_y: float | None = None,
    preview_w: int | None = None,
    preview_h: int | None = None,
    display_w: float | None = None,
    display_h: float | None = None,
    stretch: StretchParams | None = None,
    scale: float = DEFAULT_FOCUS_SCALE,
) -> PreviewResult:
    """ROI für neuestes Session-FITS (Quell- oder Preview-Koordinaten)."""
    root = Path(session_dir)
    fits_path = find_latest_fits(root)
    if fits_path is None:
        raise PreviewError("Kein FITS in Session")
    if preview_x is not None and preview_y is not None and preview_w and preview_h:
        return generate_roi_from_preview_click(
            fits_path,
            session_dir=root,
            preview_x=float(preview_x),
            preview_y=float(preview_y),
            preview_w=int(preview_w),
            preview_h=int(preview_h),
            display_w=display_w,
            display_h=display_h,
            roi_size=int(width or DEFAULT_ROI_SIZE),
            stretch=stretch,
            scale=scale,
        )
    if x is None or y is None:
        raise PreviewError("ROI: x/y oder preview_x/preview_y nötig")
    return generate_roi_preview(
        fits_path,
        session_dir=root,
        x=int(x),
        y=int(y),
        width=int(width),
        height=int(height),
        stretch=stretch,
        scale=scale,
    )
