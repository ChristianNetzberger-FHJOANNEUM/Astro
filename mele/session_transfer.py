"""Verifizierte Session-Transfers: CAPTURE→WORK (S3), CAPTURE→ARCHIVE (S4), WORK→ARCHIVE (S5).

SHA-256-Manifest, kein silent overwrite. ARCHIVE: CAPTURE überspringt results/; S5 liefert sie.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mele.astro_manager import (
    create_transfer_job,
    get_session,
    resolve_archive_session_dir,
    suggested_archive_session_dir,
    update_session,
    update_session_storage_fields,
    update_transfer_job_status,
)
from mele.config import load_mele_settings
from mele.session_storage import (
    ARCHIVE_COMPLETENESS_COMPLETE,
    ARCHIVE_COMPLETENESS_PARTIAL,
    DEFAULT_SIRIL_HOME_DIRNAME,
    JOB_COMPLETENESS_FULL,
    JOB_COMPLETENESS_PARTIAL,
    LIFECYCLE_CLOSED,
    ManifestError,
    TRANSFER_KIND_CAPTURE_TO_ARCHIVE,
    TRANSFER_KIND_CAPTURE_TO_WORK,
    TRANSFER_KIND_WORK_TO_ARCHIVE,
    empty_manifest,
    merge_manifest_files,
    suggested_work_local_session_dir,
    suggested_work_transfer_session_dir,
    validate_manifest,
)

STABLE_WINDOW_S = 2.0
MANIFEST_NAME = "session-manifest.json"
TRANSFER_LOG_WORK = "transfer-work.log"
TRANSFER_LOG_ARCHIVE = "transfer-archive.log"
TRANSFER_LOG_WORK_ARCHIVE = "transfer-work-archive.log"
# CAPTURE→ARCHIVE kopiert diese Top-Level-Ordner nie (Results nur via S5)
_ARCHIVE_SKIP_TOP = frozenset({"results", "siril_home"})
# WORK→ARCHIVE: siril_home nie; results + Master + weather/meta ja
_W2A_DENY_TOP = frozenset({"siril_home"})


class TransferError(RuntimeError):
    """Transfer abgebrochen (Config, Space, Conflict, …)."""


@dataclass
class PushWorkResult:
    ok: bool
    job_id: str = ""
    session: dict[str, Any] = field(default_factory=dict)
    work_transfer_path: str = ""
    work_local_path: str = ""
    siril_home_local: str = ""
    files_copied: int = 0
    files_skipped: int = 0
    bytes_copied: int = 0
    manifest_revision: int = 0
    completeness: str = JOB_COMPLETENESS_PARTIAL
    error: str = ""
    log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "job_id": self.job_id,
            "session": self.session,
            "work_transfer_path": self.work_transfer_path,
            "work_local_path": self.work_local_path,
            "siril_home_local": self.siril_home_local,
            "files_copied": self.files_copied,
            "files_skipped": self.files_skipped,
            "bytes_copied": self.bytes_copied,
            "manifest_revision": self.manifest_revision,
            "completeness": self.completeness,
            "error": self.error,
            "log_path": self.log_path,
        }


@dataclass
class PushArchiveResult:
    ok: bool
    job_id: str = ""
    session: dict[str, Any] = field(default_factory=dict)
    archive_path: str = ""
    files_copied: int = 0
    files_skipped: int = 0
    bytes_copied: int = 0
    manifest_revision: int = 0
    completeness: str = JOB_COMPLETENESS_PARTIAL
    archive_completeness: str = ARCHIVE_COMPLETENESS_PARTIAL
    error: str = ""
    log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "job_id": self.job_id,
            "session": self.session,
            "archive_path": self.archive_path,
            "files_copied": self.files_copied,
            "files_skipped": self.files_skipped,
            "bytes_copied": self.bytes_copied,
            "manifest_revision": self.manifest_revision,
            "completeness": self.completeness,
            "archive_completeness": self.archive_completeness,
            "error": self.error,
            "log_path": self.log_path,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def wait_until_stable(
    path: Path,
    *,
    window_s: float = STABLE_WINDOW_S,
    skip_wait: bool = False,
) -> tuple[int, float]:
    """Wartet bis Größe+mtime stabil. Liefert (size, mtime)."""
    if not path.is_file():
        raise TransferError(f"Datei fehlt: {path}")
    st1 = path.stat()
    if skip_wait:
        return int(st1.st_size), float(st1.st_mtime)
    time.sleep(max(0.05, float(window_s)))
    st2 = path.stat()
    if int(st1.st_size) != int(st2.st_size) or float(st1.st_mtime) != float(st2.st_mtime):
        time.sleep(max(0.05, float(window_s)))
        st2 = path.stat()
    return int(st2.st_size), float(st2.st_mtime)


def iter_relative_files(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    out: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            out.append(path.relative_to(root))
    return sorted(out, key=lambda p: str(p).replace("\\", "/").lower())


def _rel_key(rel: Path | str) -> str:
    return str(rel).replace("\\", "/").lstrip("/")


def estimate_source_bytes(root: Path, rels: list[Path]) -> int:
    total = 0
    for rel in rels:
        try:
            total += int((root / rel).stat().st_size)
        except OSError:
            continue
    return total


def check_free_space(dest_root: Path, need_bytes: int) -> None:
    """Wirft TransferError wenn zu wenig Platz (mit 64 MiB Reserve)."""
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        usage = shutil.disk_usage(str(dest_root))
    except OSError as exc:
        raise TransferError(f"Freier Speicher nicht pruefbar: {exc}") from exc
    reserve = 64 * 1024 * 1024
    if int(usage.free) < int(need_bytes) + reserve:
        raise TransferError(
            f"Zu wenig Speicher am WORK-Ziel: frei={usage.free}, benoetigt≈{need_bytes + reserve}"
        )


def _append_log(log_path: Path, line: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{_utc_now()} {line}\n")


def _load_dest_manifest(dest: Path) -> dict[str, Any] | None:
    path = dest / MANIFEST_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return validate_manifest(data)
    except (OSError, json.JSONDecodeError, ManifestError):
        return None


def _write_manifest_atomic(dest: Path, manifest: dict[str, Any]) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / MANIFEST_NAME
    partial = dest / f"{MANIFEST_NAME}.partial"
    payload = validate_manifest(manifest)
    partial.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    partial.replace(final)
    return final


def ensure_work_dirs(dest: Path, *, siril_home_dirname: str) -> None:
    """siril_home + results anlegen falls fehlend — Inhalt nie loeschen."""
    name = (siril_home_dirname or DEFAULT_SIRIL_HOME_DIRNAME).strip() or DEFAULT_SIRIL_HOME_DIRNAME
    (dest / name).mkdir(parents=True, exist_ok=True)
    (dest / "results").mkdir(parents=True, exist_ok=True)


def storage_paths_payload(settings: Any | None = None) -> dict[str, Any]:
    cfg = settings or load_mele_settings()
    wt = getattr(cfg, "work_transfer_root", None)
    wl = getattr(cfg, "work_local_root", None)
    siril = str(getattr(cfg, "siril_home_dirname", None) or DEFAULT_SIRIL_HOME_DIRNAME)
    return {
        "local_capture_root": str(cfg.local_capture_root),
        "archive_root": str(cfg.archive_root),
        "work_transfer_root": str(wt) if wt else "",
        "work_local_root": str(wl) if wl else "",
        "siril_home_dirname": siril,
        "work_configured": bool(wt),
        "archive_configured": bool(str(getattr(cfg, "archive_root", "") or "").strip()),
        "config_file": "configs/mele.yaml",
    }


def _session_when(session: Any) -> datetime | None:
    try:
        if session.started_utc:
            return datetime.fromisoformat(str(session.started_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    return None


def _top_dir(rel_key: str) -> str:
    return rel_key.split("/", 1)[0].lower() if rel_key else ""


def _copy_verified_tree(
    *,
    source: Path,
    dest: Path,
    rels: list[Path],
    job_id: str,
    skip_stable_wait: bool,
    stable_window_s: float,
    db_path: Path | None,
    conflict_label: str,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Copy+verify relative files. Returns copied, skipped, bytes, manifest entries."""
    copied = 0
    skipped = 0
    bytes_copied = 0
    new_entries: list[dict[str, Any]] = []

    for rel in rels:
        key = _rel_key(rel)
        src_file = source / rel
        dst_file = dest / rel

        size, _mtime = wait_until_stable(
            src_file,
            window_s=stable_window_s,
            skip_wait=skip_stable_wait,
        )
        src_hash = sha256_file(src_file)

        if dst_file.is_file():
            dst_size = int(dst_file.stat().st_size)
            dst_hash = sha256_file(dst_file)
            if dst_hash == src_hash and dst_size == size:
                skipped += 1
                new_entries.append({"path": key, "size": size, "sha256": src_hash})
                continue
            raise TransferError(
                f"Konflikt: {key} existiert am {conflict_label}-Ziel mit anderem Hash "
                f"(src={src_hash[:12]}… dest={dst_hash[:12]}…)"
            )

        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        verify_hash = sha256_file(dst_file)
        if verify_hash != src_hash:
            raise TransferError(f"Verify fehlgeschlagen nach Copy: {key}")
        copied += 1
        bytes_copied += size
        new_entries.append({"path": key, "size": size, "sha256": src_hash})
        if (copied + skipped) % 10 == 0:
            update_transfer_job_status(
                job_id,
                status="copying",
                progress_files=copied + skipped,
                progress_bytes=bytes_copied,
                db_path=db_path,
            )
    return copied, skipped, bytes_copied, new_entries


