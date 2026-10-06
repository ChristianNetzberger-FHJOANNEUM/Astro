"""Lokale Sterndatenbank: Import (HYG + Sternbilder + OpenNGC) und Overlay-Abfrage."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from mele.config import REPO_ROOT, load_mele_settings
from mele.ephemeris import solar_system_bodies, sun_radec
from mele.horizon import HorizonProfile
from mele.sky import radec_to_az_alt, radec_to_az_alt_many

DEFAULT_DB = REPO_ROOT / "data" / "catalogs" / "sky.sqlite"
DEFAULT_SRC = REPO_ROOT / "data" / "catalogs" / "src"

# OpenNGC Type-Codes -> UI-Gruppen (Messier und NGC/IC teilen dasselbe Feld).
DSO_TYPE_GROUPS: dict[str, frozenset[str]] = {
    "galaxy": frozenset({"G", "GPair", "GTrpl", "GGroup"}),
    "globular": frozenset({"GCl"}),
    "open": frozenset({"OCl", "*Ass", "Cl+N"}),
    "planetary": frozenset({"PN"}),
    "nebula": frozenset({"Neb", "HII", "EmN", "RfN", "DrkN", "SNR"}),
}
DSO_TYPE_GROUP_KEYS = ("galaxy", "globular", "open", "planetary", "nebula", "other")
_DSO_GROUPED_TYPES = frozenset().union(*DSO_TYPE_GROUPS.values())


def normalize_dso_type_groups(groups: list[str] | set[str] | None) -> set[str] | None:
    """UI-Gruppen normalisieren. None = alle (kein Filter). Leere Menge = keine DSO."""
    if groups is None:
        return None
    allowed = {str(g).strip().lower() for g in groups if str(g).strip()}
    allowed &= set(DSO_TYPE_GROUP_KEYS)
    if allowed >= set(DSO_TYPE_GROUP_KEYS):
        return None
    return allowed


def dso_row_matches_type_groups(raw_type: str | None, groups: set[str] | None) -> bool:
    if groups is None:
        return True
    if not groups:
        return False
    code = (raw_type or "").strip()
    for key, codes in DSO_TYPE_GROUPS.items():
        if key in groups and code in codes:
            return True
    if "other" in groups and code not in _DSO_GROUPED_TYPES:
        return True
    return False


DOWNLOADS = (
    (
        "hygdata_v41.csv",
        (
            "https://raw.githubusercontent.com/astronexus/HYG-Database/master/hyg/CURRENT/hygdata_v41.csv",
        ),
    ),
    (
        "constellationship.fab",
        (
            "https://raw.githubusercontent.com/Stellarium/stellarium/eb47095a9282cf6b981f6e37fe1ea3a3ae0fd167/skycultures/modern/constellationship.fab",
        ),
    ),
    (
        "NGC.csv",
        (
            "https://raw.githubusercontent.com/mattiaverga/OpenNGC/refs/tags/v20231203/database_files/NGC.csv",
        ),
    ),
    (
        "addendum.csv",
        (
            "https://raw.githubusercontent.com/mattiaverga/OpenNGC/refs/tags/v20231203/database_files/addendum.csv",
        ),
    ),
)

IAU_NAMES = {
    "And": "Andromeda",
    "Ant": "Luftpumpe",
    "Aps": "Paradiesvogel",
    "Aql": "Adler",
    "Aqr": "Wassermann",
    "Ara": "Altar",
    "Ari": "Widder",
    "Aur": "Fuhrmann",
    "Boo": "Baerenhueter",
    "Cae": "Grabstichel",
    "Cam": "Giraffe",
    "Cap": "Steinbock",
    "Car": "Kiel",
    "Cas": "Kassiopeia",
    "Cen": "Zentaur",
    "Cep": "Kepheus",
    "Cet": "Walfisch",
    "Cha": "Chamaeleon",
    "Cir": "Zirkel",
    "CMa": "Grosser Hund",
    "CMi": "Kleiner Hund",
    "Cnc": "Krebs",
    "Col": "Taube",
    "Com": "Haar der Berenike",
    "CrA": "Suedliche Krone",
    "CrB": "Noerdliche Krone",
    "Crv": "Rabe",
    "Crt": "Becher",
    "Cru": "Kreuz des Suedens",
    "Cyg": "Schwan",
    "Del": "Delphin",
    "Dor": "Schwertfisch",
    "Dra": "Drache",
    "Equ": "Fuelllen",
    "Eri": "Eridanus",
    "For": "Chemischer Ofen",
    "Gem": "Zwillinge",
    "Gru": "Kranich",
    "Her": "Herkules",
    "Hor": "Pendeluhr",
    "Hya": "Wasserschlange",
    "Hyi": "Kleine Wasserschlange",
    "Ind": "Indianer",
    "Lac": "Eidechse",
    "Leo": "Loewe",
    "Lep": "Hase",
    "Lib": "Waage",
    "LMi": "Kleiner Loewe",
    "Lup": "Wolf",
    "Lyn": "Luchs",
    "Lyr": "Leier",
    "Men": "Tafelberg",
    "Mic": "Mikroskop",
    "Mon": "Einhorn",
    "Mus": "Fliege",
    "Nor": "Winkelmass",
    "Oct": "Oktant",
    "Oph": "Schlangentraeger",
    "Ori": "Orion",
    "Pav": "Pfau",
    "Peg": "Pegasus",
    "Per": "Perseus",
    "Phe": "Phoenix",
    "Pic": "Maler",
    "PsA": "Suedlicher Fisch",
    "Psc": "Fische",
    "Pup": "Achterdeck",
    "Pyx": "Kompass",
    "Ret": "Netz",
    "Scl": "Bildhauer",
    "Sco": "Skorpion",
    "Sct": "Schild",
    "Ser": "Schlange",
    "Sex": "Sextant",
    "Sge": "Pfeil",
    "Sgr": "Schuetze",
    "Tau": "Stier",
    "Tel": "Teleskop",
    "TrA": "Suedliches Dreieck",
    "Tri": "Dreieck",
    "Tuc": "Tukan",
    "UMa": "Grosser Baer",
    "UMi": "Kleiner Baer",
    "Vel": "Segel",
    "Vir": "Jungfrau",
    "Vol": "Fliegender Fisch",
    "Vul": "Fuchs",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS stars (
    hip INTEGER,
    ra_deg REAL NOT NULL,
    dec_deg REAL NOT NULL,
    mag REAL,
    name TEXT,
    con TEXT
);
CREATE INDEX IF NOT EXISTS stars_hip ON stars(hip);
CREATE INDEX IF NOT EXISTS stars_mag ON stars(mag);
CREATE TABLE IF NOT EXISTS constellation_lines (
    iau TEXT NOT NULL,
    hip_a INTEGER NOT NULL,
    hip_b INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dso (
    key TEXT PRIMARY KEY,
    catalog TEXT NOT NULL,
    number INTEGER,
    name TEXT,
    type TEXT,
    ra_deg REAL NOT NULL,
    dec_deg REAL NOT NULL,
    mag REAL,
    mag_band TEXT,
    messier INTEGER
);
CREATE INDEX IF NOT EXISTS dso_messier ON dso(messier);
CREATE INDEX IF NOT EXISTS dso_mag ON dso(mag);
"""


