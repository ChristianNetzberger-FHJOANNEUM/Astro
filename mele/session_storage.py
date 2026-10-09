"""Session-Storage S1: Manifest, Lifecycle, WORK-Pfadzuordnung (ohne Copy/Delete).

Siehe wiki/knowledge/mele-session-storage-weather-archive-spec.md (Rev. 3.1).
Produktive Transfers (S3–S5) kommen spaeter. Close/Wetterexport: siehe session_close / session_weather.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

MANIFEST_SCHEMA_VERSION = 1

LIFECYCLE_OPEN = "open"
LIFECYCLE_CAPTURING = "capturing"
LIFECYCLE_CLOSED = "closed"
LIFECYCLE_STATUSES = frozenset({LIFECYCLE_OPEN, LIFECYCLE_CAPTURING, LIFECYCLE_CLOSED})

# Erlaubte Uebergaenge (S1 State-Machine; NINA-Idle-Check erst bei Close-UI)
_LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    LIFECYCLE_OPEN: frozenset({LIFECYCLE_CAPTURING, LIFECYCLE_CLOSED}),
    LIFECYCLE_CAPTURING: frozenset({LIFECYCLE_CLOSED}),
    LIFECYCLE_CLOSED: frozenset(),  # kein Re-Open in v1
}

ARCHIVE_COMPLETENESS_NONE = "none"
ARCHIVE_COMPLETENESS_PARTIAL = "partial"
ARCHIVE_COMPLETENESS_COMPLETE = "complete"
ARCHIVE_COMPLETENESS_STALE = "stale"
ARCHIVE_COMPLETENESS = frozenset(
    {
        ARCHIVE_COMPLETENESS_NONE,
        ARCHIVE_COMPLETENESS_PARTIAL,
        ARCHIVE_COMPLETENESS_COMPLETE,
        ARCHIVE_COMPLETENESS_STALE,
    }
)

WEATHER_EXPORT_NONE = "none"
WEATHER_EXPORT_OK = "ok"
WEATHER_EXPORT_PARTIAL = "partial"
WEATHER_EXPORT_UNAVAILABLE = "unavailable"
WEATHER_EXPORT_STATUSES = frozenset(
    {
        WEATHER_EXPORT_NONE,
        WEATHER_EXPORT_OK,
        WEATHER_EXPORT_PARTIAL,
        WEATHER_EXPORT_UNAVAILABLE,
    }
)

TRANSFER_KIND_CAPTURE_TO_ARCHIVE = "capture_to_archive"
TRANSFER_KIND_CAPTURE_TO_WORK = "capture_to_work"
TRANSFER_KIND_WORK_TO_ARCHIVE = "work_to_archive"
TRANSFER_KINDS = frozenset(
    {
        TRANSFER_KIND_CAPTURE_TO_ARCHIVE,
        TRANSFER_KIND_CAPTURE_TO_WORK,
        TRANSFER_KIND_WORK_TO_ARCHIVE,
    }
)

TRANSFER_QUEUED = "queued"
TRANSFER_COPYING = "copying"
TRANSFER_VERIFYING = "verifying"
TRANSFER_COMPLETED = "completed"
TRANSFER_FAILED = "failed"
TRANSFER_STATUSES = frozenset(
    {
        TRANSFER_QUEUED,
        TRANSFER_COPYING,
        TRANSFER_VERIFYING,
        TRANSFER_COMPLETED,
        TRANSFER_FAILED,
    }
)

JOB_COMPLETENESS_PARTIAL = "partial"
JOB_COMPLETENESS_FULL = "full"
JOB_COMPLETENESS = frozenset({JOB_COMPLETENESS_PARTIAL, JOB_COMPLETENESS_FULL})

DEFAULT_SIRIL_HOME_DIRNAME = "siril_home"


class LifecycleError(ValueError):
    """Ungueltiger Lifecycle-Uebergang."""


class ManifestError(ValueError):
    """Manifest ungueltig oder Konflikt."""


@dataclass(frozen=True)
class ManifestConflict:
    path: str
    existing_sha256: str
    new_sha256: str
    existing_size: int
    new_size: int


def normalize_lifecycle(value: str | None) -> str:
    raw = str(value or LIFECYCLE_OPEN).strip().lower()
    return raw if raw in LIFECYCLE_STATUSES else LIFECYCLE_OPEN


def normalize_archive_completeness(value: str | None) -> str:
    raw = str(value or ARCHIVE_COMPLETENESS_NONE).strip().lower()
    return raw if raw in ARCHIVE_COMPLETENESS else ARCHIVE_COMPLETENESS_NONE


def normalize_weather_export_status(value: str | None) -> str:
    raw = str(value or WEATHER_EXPORT_NONE).strip().lower()
    return raw if raw in WEATHER_EXPORT_STATUSES else WEATHER_EXPORT_NONE


def can_transition_lifecycle(current: str, target: str) -> bool:
    cur = normalize_lifecycle(current)
    tgt = normalize_lifecycle(target)
    if cur == tgt:
        return True
    return tgt in _LIFECYCLE_TRANSITIONS.get(cur, frozenset())


def assert_lifecycle_transition(current: str, target: str) -> None:
    if not can_transition_lifecycle(current, target):
        raise LifecycleError(
            f"Lifecycle-Uebergang nicht erlaubt: {normalize_lifecycle(current)} → {normalize_lifecycle(target)}"
        )


def mark_archive_stale_after_new_files(current: str) -> str:
    """Nach zusaetzlichen Master/Results: complete → stale; partial bleibt partial."""
    cur = normalize_archive_completeness(current)
    if cur == ARCHIVE_COMPLETENESS_COMPLETE:
        return ARCHIVE_COMPLETENESS_STALE
    return cur


def session_relative_under_root(
    catalog_key: str,
    *,
    when: datetime | None = None,
    display_name: str | None = None,
    session_id: int | None = None,
) -> Path:
    """Relativpfad Object/Datum[/s#####] — gemeinsam fuer CAPTURE/WORK/ARCHIVE."""
    from mele.astro_manager import folder_slug, session_dir_slug

    stamp = when or datetime.now().astimezone()
    path = Path(folder_slug(catalog_key, display_name)) / stamp.strftime("%Y-%m-%d")
    if session_id is not None:
        path = path / session_dir_slug(session_id)
    return path


def map_work_paths(
    relative_session: str | Path,
    *,
    work_transfer_root: Path | None,
    work_local_root: Path | None,
) -> tuple[Path | None, Path | None]:
    """UNC-Transferpfad und Notebook-Lokalpfad aus gemeinsamer Relativstruktur."""
    rel = Path(str(relative_session).replace("\\", "/").lstrip("/"))
    transfer = (work_transfer_root / rel) if work_transfer_root else None
    local = (work_local_root / rel) if work_local_root else None
    return transfer, local


def siril_home_dir(work_session_root: Path, *, dirname: str = DEFAULT_SIRIL_HOME_DIRNAME) -> Path:
    name = (dirname or DEFAULT_SIRIL_HOME_DIRNAME).strip() or DEFAULT_SIRIL_HOME_DIRNAME
    return Path(work_session_root) / name


def suggested_work_transfer_session_dir(
    catalog_key: str,
    *,
    when: datetime | None = None,
    work_transfer_root: Path | None = None,
    display_name: str | None = None,
    session_id: int | None = None,
) -> Path | None:
    from mele.config import load_mele_settings

    root = work_transfer_root
    if root is None:
        root = load_mele_settings().work_transfer_root
    if root is None:
        return None
    return root / session_relative_under_root(
        catalog_key, when=when, display_name=display_name, session_id=session_id
    )


def suggested_work_local_session_dir(
    catalog_key: str,
    *,
    when: datetime | None = None,
    work_local_root: Path | None = None,
    display_name: str | None = None,
    session_id: int | None = None,
) -> Path | None:
    from mele.config import load_mele_settings

    root = work_local_root
    if root is None:
        root = load_mele_settings().work_local_root
    if root is None:
        return None
    return root / session_relative_under_root(
        catalog_key, when=when, display_name=display_name, session_id=session_id
    )


def empty_manifest(
    *,
    session_id: str | int,
    object_name: str = "",
    capture_date: str = "",
    lifecycle_at_source: str = LIFECYCLE_OPEN,
    completeness: str = JOB_COMPLETENESS_PARTIAL,
    revision: int = 0,
    generated_utc: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "revision": max(0, int(revision)),
        "session_id": str(session_id),
        "object": str(object_name or ""),
        "capture_date": str(capture_date or ""),
        "lifecycle_at_source": normalize_lifecycle(lifecycle_at_source),
        "completeness": (
            completeness
            if completeness in JOB_COMPLETENESS
            else JOB_COMPLETENESS_PARTIAL
        ),
        "generated_utc": str(generated_utc or ""),
        "files": [],
    }


def validate_manifest(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ManifestError("Manifest muss ein Objekt sein")
    try:
        schema = int(data.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise ManifestError("schema_version fehlt oder ungueltig") from exc
    if schema != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"Unbekannte schema_version: {schema}")
    try:
        revision = int(data.get("revision"))
    except (TypeError, ValueError) as exc:
        raise ManifestError("revision fehlt oder ungueltig") from exc
    if revision < 0:
        raise ManifestError("revision muss >= 0 sein")
    files = data.get("files")
    if not isinstance(files, list):
        raise ManifestError("files muss eine Liste sein")
    normalized_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, Mapping):
            raise ManifestError("files-Eintrag ungueltig")
        path = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not path or path.startswith("..") or "/../" in f"/{path}/":
            raise ManifestError(f"Ungueltiger Relativpfad: {item.get('path')!r}")
        try:
            size = int(item.get("size"))
            sha = str(item.get("sha256") or "").strip().lower()
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"size/sha256 ungueltig fuer {path}") from exc
        if size < 0 or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ManifestError(f"size/sha256 ungueltig fuer {path}")
        normalized_files.append({"path": path, "size": size, "sha256": sha})
    out = dict(data)
    out["schema_version"] = schema
    out["revision"] = revision
    out["files"] = normalized_files
    out["lifecycle_at_source"] = normalize_lifecycle(str(data.get("lifecycle_at_source") or ""))
    comp = str(data.get("completeness") or JOB_COMPLETENESS_PARTIAL)
    out["completeness"] = comp if comp in JOB_COMPLETENESS else JOB_COMPLETENESS_PARTIAL
    return out