def push_capture_to_work(
    session_id: int,
    *,
    db_path: Path | None = None,
    work_transfer_root: Path | None = None,
    work_local_root: Path | None = None,
    siril_home_dirname: str | None = None,
    stable_window_s: float = STABLE_WINDOW_S,
) -> PushWorkResult:
    """CAPTURE-Session verifiziert nach WORK kopieren."""
    settings = load_mele_settings()
    wt_root = work_transfer_root if work_transfer_root is not None else settings.work_transfer_root
    wl_root = work_local_root if work_local_root is not None else settings.work_local_root
    siril_name = (
        (siril_home_dirname or settings.siril_home_dirname or DEFAULT_SIRIL_HOME_DIRNAME).strip()
        or DEFAULT_SIRIL_HOME_DIRNAME
    )

    session = get_session(session_id, db_path=db_path)
    if session is None:
        return PushWorkResult(ok=False, error=f"Unbekannte Session: {session_id}")
    if not wt_root:
        return PushWorkResult(
            ok=False,
            error=(
                "work_transfer_root nicht gesetzt — in configs/mele.yaml eintragen "
                "(UNC zum Notebook, z.B. //NOTEBOOK/AstroWork/Mele)"
            ),
        )

    source = Path(str(session.local_path or "").strip())
    if not source.is_dir():
        return PushWorkResult(
            ok=False,
            error=f"CAPTURE-Pfad fehlt oder kein Ordner: {session.local_path!r}",
        )

    when = _session_when(session)
    dest = suggested_work_transfer_session_dir(
        session.catalog_key,
        when=when,
        work_transfer_root=Path(wt_root),
        session_id=session.id,
    )
    assert dest is not None
    local_display = suggested_work_local_session_dir(
        session.catalog_key,
        when=when,
        work_local_root=Path(wl_root) if wl_root else None,
        session_id=session.id,
    )
    local_str = str(local_display) if local_display else ""
    siril_local = str(Path(local_str) / siril_name) if local_str else ""

    completeness = (
        JOB_COMPLETENESS_FULL
        if session.lifecycle_status == LIFECYCLE_CLOSED
        else JOB_COMPLETENESS_PARTIAL
    )
    skip_stable_wait = session.lifecycle_status == LIFECYCLE_CLOSED
    skip_names = {MANIFEST_NAME.lower(), TRANSFER_LOG_WORK.lower(), TRANSFER_LOG_ARCHIVE.lower()}

    rels = [
        rel
        for rel in iter_relative_files(source)
        if _rel_key(rel).lower() not in skip_names
    ]
    need = estimate_source_bytes(source, rels)
    check_free_space(dest, need)

    log_path = dest / TRANSFER_LOG_WORK
    job = create_transfer_job(
        session_id=session.id,
        kind=TRANSFER_KIND_CAPTURE_TO_WORK,
        source_root=str(source),
        dest_root=str(dest),
        completeness=completeness,
        manifest_revision=int(session.manifest_revision or 0),
        db_path=db_path,
    )
    _append_log(log_path, f"START job={job.job_id} src={source} dest={dest}")

    try:
        update_transfer_job_status(job.job_id, status="copying", log_path=str(log_path), db_path=db_path)
        dest.mkdir(parents=True, exist_ok=True)
        existing_manifest = _load_dest_manifest(dest)
        copied, skipped, bytes_copied, new_entries = _copy_verified_tree(
            source=source,
            dest=dest,
            rels=rels,
            job_id=job.job_id,
            skip_stable_wait=skip_stable_wait,
            stable_window_s=stable_window_s,
            db_path=db_path,
            conflict_label="WORK",
        )
        update_transfer_job_status(
            job.job_id,
            status="verifying",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            db_path=db_path,
        )
        ensure_work_dirs(dest, siril_home_dirname=siril_name)
        base = existing_manifest or empty_manifest(
            session_id=session.id,
            object_name=session.catalog_key,
            capture_date=str(dest.parent.name),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
            revision=int(session.manifest_revision or 0),
        )
        merged = merge_manifest_files(
            base,
            new_entries,
            generated_utc=_utc_now(),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
        )
        manifest_path = _write_manifest_atomic(dest, merged)
        updated = update_session_storage_fields(
            session.id,
            work_transfer_path=str(dest),
            work_local_path=local_str,
            manifest_revision=int(merged["revision"]),
            db_path=db_path,
        )
        update_transfer_job_status(
            job.job_id,
            status="completed",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            manifest_path=str(manifest_path),
            log_path=str(log_path),
            db_path=db_path,
        )
        _append_log(
            log_path,
            f"OK copied={copied} skipped={skipped} bytes={bytes_copied} rev={merged['revision']}",
        )
        return PushWorkResult(
            ok=True,
            job_id=job.job_id,
            session=updated.to_dict(),
            work_transfer_path=str(dest),
            work_local_path=local_str,
            siril_home_local=siril_local,
            files_copied=copied,
            files_skipped=skipped,
            bytes_copied=bytes_copied,
            manifest_revision=int(merged["revision"]),
            completeness=completeness,
            log_path=str(log_path),
        )
    except Exception as exc:
        err = str(exc)
        try:
            update_transfer_job_status(
                job.job_id,
                status="failed",
                error=err,
                log_path=str(log_path),
                db_path=db_path,
            )
        except Exception:
            pass
        try:
            _append_log(log_path, f"FAIL {err}")
        except OSError:
            pass
        return PushWorkResult(
            ok=False,
            job_id=job.job_id,
            work_transfer_path=str(dest),
            work_local_path=local_str,
            siril_home_local=siril_local,
            error=err,
            log_path=str(log_path),
        )