def catalog_db_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    return load_mele_settings().catalog_dir / "sky.sqlite"


def catalog_ready(db_path: Path | None = None) -> bool:
    path = catalog_db_path(db_path)
    if not path.is_file():
        return False
    with sqlite3.connect(path) as conn:
        try:
            n = conn.execute("SELECT COUNT(*) FROM stars").fetchone()[0]
        except sqlite3.Error:
            return False
    return n > 0


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open(encoding="utf-8", newline="")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "MeLE-Astro/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)


def ensure_sources(src_dir: Path, download: bool = True) -> dict[str, Path]:
    src_dir.mkdir(parents=True, exist_ok=True)
    found: dict[str, Path] = {}
    aliases = {
        "hygdata_v41.csv": (
            "hygdata_v41.csv",
            "hyg_v44.csv",
            "hyg.csv",
            "hyg_github_v41.tmp",
        ),
        "constellationship.fab": ("constellationship.fab",),
        "NGC.csv": ("NGC.csv",),
        "addendum.csv": ("addendum.csv",),
    }
    for key, names in aliases.items():
        for name in names:
            path = src_dir / name
            if path.is_file() and path.stat().st_size > 100:
                found[key] = path
                break
        if key not in found:
            for path in src_dir.glob("hyg*.csv*") if key.startswith("hyg") else []:
                found[key] = path
                break
    if not download:
        return found
    for filename, urls in DOWNLOADS:
        if filename in found:
            continue
        dest = src_dir / filename
        last_error: Exception | None = None
        for url in urls:
            try:
                print(f"Lade {url}")
                _download(url, dest)
                found[filename] = dest
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 — Spiegel-Fallback
                last_error = exc
        if filename not in found and last_error is not None:
            raise RuntimeError(f"{filename} nicht geladen: {last_error}") from last_error
    return found


def _parse_hyg(path: Path) -> list[tuple]:
    with _open_text(path) as handle:
        raw_rows = list(csv.DictReader(handle))
    sample_ra = []
    for raw in raw_rows:
        try:
            mag = float(raw.get("mag") or "99")
            ra = float(raw.get("ra") or 0)
        except ValueError:
            continue
        if mag <= 3:
            sample_ra.append(ra)
    hours = True if not sample_ra else max(sample_ra) <= 24.5
    rows: list[tuple] = []
    for raw in raw_rows:
        name = (raw.get("proper") or "").strip()
        if name == "Sol":
            continue
        try:
            ra = float(raw.get("ra") or "")
            dec = float(raw.get("dec") or "")
        except ValueError:
            continue
        ra_deg = ra * 15.0 if hours else ra
        mag_s = raw.get("mag")
        try:
            mag = float(mag_s) if mag_s not in (None, "") else None
        except ValueError:
            mag = None
        hip_s = (raw.get("hip") or "").strip()
        hip = int(hip_s) if hip_s.isdigit() else None
        rows.append((hip, ra_deg, dec, mag, name, (raw.get("con") or "").strip()))
    return rows


def parse_constellation_fab(path: Path) -> list[tuple[str, int, int]]:
    lines: list[tuple[str, int, int]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) < 4:
            continue
        iau = parts[0]
        try:
            count = int(parts[1])
            hips = [int(item) for item in parts[2:]]
        except ValueError:
            continue
        for index in range(count):
            start = 2 * index
            if start + 1 >= len(hips):
                break
            lines.append((iau, hips[start], hips[start + 1]))
    return lines


def _sexagesimal(text: str, hours: bool) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    sign = -1.0 if raw.startswith("-") else 1.0
    bits = raw.lstrip("+-").split(":")
    try:
        first = float(bits[0])
        minutes = float(bits[1]) if len(bits) > 1 else 0.0
        seconds = float(bits[2]) if len(bits) > 2 else 0.0
    except ValueError:
        return None
    value = sign * (abs(first) + minutes / 60.0 + seconds / 3600.0)
    return value * 15.0 if hours else value