def find_manifest_conflicts(
    existing_files: Iterable[Mapping[str, Any]],
    incoming_files: Iterable[Mapping[str, Any]],
) -> list[ManifestConflict]:
    """Gleicher Relativpfad, anderer Hash → Konflikt (kein silent overwrite)."""
    by_path: dict[str, tuple[str, int]] = {}
    for item in existing_files:
        path = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not path:
            continue
        by_path[path] = (str(item.get("sha256") or "").lower(), int(item.get("size") or 0))
    conflicts: list[ManifestConflict] = []
    for item in incoming_files:
        path = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not path or path not in by_path:
            continue
        old_sha, old_size = by_path[path]
        new_sha = str(item.get("sha256") or "").lower()
        new_size = int(item.get("size") or 0)
        if old_sha and new_sha and old_sha != new_sha:
            conflicts.append(
                ManifestConflict(
                    path=path,
                    existing_sha256=old_sha,
                    new_sha256=new_sha,
                    existing_size=old_size,
                    new_size=new_size,
                )
            )
    return conflicts


def merge_manifest_files(
    existing: Mapping[str, Any],
    incoming_files: Iterable[Mapping[str, Any]],
    *,
    generated_utc: str = "",
    lifecycle_at_source: str | None = None,
    completeness: str | None = None,
) -> dict[str, Any]:
    """Neue Dateien ergaenzen; bei Hash-Konflikt ManifestError. revision += 1 wenn Inhalt aendert."""
    base = validate_manifest(existing)
    incoming = list(incoming_files)
    conflicts = find_manifest_conflicts(base["files"], incoming)
    if conflicts:
        paths = ", ".join(c.path for c in conflicts[:5])
        raise ManifestError(f"Manifest-Konflikt (Hash): {paths}")

    by_path = {f["path"]: dict(f) for f in base["files"]}
    changed = False
    for item in incoming:
        path = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if not path:
            continue
        entry = {
            "path": path,
            "size": int(item["size"]),
            "sha256": str(item["sha256"]).strip().lower(),
        }
        prev = by_path.get(path)
        if prev is None:
            by_path[path] = entry
            changed = True
        elif prev["sha256"] != entry["sha256"] or prev["size"] != entry["size"]:
            # sollte durch find_manifest_conflicts abgefangen sein
            raise ManifestError(f"Manifest-Konflikt (Hash): {path}")

    out = dict(base)
    out["files"] = sorted(by_path.values(), key=lambda f: f["path"])
    if changed:
        out["revision"] = int(base["revision"]) + 1
    if generated_utc:
        out["generated_utc"] = generated_utc
    if lifecycle_at_source is not None:
        out["lifecycle_at_source"] = normalize_lifecycle(lifecycle_at_source)
    if completeness is not None:
        out["completeness"] = (
            completeness if completeness in JOB_COMPLETENESS else JOB_COMPLETENESS_PARTIAL
        )
    return validate_manifest(out)