def push_capture_to_archive(
    session_id: int,
    *,
    db_path: Path | None = None,
    archive_root: Path | None = None,
    stable_window_s: float = STABLE_WINDOW_S,
) -> PushArchiveResult:
    """S4: CAPTURE → ARCHIVE (NAS), Results/siril_home am Ziel nie überschreiben/löschen."""
    settings = load_mele_settings()
    arch_root = archive_root if archive_root is not None else settings.archive_root

    session = get_session(session_id, db_path=db_path)
    if session is None:
        return PushArchiveResult(ok=False, error=f"Unbekannte Session: {session_id}")
    if not arch_root or not str(arch_root).strip():
        return PushArchiveResult(
            ok=False,
            error="archive_root nicht gesetzt — Prefs / mele.yaml (UNC zur NAS)",
        )

    source = Path(str(session.local_path or "").strip())
    if not source.is_dir():
        return PushArchiveResult(
            ok=False,
            error=f"CAPTURE-Pfad fehlt oder kein Ordner: {session.local_path!r}",
        )

    dest = resolve_archive_session_dir(session, archive_root=Path(arch_root))

    completeness = (
        JOB_COMPLETENESS_FULL
        if session.lifecycle_status == LIFECYCLE_CLOSED
        else JOB_COMPLETENESS_PARTIAL
    )
    arch_comp = (
        ARCHIVE_COMPLETENESS_COMPLETE
        if session.lifecycle_status == LIFECYCLE_CLOSED
        else ARCHIVE_COMPLETENESS_PARTIAL
    )
    skip_stable_wait = session.lifecycle_status == LIFECYCLE_CLOSED
    skip_names = {MANIFEST_NAME.lower(), TRANSFER_LOG_WORK.lower(), TRANSFER_LOG_ARCHIVE.lower()}

    rels = []
    for rel in iter_relative_files(source):
        key = _rel_key(rel)
        if key.lower() in skip_names:
            continue
        if _top_dir(key) in _ARCHIVE_SKIP_TOP:
            continue
        rels.append(rel)

    need = estimate_source_bytes(source, rels)
    check_free_space(dest, need)

    log_path = dest / TRANSFER_LOG_ARCHIVE
    job = create_transfer_job(
        session_id=session.id,
        kind=TRANSFER_KIND_CAPTURE_TO_ARCHIVE,
        source_root=str(source),
        dest_root=str(dest),
        completeness=completeness,
        manifest_revision=int(session.manifest_revision or 0),
        db_path=db_path,
    )
    _append_log(log_path, f"START job={job.job_id} src={source} dest={dest}")

    try:
        update_transfer_job_status(job.job_id, status="copying", log_path=str(log_path), db_path=db_path)
        dest.mkdir(parents=True, exist_ok=True)

        # Vorhandene ARCHIVE-results/ nicht anfassen (auch nicht listen/löschen)
        existing_manifest = _load_dest_manifest(dest)
        copied, skipped, bytes_copied, new_entries = _copy_verified_tree(
            source=source,
            dest=dest,
            rels=rels,
            job_id=job.job_id,
            skip_stable_wait=skip_stable_wait,
            stable_window_s=stable_window_s,
            db_path=db_path,
            conflict_label="ARCHIVE",
        )
        update_transfer_job_status(
            job.job_id,
            status="verifying",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            db_path=db_path,
        )

        base = existing_manifest or empty_manifest(
            session_id=session.id,
            object_name=session.catalog_key,
            capture_date=str(dest.parent.name),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
            revision=int(session.manifest_revision or 0),
        )
        # Bestehende Manifest-Eintraege unter results/ beibehalten (S5)
        merged = merge_manifest_files(
            base,
            new_entries,
            generated_utc=_utc_now(),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
        )
        manifest_path = _write_manifest_atomic(dest, merged)

        update_session(
            session.id,
            archive_path=str(dest),
            archive_status="archived",
            db_path=db_path,
        )
        updated = update_session_storage_fields(
            session.id,
            archive_completeness=arch_comp,
            manifest_revision=int(merged["revision"]),
            db_path=db_path,
        )
        update_transfer_job_status(
            job.job_id,
            status="completed",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            manifest_path=str(manifest_path),
            log_path=str(log_path),
            db_path=db_path,
        )
        _append_log(
            log_path,
            f"OK copied={copied} skipped={skipped} bytes={bytes_copied} "
            f"rev={merged['revision']} archive_completeness={arch_comp}",
        )
        return PushArchiveResult(
            ok=True,
            job_id=job.job_id,
            session=updated.to_dict(),
            archive_path=str(dest),
            files_copied=copied,
            files_skipped=skipped,
            bytes_copied=bytes_copied,
            manifest_revision=int(merged["revision"]),
            completeness=completeness,
            archive_completeness=arch_comp,
            log_path=str(log_path),
        )
    except Exception as exc:
        err = str(exc)
        try:
            update_transfer_job_status(
                job.job_id,
                status="failed",
                error=err,
                log_path=str(log_path),
                db_path=db_path,
            )
        except Exception:
            pass
        try:
            _append_log(log_path, f"FAIL {err}")
        except OSError:
            pass
        return PushArchiveResult(
            ok=False,
            job_id=job.job_id,
            archive_path=str(dest),
            error=err,
            log_path=str(log_path),
        )