def _parse_openngc(path: Path) -> list[tuple]:
    rows: list[tuple] = []
    with path.open(encoding="utf-8", newline="") as handle:
        sample = handle.read(256)
        handle.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(handle, delimiter=delimiter)
        for raw in reader:
            kind = (raw.get("Type") or "").strip()
            if kind in {"Dup", "NonEx"}:
                continue
            ra = _sexagesimal(raw.get("RA") or "", hours=True)
            dec = _sexagesimal(raw.get("Dec") or "", hours=False)
            if ra is None or dec is None:
                continue
            name = (raw.get("Name") or "").strip()
            if not name:
                continue
            common = (raw.get("Common names") or "").split(",")[0].strip()
            mag, mag_band = _parse_openngc_mag(raw)
            messier_s = (raw.get("M") or "").strip()
            messier = int(messier_s) if messier_s.isdigit() else None
            if name.startswith("NGC"):
                catalog, number_s = "NGC", name[3:]
            elif name.startswith("IC"):
                catalog, number_s = "IC", name[2:]
            elif messier is not None:
                catalog, number_s = "M", str(messier)
            else:
                catalog, number_s = "OTH", "0"
            try:
                number = int("".join(ch for ch in number_s if ch.isdigit()) or "0")
            except ValueError:
                number = 0
            key = f"M{messier}" if messier is not None else name
            display = f"M{messier}" if messier is not None else name
            if common:
                display = f"{display} {common}" if messier is not None else f"{name} {common}"
            rows.append((key, catalog, number, display, kind, ra, dec, mag, mag_band, messier))
    return rows


def _parse_openngc_mag(raw: dict) -> tuple[float | None, str | None]:
    """V-Mag bevorzugen; fehlt sie, B-Mag als Fallback (OpenNGC)."""
    for band, key in (("V", "V-Mag"), ("B", "B-Mag")):
        text = (raw.get(key) or "").strip()
        if not text:
            continue
        try:
            return float(text), band
        except ValueError:
            continue
    return None, None


