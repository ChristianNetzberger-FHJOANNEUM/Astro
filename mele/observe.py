"""Standort und Aufnahmezeit aus Foto-EXIF, sonst mele.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import ExifTags, Image

from mele.config import MeleSettings

SITE_PHOTO_MAX_BYTES = 20 * 1024 * 1024
_JPEG_SUFFIXES = {".jpg", ".jpeg"}


@dataclass(frozen=True)
class Observer:
    latitude_deg: float | None
    longitude_deg: float | None
    site_src: str
    photo_when: datetime | None
    photo_when_src: str


def local_tz(name: str | None) -> timezone | ZoneInfo:
    if name:
        return ZoneInfo(name)
    found = datetime.now().astimezone().tzinfo
    return found if found is not None else timezone.utc


def dms_to_deg(dms: object, ref: str) -> float | None:
    if isinstance(dms, (int, float)):
        value = float(dms)
    elif isinstance(dms, (list, tuple)) and len(dms) >= 3:
        deg, minutes, seconds = (float(dms[0]), float(dms[1]), float(dms[2]))
        value = abs(deg) + minutes / 60.0 + seconds / 3600.0
        if deg < 0:
            value = -value
    else:
        return None
    ref_u = (ref or "").strip().upper()
    if ref_u in {"S", "W"}:
        value = -abs(value)
    elif ref_u in {"N", "E"}:
        value = abs(value)
    return value


def gps_is_usable(lat: float, lon: float, status: str = "") -> bool:
    if status.strip().upper() == "V":
        return False
    if abs(lat) < 1e-4 and abs(lon) < 1e-4:
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return True


def _open_exif(path: Path):
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if exif is None:
                return None, {}
            extra: dict = {}
            try:
                extra.update(exif.get_ifd(ExifTags.IFD.Exif))
            except Exception:
                pass
            return exif, extra
    except OSError:
        return None, {}
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def gps_from_jpeg(path: Path) -> tuple[float, float] | None:
    exif, _extra = _open_exif(path)
    if exif is None:
        return None
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except Exception:
        return None
    if not gps:
        return None
    names = {ExifTags.GPSTAGS.get(key, key): value for key, value in gps.items()}
    lat = dms_to_deg(names.get("GPSLatitude"), str(names.get("GPSLatitudeRef") or ""))
    lon = dms_to_deg(names.get("GPSLongitude"), str(names.get("GPSLongitudeRef") or ""))
    if lat is None or lon is None:
        return None
    status = str(names.get("GPSStatus") or "")
    if not gps_is_usable(lat, lon, status):
        return None
    return lat, lon


def _parse_exif_offset(text: object) -> timedelta | None:
    raw = str(text or "").strip()
    if len(raw) < 6 or raw[0] not in "+-":
        return None
    try:
        hours = int(raw[1:3])
        minutes = int(raw[4:6])
    except ValueError:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return delta if raw[0] == "+" else -delta


def photo_datetime(path: Path, tz_name: str | None = None) -> datetime | None:
    exif, extra = _open_exif(path)
    if exif is None:
        return None
    names = {ExifTags.TAGS.get(key, key): value for key, value in dict(exif).items()}
    names.update({ExifTags.TAGS.get(key, key): value for key, value in extra.items()})
    raw = names.get("DateTimeOriginal") or names.get("DateTime")
    if not raw:
        return None
    text = str(raw).strip().replace("-", ":")
    try:
        naive = datetime.strptime(text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    offset = _parse_exif_offset(names.get("OffsetTimeOriginal") or names.get("OffsetTime"))
    if offset is not None:
        return (naive - offset).replace(tzinfo=timezone.utc)
    local = naive.replace(tzinfo=local_tz(tz_name))
    return local.astimezone(timezone.utc)


def resolve_observer(path: Path | None, settings: MeleSettings) -> Observer:
    lat = settings.latitude_deg
    lon = settings.longitude_deg
    site_src = "config" if lat is not None and lon is not None else "none"
    photo_when = None
    photo_src = ""
    if path is not None and path.is_file():
        gps = gps_from_jpeg(path)
        if gps is not None:
            lat, lon = gps
            site_src = "exif"
        photo_when = photo_datetime(path, settings.timezone)
        if photo_when is not None:
            photo_src = "exif"
    return Observer(
        latitude_deg=lat,
        longitude_deg=lon,
        site_src=site_src,
        photo_when=photo_when,
        photo_when_src=photo_src,
    )


def list_location_jpegs(folder: Path) -> list[tuple[Path, float | None, float | None]]:
    """Alle JPEGs in media/GPS-locations, mit GPS falls vorhanden."""
    if not folder.is_dir():
        return []
    found: list[tuple[Path, float | None, float | None]] = []
    for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in _JPEG_SUFFIXES:
            continue
        try:
            if path.stat().st_size > SITE_PHOTO_MAX_BYTES:
                continue
        except OSError:
            continue
        gps = gps_from_jpeg(path)
        if gps is None:
            found.append((path, None, None))
        else:
            found.append((path, gps[0], gps[1]))
    return found


def iter_geotagged_jpegs(folder: Path) -> list[tuple[Path, float, float]]:
    """Nur Dateien mit gueltigem GPS."""
    return [
        (path, lat, lon)
        for path, lat, lon in list_location_jpegs(folder)
        if lat is not None and lon is not None
    ]