def _work_to_archive_rels(
    source: Path,
    *,
    siril_home_dirname: str,
) -> list[Path]:
    """Allow: results/, Master, weather/meta. Deny: siril_home/ + Transfer-Logs/Manifest."""
    siril = (siril_home_dirname or DEFAULT_SIRIL_HOME_DIRNAME).strip() or DEFAULT_SIRIL_HOME_DIRNAME
    deny_top = set(_W2A_DENY_TOP) | {siril.lower()}
    skip_names = {
        MANIFEST_NAME.lower(),
        TRANSFER_LOG_WORK.lower(),
        TRANSFER_LOG_ARCHIVE.lower(),
        TRANSFER_LOG_WORK_ARCHIVE.lower(),
    }
    rels: list[Path] = []
    for rel in iter_relative_files(source):
        key = _rel_key(rel)
        if key.lower() in skip_names:
            continue
        if _top_dir(key) in deny_top:
            continue
        rels.append(rel)
    return rels


def push_work_to_archive(
    session_id: int,
    *,
    db_path: Path | None = None,
    archive_root: Path | None = None,
    work_transfer_root: Path | None = None,
    siril_home_dirname: str | None = None,
    stable_window_s: float = STABLE_WINDOW_S,
) -> PushArchiveResult:
    """S5: WORK → ARCHIVE (MeLE Doppel-Hop). results/ ja, siril_home/ nie."""
    settings = load_mele_settings()
    arch_root = archive_root if archive_root is not None else settings.archive_root
    siril_name = (
        (siril_home_dirname or settings.siril_home_dirname or DEFAULT_SIRIL_HOME_DIRNAME).strip()
        or DEFAULT_SIRIL_HOME_DIRNAME
    )

    session = get_session(session_id, db_path=db_path)
    if session is None:
        return PushArchiveResult(ok=False, error=f"Unbekannte Session: {session_id}")
    if not arch_root or not str(arch_root).strip():
        return PushArchiveResult(
            ok=False,
            error="archive_root nicht gesetzt — Prefs / mele.yaml (UNC zur NAS)",
        )

    source_s = str(getattr(session, "work_transfer_path", "") or "").strip()
    if not source_s and work_transfer_root is not None:
        when = _session_when(session)
        suggested = suggested_work_transfer_session_dir(
            session.catalog_key,
            when=when,
            work_transfer_root=Path(work_transfer_root),
            session_id=session.id,
        )
        if suggested is not None:
            source_s = str(suggested)
    if not source_s:
        return PushArchiveResult(
            ok=False,
            error="Kein WORK-Pfad — zuerst → Work (CAPTURE→WORK), dann Work→Archiv",
        )
    source = Path(source_s)
    if not source.is_dir():
        return PushArchiveResult(
            ok=False,
            error=f"WORK-Pfad fehlt oder kein Ordner: {source_s!r}",
        )

    dest = resolve_archive_session_dir(session, archive_root=Path(arch_root))

    completeness = (
        JOB_COMPLETENESS_FULL
        if session.lifecycle_status == LIFECYCLE_CLOSED
        else JOB_COMPLETENESS_PARTIAL
    )
    arch_comp = (
        ARCHIVE_COMPLETENESS_COMPLETE
        if session.lifecycle_status == LIFECYCLE_CLOSED
        else ARCHIVE_COMPLETENESS_PARTIAL
    )
    skip_stable_wait = session.lifecycle_status == LIFECYCLE_CLOSED
    rels = _work_to_archive_rels(source, siril_home_dirname=siril_name)
    need = estimate_source_bytes(source, rels)
    check_free_space(dest, need)

    log_path = dest / TRANSFER_LOG_WORK_ARCHIVE
    job = create_transfer_job(
        session_id=session.id,
        kind=TRANSFER_KIND_WORK_TO_ARCHIVE,
        source_root=str(source),
        dest_root=str(dest),
        completeness=completeness,
        manifest_revision=int(session.manifest_revision or 0),
        db_path=db_path,
    )
    _append_log(log_path, f"START work_to_archive job={job.job_id} src={source} dest={dest}")

    try:
        update_transfer_job_status(job.job_id, status="copying", log_path=str(log_path), db_path=db_path)
        dest.mkdir(parents=True, exist_ok=True)
        existing_manifest = _load_dest_manifest(dest)
        copied, skipped, bytes_copied, new_entries = _copy_verified_tree(
            source=source,
            dest=dest,
            rels=rels,
            job_id=job.job_id,
            skip_stable_wait=skip_stable_wait,
            stable_window_s=stable_window_s,
            db_path=db_path,
            conflict_label="ARCHIVE",
        )
        update_transfer_job_status(
            job.job_id,
            status="verifying",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            db_path=db_path,
        )
        base = existing_manifest or empty_manifest(
            session_id=session.id,
            object_name=session.catalog_key,
            capture_date=str(dest.parent.name),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
            revision=int(session.manifest_revision or 0),
        )
        merged = merge_manifest_files(
            base,
            new_entries,
            generated_utc=_utc_now(),
            lifecycle_at_source=session.lifecycle_status,
            completeness=completeness,
        )
        manifest_path = _write_manifest_atomic(dest, merged)

        update_session(
            session.id,
            archive_path=str(dest),
            archive_status="archived",
            db_path=db_path,
        )
        updated = update_session_storage_fields(
            session.id,
            archive_completeness=arch_comp,
            manifest_revision=int(merged["revision"]),
            db_path=db_path,
        )
        update_transfer_job_status(
            job.job_id,
            status="completed",
            progress_files=copied + skipped,
            progress_bytes=bytes_copied,
            manifest_path=str(manifest_path),
            log_path=str(log_path),
            db_path=db_path,
        )
        _append_log(
            log_path,
            f"OK copied={copied} skipped={skipped} bytes={bytes_copied} "
            f"rev={merged['revision']} archive_completeness={arch_comp}",
        )
        return PushArchiveResult(
            ok=True,
            job_id=job.job_id,
            session=updated.to_dict(),
            archive_path=str(dest),
            files_copied=copied,
            files_skipped=skipped,
            bytes_copied=bytes_copied,
            manifest_revision=int(merged["revision"]),
            completeness=completeness,
            archive_completeness=arch_comp,
            log_path=str(log_path),
        )
    except Exception as exc:
        err = str(exc)
        try:
            update_transfer_job_status(
                job.job_id,
                status="failed",
                error=err,
                log_path=str(log_path),
                db_path=db_path,
            )
        except Exception:
            pass
        try:
            _append_log(log_path, f"FAIL {err}")
        except OSError:
            pass
        return PushArchiveResult(
            ok=False,
            job_id=job.job_id,
            archive_path=str(dest),
            error=err,
            log_path=str(log_path),
        )