def build_database(
    db_path: Path,
    *,
    hyg: Path | None = None,
    fab: Path | None = None,
    ngc: list[Path] | None = None,
) -> dict[str, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.is_file():
        db_path.unlink()
    stars = _parse_hyg(hyg) if hyg is not None else []
    lines = parse_constellation_fab(fab) if fab is not None else []
    objects: list[tuple] = []
    seen: set[str] = set()
    for path in ngc or []:
        for row in _parse_openngc(path):
            if row[0] in seen:
                continue
            seen.add(row[0])
            objects.append(row)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO stars (hip, ra_deg, dec_deg, mag, name, con) VALUES (?,?,?,?,?,?)",
            stars,
        )
        conn.executemany(
            "INSERT INTO constellation_lines (iau, hip_a, hip_b) VALUES (?,?,?)",
            lines,
        )
        conn.executemany(
            "INSERT INTO dso (key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            objects,
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("imported", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    return {"stars": len(stars), "lines": len(lines), "dso": len(objects)}


def import_catalogs(
    db_path: Path | None = None,
    src_dir: Path | None = None,
    *,
    download: bool = True,
) -> dict[str, int]:
    dest = catalog_db_path(db_path)
    src = src_dir or dest.parent / "src"
    files = ensure_sources(src, download=download)
    if "hygdata_v41.csv" not in files:
        raise FileNotFoundError("HYG-CSV fehlt. Mit Internet: python -m mele.catalog import")
    if "constellationship.fab" not in files:
        raise FileNotFoundError("constellationship.fab fehlt.")
    ngc_files = [files[key] for key in ("NGC.csv", "addendum.csv") if key in files]
    return build_database(
        dest,
        hyg=files["hygdata_v41.csv"],
        fab=files["constellationship.fab"],
        ngc=ngc_files,
    )


def _horizon_alts(profile: HorizonProfile | None, az: np.ndarray) -> np.ndarray:
    if profile is None or not profile.points:
        return np.zeros(az.shape, dtype=np.float64)
    azimuths = np.array([point.az_deg for point in profile.points], dtype=np.float64)
    alts = np.array([point.alt_deg for point in profile.points], dtype=np.float64)
    order = np.argsort(azimuths)
    azimuths = azimuths[order]
    alts = alts[order]
    wrap_az = np.concatenate([azimuths - 360.0, azimuths, azimuths + 360.0])
    wrap_alt = np.concatenate([alts, alts, alts])
    return np.interp(az % 360.0, wrap_az, wrap_alt)


def _mean_az_alt(az: np.ndarray, alt: np.ndarray) -> tuple[float, float]:
    phi = np.radians(90.0 - alt)
    theta = np.radians(az)
    x = np.sin(phi) * np.cos(theta)
    y = np.cos(phi)
    z = np.sin(phi) * np.sin(theta)
    vec = np.array([x.mean(), y.mean(), z.mean()])
    norm = np.linalg.norm(vec)
    if norm < 1e-9:
        return float(az[0]), float(alt[0])
    vec /= norm
    lat = float(np.degrees(np.arcsin(np.clip(vec[1], -1.0, 1.0))))
    lon = float(np.degrees(np.arctan2(vec[2], vec[0]))) % 360.0
    return lon, lat


def normalize_object_query(raw: str) -> str:
    """Normalisiert Nutzereingabe: 'NGC 6960' → 'NGC6960', 'hip 97649' → 'HIP97649'."""
    text = " ".join(str(raw or "").strip().split())
    if not text:
        return ""
    compact = text.replace(" ", "").replace("-", "").upper()
    # M031 / m 31 → M31 (fuehrende Nullen bei Messier weglassen)
    if compact.startswith("M") and compact[1:].isdigit():
        return f"M{int(compact[1:])}"
    if compact.startswith("HIP") and compact[3:].isdigit():
        return f"HIP{int(compact[3:])}"
    if compact.startswith("NGC") and compact[3:].isdigit():
        return f"NGC{int(compact[3:]):04d}" if len(compact[3:]) <= 4 else f"NGC{compact[3:]}"
    if compact.startswith("IC") and compact[2:].isdigit():
        return f"IC{int(compact[2:]):04d}" if len(compact[2:]) <= 4 else f"IC{compact[2:]}"
    return compact


def _dso_kind(row: sqlite3.Row) -> str:
    return "messier" if row["messier"] is not None else "ngc"


def _dso_hit(row: sqlite3.Row) -> dict:
    item = {
        "key": str(row["key"]),
        "id": str(row["key"]),
        "name": str(row["name"] or row["key"]),
        "kind": _dso_kind(row),
        "type": str(row["type"] or ""),
        "ra": round(float(row["ra_deg"]), 5),
        "dec": round(float(row["dec_deg"]), 5),
    }
    if row["mag"] is not None:
        item["mag"] = float(row["mag"])
        band = str(row["mag_band"] or "").strip().upper()
        if band in {"V", "B"}:
            item["mag_band"] = band
    return item


def _star_hit(row: sqlite3.Row) -> dict:
    hip = None if row["hip"] is None else int(row["hip"])
    name = str(row["name"] or "").strip()
    key = f"HIP{hip}" if hip is not None else (f"STAR:{name}" if name else "STAR")
    item = {
        "key": key,
        "id": key,
        "name": name or key,
        "kind": "star",
        "ra": round(float(row["ra_deg"]), 5),
        "dec": round(float(row["dec_deg"]), 5),
    }
    if hip is not None:
        item["hip"] = hip
    if row["mag"] is not None:
        item["mag"] = float(row["mag"])
    if row["con"]:
        item["con"] = str(row["con"])
    return item


def _planet_hits(query: str) -> list[dict]:
    """Namenssuche Mond/Planeten (ohne Ephemeride — nur Trefferliste)."""
    q = query.strip().lower()
    if not q:
        return []
    aliases = [
        ("Sun", "Sonne", "sun"),
        ("Moon", "Mond", "moon"),
        ("Merkur", "Mercury", "planet"),
        ("Venus", "Venus", "planet"),
        ("Mars", "Mars", "planet"),
        ("Jupiter", "Jupiter", "planet"),
        ("Saturn", "Saturn", "planet"),
        ("Uranus", "Uranus", "planet"),
        ("Neptun", "Neptune", "planet"),
    ]
    out: list[dict] = []
    for name_de, name_en, kind in aliases:
        labels = {name_de.lower(), name_en.lower(), kind}
        if q in labels or any(q in label for label in labels):
            out.append(
                {
                    "key": f"{kind}:{name_de}",
                    "id": name_de,
                    "name": name_de,
                    "kind": kind,
                }
            )
    return out


def search_catalog(
    query: str,
    *,
    db_path: Path | None = None,
    limit: int = 20,
) -> list[dict]:
    """Freitextsuche in DSO + benannten Sternen (+ Gestirne). Ohne Az/h."""
    raw = str(query or "").strip()
    if not raw:
        return []
    limit = max(1, min(50, int(limit)))
    norm = normalize_object_query(raw)
    path = catalog_db_path(db_path)
    hits: list[dict] = []
    seen: set[str] = set()

    def _add(item: dict) -> None:
        key = str(item.get("key") or "")
        if not key or key in seen:
            return
        seen.add(key)
        hits.append(item)

    for item in _planet_hits(raw):
        _add(item)
        if len(hits) >= limit:
            return hits[:limit]

    if not catalog_ready(path):
        return hits[:limit]

    like = f"%{raw}%"
    like_norm = f"%{norm}%"
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        # 1) Exakter Key
        if norm:
            row = conn.execute(
                "SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier "
                "FROM dso WHERE upper(key)=? LIMIT 1",
                (norm,),
            ).fetchone()
            if row is not None:
                _add(_dso_hit(row))
            # HIP exakt
            if norm.startswith("HIP") and norm[3:].isdigit():
                hip = int(norm[3:])
                star = conn.execute(
                    "SELECT hip, ra_deg, dec_deg, mag, name, con FROM stars WHERE hip=? LIMIT 1",
                    (hip,),
                ).fetchone()
                if star is not None:
                    _add(_star_hit(star))

        # 2) Key-Prefix / Name
        for row in conn.execute(
            """
            SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier
            FROM dso
            WHERE upper(key) LIKE ? OR upper(key) LIKE ?
               OR name LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE
            ORDER BY
              CASE WHEN upper(key)=? THEN 0
                   WHEN upper(key) LIKE ? THEN 1
                   ELSE 2 END,
              CASE WHEN mag IS NULL THEN 99 ELSE mag END,
              key
            LIMIT ?
            """,
            (f"{norm}%", like_norm, like, like_norm, norm, f"{norm}%", limit),
        ):
            _add(_dso_hit(row))
            if len(hits) >= limit:
                break

        if len(hits) < limit:
            for star in conn.execute(
                """
                SELECT hip, ra_deg, dec_deg, mag, name, con FROM stars
                WHERE name IS NOT NULL AND name != ''
                  AND (name LIKE ? COLLATE NOCASE OR name LIKE ? COLLATE NOCASE)
                ORDER BY CASE WHEN mag IS NULL THEN 99.0 ELSE mag END ASC, name
                LIMIT ?
                """,
                (like, like_norm, limit),
            ):
                _add(_star_hit(star))
                if len(hits) >= limit:
                    break

    return hits[:limit]


def resolve_catalog_object(
    query: str,
    *,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    db_path: Path | None = None,
    profile: HorizonProfile | None = None,
) -> dict | None:
    """Ein Objekt inkl. Az/h — unabhaengig von Messier/NGC-Overlay-Filtern."""
    raw = str(query or "").strip()
    if not raw:
        return None
    stamp = when.astimezone(timezone.utc)
    norm = normalize_object_query(raw)
    path = catalog_db_path(db_path)

    def _with_horizon(item: dict, ra: float, dec: float) -> dict:
        az, alt = radec_to_az_alt(ra, dec, latitude_deg, longitude_deg, stamp)
        above = True
        if profile is not None and profile.points:
            above = float(alt) > profile.altitude_at(float(az))
        out = dict(item)
        out["ra"] = round(float(ra), 5)
        out["dec"] = round(float(dec), 5)
        out["az"] = round(float(az), 3)
        out["alt"] = round(float(alt), 3)
        out["above"] = bool(above)
        out["when"] = stamp.isoformat()
        return out

    def _resolve_body(kind: str, name: str) -> dict | None:
        want = name.lower()
        for body in solar_system_bodies(stamp):
            if body.name.lower() != want and body.key.lower() != want:
                if not (kind in {"sun", "moon"} and body.kind == kind):
                    continue
            item = {
                "key": f"{body.kind}:{body.name}",
                "id": body.key,
                "name": body.name,
                "kind": body.kind,
                "mag": body.mag,
            }
            if body.phase is not None:
                item["phase"] = round(float(body.phase), 3)
            return _with_horizon(item, body.ra_deg, body.dec_deg)
        return None

    # Klare Gestirnsnamen
    qlow = raw.lower()
    body_aliases = {
        "sonne": ("sun", "Sonne"),
        "sun": ("sun", "Sonne"),
        "mond": ("moon", "Mond"),
        "moon": ("moon", "Mond"),
        "merkur": ("planet", "Merkur"),
        "mercury": ("planet", "Merkur"),
        "venus": ("planet", "Venus"),
        "mars": ("planet", "Mars"),
        "jupiter": ("planet", "Jupiter"),
        "saturn": ("planet", "Saturn"),
        "uranus": ("planet", "Uranus"),
        "neptun": ("planet", "Neptun"),
        "neptune": ("planet", "Neptun"),
    }
    if qlow in body_aliases:
        kind, name = body_aliases[qlow]
        found = _resolve_body(kind, name)
        if found is not None:
            return found

    hit: dict | None = None
    if catalog_ready(path):
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = None
            if norm:
                row = conn.execute(
                    "SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier "
                    "FROM dso WHERE upper(key)=? LIMIT 1",
                    (norm,),
                ).fetchone()
                # NGC6960 vs NGC 6960 ohne Zero-Pad-Varianten
                if row is None and norm.startswith("NGC") and norm[3:].isdigit():
                    alt_keys = {f"NGC{int(norm[3:])}", f"NGC{int(norm[3:]):04d}"}
                    for key in alt_keys:
                        row = conn.execute(
                            "SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier "
                            "FROM dso WHERE upper(key)=? LIMIT 1",
                            (key,),
                        ).fetchone()
                        if row is not None:
                            break
                if row is None and norm.startswith("IC") and norm[2:].isdigit():
                    for key in {f"IC{int(norm[2:])}", f"IC{int(norm[2:]):04d}"}:
                        row = conn.execute(
                            "SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier "
                            "FROM dso WHERE upper(key)=? LIMIT 1",
                            (key,),
                        ).fetchone()
                        if row is not None:
                            break
            if row is not None:
                hit = _dso_hit(row)
            elif norm.startswith("HIP") and norm[3:].isdigit():
                star = conn.execute(
                    "SELECT hip, ra_deg, dec_deg, mag, name, con FROM stars WHERE hip=? LIMIT 1",
                    (int(norm[3:]),),
                ).fetchone()
                if star is not None:
                    hit = _star_hit(star)

    if hit is None:
        for cand in search_catalog(raw, db_path=path, limit=8):
            if cand.get("kind") in {"sun", "moon", "planet"}:
                found = _resolve_body(str(cand["kind"]), str(cand["name"]))
                if found is not None:
                    return found
            if cand.get("ra") is not None and cand.get("dec") is not None:
                hit = cand
                break

    if hit is None:
        return None
    return _with_horizon(hit, float(hit["ra"]), float(hit["dec"]))


def query_overlay(
    *,
    db_path: Path | None = None,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    mag_limit: float = 5.5,
    stars: bool = True,
    constellations: bool = True,
    messier: bool = True,
    ngc: bool = False,
    planets: bool = True,
    dso_types: list[str] | set[str] | None = None,
    profile: HorizonProfile | None = None,
) -> dict:
    when_utc = when.astimezone(timezone.utc)
    type_groups = normalize_dso_type_groups(dso_types)
    empty = {
        "when": when_utc.isoformat(),
        "stars": [],
        "lines": [],
        "labels": [],
        "dso": [],
        "bodies": [],
    }
    path = catalog_db_path(db_path)
    ready = catalog_ready(path)
    if not ready and not planets:
        return {
            **empty,
            "error": "Katalog fehlt. Einmal (mit Internet): python -m mele.catalog import",
        }
    star_rows: list = []
    dso_rows: list = []
    line_rows: list = []
    if ready:
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            if stars or constellations:
                star_rows = list(
                    conn.execute(
                        "SELECT hip, ra_deg, dec_deg, mag, name, con FROM stars "
                        "WHERE mag IS NOT NULL AND mag <= ?",
                        (max(mag_limit, 6.5) if constellations else mag_limit,),
                    )
                )
            if messier or ngc:
                if type_groups is not None and not type_groups:
                    dso_rows = []
                else:
                    clauses = []
                    if messier:
                        clauses.append("messier IS NOT NULL")
                    if ngc:
                        clauses.append("(catalog IN ('NGC','IC') AND (mag IS NULL OR mag <= ?))")
                    sql = (
                        "SELECT key, catalog, number, name, type, ra_deg, dec_deg, mag, mag_band, messier "
                        "FROM dso WHERE " + " OR ".join(clauses)
                    )
                    params = (max(mag_limit + 3.0, 9.0),) if ngc else ()
                    dso_rows = list(conn.execute(sql, params))
                    if type_groups is not None:
                        dso_rows = [
                            row
                            for row in dso_rows
                            if dso_row_matches_type_groups(row["type"], type_groups)
                        ]
            if constellations:
                line_rows = list(conn.execute("SELECT iau, hip_a, hip_b FROM constellation_lines"))

    hip_xyz: dict[int, tuple[float, float, float, float]] = {}
    out_stars: list[dict] = []
    if star_rows:
        ra = np.array([row["ra_deg"] for row in star_rows], dtype=np.float64)
        dec = np.array([row["dec_deg"] for row in star_rows], dtype=np.float64)
        az, alt = radec_to_az_alt_many(ra, dec, latitude_deg, longitude_deg, when_utc)
        hlim = _horizon_alts(profile, az)
        for row, az_i, alt_i, limit in zip(star_rows, az, alt, hlim, strict=True):
            hip = row["hip"]
            if hip is not None:
                hip_xyz[int(hip)] = (float(az_i), float(alt_i), float(row["mag"] or 99), float(limit))
            if stars and row["mag"] is not None and row["mag"] <= mag_limit and alt_i > limit:
                item = {
                    "az": round(float(az_i), 3),
                    "alt": round(float(alt_i), 3),
                    "mag": float(row["mag"]),
                    "ra": round(float(row["ra_deg"]), 5),
                    "dec": round(float(row["dec_deg"]), 5),
                }
                if row["name"]:
                    item["name"] = row["name"]
                if hip is not None:
                    item["hip"] = int(hip)
                if row["con"]:
                    item["con"] = row["con"]
                out_stars.append(item)

    out_lines: list[dict] = []
    label_pts: dict[str, list[tuple[float, float]]] = {}
    for row in line_rows:
        a = hip_xyz.get(int(row["hip_a"]))
        b = hip_xyz.get(int(row["hip_b"]))
        if a is None or b is None:
            continue
        if a[1] <= a[3] and b[1] <= b[3]:
            continue
        iau = row["iau"]
        out_lines.append(
            {
                "iau": iau,
                "az1": round(a[0], 3),
                "alt1": round(a[1], 3),
                "az2": round(b[0], 3),
                "alt2": round(b[1], 3),
            }
        )
        if a[1] > a[3]:
            label_pts.setdefault(iau, []).append((a[0], a[1]))
        if b[1] > b[3]:
            label_pts.setdefault(iau, []).append((b[0], b[1]))

    labels = []
    for iau, points in label_pts.items():
        arr = np.array(points, dtype=np.float64)
        az_m, alt_m = _mean_az_alt(arr[:, 0], arr[:, 1])
        labels.append(
            {
                "iau": iau,
                "name": IAU_NAMES.get(iau, iau),
                "az": round(az_m, 3),
                "alt": round(alt_m, 3),
            }
        )

    out_dso: list[dict] = []
    if dso_rows:
        ra = np.array([row["ra_deg"] for row in dso_rows], dtype=np.float64)
        dec = np.array([row["dec_deg"] for row in dso_rows], dtype=np.float64)
        az, alt = radec_to_az_alt_many(ra, dec, latitude_deg, longitude_deg, when_utc)
        hlim = _horizon_alts(profile, az)
        for row, az_i, alt_i, limit in zip(dso_rows, az, alt, hlim, strict=True):
            if alt_i <= limit:
                continue
            kind = "messier" if row["messier"] is not None else "ngc"
            if kind == "messier" and not messier:
                continue
            if kind == "ngc" and not ngc:
                continue
            item = {
                "id": row["key"],
                "name": row["name"],
                "az": round(float(az_i), 3),
                "alt": round(float(alt_i), 3),
                "kind": kind,
                "type": row["type"] or "",
                "ra": round(float(row["ra_deg"]), 5),
                "dec": round(float(row["dec_deg"]), 5),
            }
            if row["mag"] is not None:
                item["mag"] = float(row["mag"])
                band = (row["mag_band"] or "").strip().upper()
                if band in {"V", "B"}:
                    item["mag_band"] = band
            out_dso.append(item)

    out_bodies: list[dict] = []
    if planets:
        raw_bodies = solar_system_bodies(when_utc)
        ra = np.array([body.ra_deg for body in raw_bodies], dtype=np.float64)
        dec = np.array([body.dec_deg for body in raw_bodies], dtype=np.float64)
        az, alt = radec_to_az_alt_many(ra, dec, latitude_deg, longitude_deg, when_utc)
        hlim = _horizon_alts(profile, az)
        placed: list[tuple] = []
        sun_az = sun_alt = None
        for body, az_i, alt_i, limit in zip(raw_bodies, az, alt, hlim, strict=True):
            rec = {
                "id": body.key,
                "name": body.name,
                "az": round(float(az_i), 3),
                "alt": round(float(alt_i), 3),
                "mag": body.mag,
                "kind": body.kind,
                "ra": round(float(body.ra_deg), 5),
                "dec": round(float(body.dec_deg), 5),
            }
            if body.phase is not None:
                rec["phase"] = round(float(body.phase), 3)
            if body.diam_deg is not None:
                rec["diam_deg"] = float(body.diam_deg)
            placed.append((body, rec, float(alt_i), float(limit)))
            if body.kind == "sun":
                sun_az, sun_alt = rec["az"], rec["alt"]
        for _body, rec, alt_i, limit in placed:
            if rec["kind"] == "moon" and sun_az is not None:
                rec["sun_az"] = sun_az
                rec["sun_alt"] = sun_alt
            if alt_i <= limit:
                continue
            out_bodies.append(rec)

    result = {
        "when": when_utc.isoformat(),
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "stars": out_stars,
        "lines": out_lines,
        "labels": labels,
        "dso": out_dso,
        "bodies": out_bodies,
    }
    if not ready:
        result["error"] = "Katalog fehlt. Einmal (mit Internet): python -m mele.catalog import"
    return result


TWILIGHT_MINUTES = 60
LIGHT_NIGHT = "night"
LIGHT_TWILIGHT = "twilight"
LIGHT_DAY = "day"


def _sun_altitudes(
    stamps: list[datetime],
    latitude_deg: float,
    longitude_deg: float,
) -> np.ndarray:
    alts = np.empty(len(stamps), dtype=np.float64)
    for index, stamp in enumerate(stamps):
        ra_deg, dec_deg = sun_radec(stamp)
        _, alts[index] = radec_to_az_alt(ra_deg, dec_deg, latitude_deg, longitude_deg, stamp)
    return alts


def _horizon_crossings(stamps: list[datetime], alts: np.ndarray) -> tuple[list[datetime], list[datetime]]:
    rises: list[datetime] = []
    sets: list[datetime] = []
    for index in range(len(alts) - 1):
        start_alt = float(alts[index])
        end_alt = float(alts[index + 1])
        delta = stamps[index + 1] - stamps[index]
        if start_alt < 0.0 <= end_alt:
            frac = 0.0 if end_alt == start_alt else (-start_alt) / (end_alt - start_alt)
            rises.append(stamps[index] + delta * frac)
        elif start_alt >= 0.0 > end_alt:
            frac = 0.0 if start_alt == end_alt else start_alt / (start_alt - end_alt)
            sets.append(stamps[index] + delta * frac)
    return rises, sets


def _sun_events(
    day: datetime,
    latitude_deg: float,
    longitude_deg: float,
    step_min: int,
    twilight_min: int,
) -> tuple[list[datetime], list[datetime]]:
    pad = timedelta(minutes=twilight_min + step_min)
    start = day - pad
    end = day + timedelta(days=1) + pad
    count = int((end - start).total_seconds() // (step_min * 60)) + 1
    stamps = [start + timedelta(minutes=index * step_min) for index in range(count)]
    return _horizon_crossings(stamps, _sun_altitudes(stamps, latitude_deg, longitude_deg))


def classify_daylight(
    stamps: list[datetime],
    sun_alts: np.ndarray,
    events: list[datetime],
    twilight_min: int = TWILIGHT_MINUTES,
) -> list[str]:
    """Nacht / Daemmerung (±twilight_min um Auf- und Untergang) / Tag."""
    limit = twilight_min * 60.0
    phases: list[str] = []
    for stamp, alt in zip(stamps, sun_alts, strict=True):
        near = events and min(abs((stamp - event).total_seconds()) for event in events) <= limit
        if near:
            phases.append(LIGHT_TWILIGHT)
        elif float(alt) > 0.0:
            phases.append(LIGHT_DAY)
        else:
            phases.append(LIGHT_NIGHT)
    return phases


def daylight_phases_for_stamps(
    stamps: list[datetime],
    latitude_deg: float,
    longitude_deg: float,
    *,
    twilight_min: int = TWILIGHT_MINUTES,
) -> list[str]:
    """Klassifiziert Zeitstempel am Standort als night / twilight / day."""
    if not stamps:
        return []
    sun_alts = _sun_altitudes(stamps, latitude_deg, longitude_deg)
    rises, sets = _horizon_crossings(stamps, sun_alts)
    return classify_daylight(stamps, sun_alts, rises + sets, twilight_min)


def _phase_windows(
    stamps: list[datetime],
    above: np.ndarray,
    lights: list[str],
    alts: np.ndarray,
    step_min: int,
) -> list[dict]:
    windows: list[dict] = []
    start: int | None = None
    peak = -99.0
    current: str | None = None
    for index, is_up in enumerate(above):
        light = lights[index]
        if is_up and light == current and start is not None:
            peak = max(peak, float(alts[index]))
            continue
        if start is not None and current is not None:
            windows.append(
                {
                    "start": stamps[start].isoformat(),
                    "end": stamps[index].isoformat(),
                    "max_alt": round(peak, 2),
                    "light": current,
                }
            )
            start = None
            current = None
        if is_up:
            start = index
            peak = float(alts[index])
            current = light
    if start is not None and current is not None:
        windows.append(
            {
                "start": stamps[start].isoformat(),
                "end": (stamps[-1] + timedelta(minutes=step_min)).isoformat(),
                "max_alt": round(peak, 2),
                "light": current,
            }
        )
    return windows


def visibility_summary(track: dict) -> dict:
    """Kennzahlen: ueber Horizont vs. beobachtbar (Nacht ∩ Horizont)."""
    windows = track.get("windows") if isinstance(track.get("windows"), list) else []
    above = [slot for slot in windows if slot.get("light")]
    observable = [slot for slot in windows if slot.get("light") == LIGHT_NIGHT]

    def slot_minutes(slot: dict) -> float:
        try:
            start = datetime.fromisoformat(str(slot["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(slot["end"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            return 0.0
        return max(0.0, (end - start).total_seconds() / 60.0)

    above_min = sum(slot_minutes(slot) for slot in above)
    obs_min = sum(slot_minutes(slot) for slot in observable)
    above_alts = [float(slot["max_alt"]) for slot in above if slot.get("max_alt") is not None]
    obs_alts = [float(slot["max_alt"]) for slot in observable if slot.get("max_alt") is not None]
    return {
        "above_horizon_min": round(above_min, 1),
        "above_horizon_h": round(above_min / 60.0, 2),
        "above_max_alt": round(max(above_alts), 2) if above_alts else None,
        "above_windows": above,
        "observable_min": round(obs_min, 1),
        "observable_h": round(obs_min / 60.0, 2),
        "observable_max_alt": round(max(obs_alts), 2) if obs_alts else None,
        "observable_windows": observable,
        "twilight_min": track.get("twilight_min"),
        "sunrise": track.get("sunrise"),
        "sunset": track.get("sunset"),
    }


def observing_night_start_utc(
    when: datetime,
    *,
    longitude_deg: float,
    tz_offset_min: int | None = None,
) -> datetime:
    """Lokaler Mittag vor der Beobachtungsnacht von `when` (Mittag→Mittag).

    Kalendertag 00:00–24:00 wuerde die Nacht an Mitternacht zerschneiden
    (z.B. 20:00–02:00 und 02:00–03:30 als zwei Fenster).
    """
    when_utc = when.astimezone(timezone.utc)
    if tz_offset_min is None:
        tz_offset_min = int(round(float(longitude_deg) / 15.0 * 60.0))
    offset = timedelta(minutes=int(tz_offset_min))
    local = when_utc + offset
    local_date = local.date()
    if (local.hour, local.minute, local.second, local.microsecond) < (12, 0, 0, 0):
        local_date = local_date - timedelta(days=1)
    noon_as_utc_label = datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        12,
        0,
        0,
        tzinfo=timezone.utc,
    )
    return noon_as_utc_label - offset


def object_track(
    *,
    ra_deg: float,
    dec_deg: float,
    latitude_deg: float,
    longitude_deg: float,
    when: datetime,
    profile: HorizonProfile | None = None,
    step_min: int = 15,
    tz_offset_min: int | None = None,
) -> dict:
    """Az/h ueber die Beobachtungsnacht (lokal Mittag→Mittag), plus Zeitfenster."""
    when_utc = when.astimezone(timezone.utc)
    if tz_offset_min is None:
        tz_offset_min = int(round(float(longitude_deg) / 15.0 * 60.0))
    day = observing_night_start_utc(
        when_utc,
        longitude_deg=longitude_deg,
        tz_offset_min=tz_offset_min,
    )
    stamps = [day + timedelta(minutes=index * step_min) for index in range((24 * 60) // step_min)]
    azs = np.empty(len(stamps), dtype=np.float64)
    alts = np.empty(len(stamps), dtype=np.float64)
    for index, stamp in enumerate(stamps):
        azs[index], alts[index] = radec_to_az_alt(ra_deg, dec_deg, latitude_deg, longitude_deg, stamp)
    hlim = _horizon_alts(profile, azs)
    above = alts > hlim
    sun_alts = _sun_altitudes(stamps, latitude_deg, longitude_deg)
    rises, sets = _sun_events(day, latitude_deg, longitude_deg, step_min, TWILIGHT_MINUTES)
    lights = classify_daylight(stamps, sun_alts, rises + sets, TWILIGHT_MINUTES)
    points = [
        {
            "az": round(float(azs[i]), 3),
            "alt": round(float(alts[i]), 3),
            "above": bool(above[i]),
            "light": lights[i],
            "when": stamps[i].isoformat(),
        }
        for i in range(len(stamps))
    ]
    day_end = day + timedelta(days=1)
    in_day = [event for event in rises if day <= event < day_end]
    in_set = [event for event in sets if day <= event < day_end]
    track = {
        "when": when_utc.isoformat(),
        "ra": ra_deg,
        "dec": dec_deg,
        "night_start": day.isoformat(),
        "tz_offset_min": int(tz_offset_min),
        "points": points,
        "windows": _phase_windows(stamps, above, lights, alts, step_min),
        "sunrise": in_day[0].isoformat() if in_day else None,
        "sunset": in_set[0].isoformat() if in_set else None,
        "twilight_min": TWILIGHT_MINUTES,
        "step_min": step_min,
    }
    track["summary"] = visibility_summary(track)
    return track


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mele.catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import", help="Kataloge laden und sky.sqlite bauen")
    imp.add_argument("--src", type=Path, help="Ordner mit bereits heruntergeladenen Dateien")
    imp.add_argument("--db", type=Path, help="Ziel-SQLite")
    imp.add_argument("--no-download", action="store_true")
    info = sub.add_parser("info", help="zeigt, ob die lokale DB da ist")
    args = parser.parse_args(argv)
    if args.command == "info":
        path = catalog_db_path()
        print(path)
        print("bereit" if catalog_ready(path) else "fehlt")
        return 0
    if args.command == "import":
        stats = import_catalogs(args.db, args.src, download=not args.no_download)
        dest = catalog_db_path(args.db)
        print(f"SQLite  {dest}")
        print(f"Sterne  {stats['stars']}")
        print(f"Linien  {stats['lines']}")
        print(f"DSO     {stats['dso']}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
