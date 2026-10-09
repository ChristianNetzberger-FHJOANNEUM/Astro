"""S6: Sichere Session-Bereinigung — CAPTURE / WORK / DB, nie NAS/ARCHIVE.

Path-Guards: Root-Whitelist, Session-Slug, kein Symlink/Junction, kein Archiv-Root.
DB-Pfade erst nach erfolgreichem physischem Delete leeren.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mele.astro_manager import (
    delete_session,
    get_session,
    path_under_root,
    session_dir_slug,
    update_session_paths,
    update_session_storage_fields,
)
from mele.config import load_mele_settings
from mele.session_storage import (
    ARCHIVE_COMPLETENESS_COMPLETE,
    LIFECYCLE_CAPTURING,
    normalize_archive_completeness,
)


class RemoveError(RuntimeError):
    """Bereinigung abgelehnt oder fehlgeschlagen."""


@dataclass
class RemoveResult:
    ok: bool
    session_id: int = 0
    deleted_capture: bool = False
    deleted_work: bool = False
    deleted_db: bool = False
    capture_path: str = ""
    work_path: str = ""
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    session: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "session_id": self.session_id,
            "deleted_capture": self.deleted_capture,
            "deleted_work": self.deleted_work,
            "deleted_db": self.deleted_db,
            "capture_path": self.capture_path,
            "work_path": self.work_path,
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "error": self.error,
            "session": self.session,
        }


def _has_reparse_point(path: Path) -> bool:
    """Symlink oder Windows-Junction/Mount-Point."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if os.name == "nt":
        try:
            st = path.lstat()
            # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            attrs = getattr(st, "st_file_attributes", 0) or 0
            if int(attrs) & 0x400:
                return True
        except OSError:
            return True
    return False


def _chain_has_reparse(path: Path, stop_at: Path | None = None) -> bool:
    cur = path
    stop_n = str(stop_at).replace("/", "\\").lower().rstrip("\\") if stop_at else None
    for _ in range(64):
        if _has_reparse_point(cur):
            return True
        if stop_n and str(cur).replace("/", "\\").lower().rstrip("\\") == stop_n:
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return False


def assert_safe_deletable_session_dir(
    path: Path | str,
    *,
    allowed_root: Path | str,
    session_id: int,
    label: str,
    forbidden_roots: list[Path | str] | None = None,
) -> Path:
    """Wirft RemoveError wenn der Pfad nicht sicher loeschbar ist."""
    raw = str(path or "").strip()
    if not raw:
        raise RemoveError(f"{label}: Pfad leer")
    target = Path(raw)
    root = Path(str(allowed_root).strip())
    if not str(root).strip():
        raise RemoveError(f"{label}: erlaubter Root nicht konfiguriert")

    # Nie den Root selbst loeschen
    from mele.astro_manager import _norm_fs_path

    if _norm_fs_path(target) == _norm_fs_path(root):
        raise RemoveError(f"{label}: Root selbst darf nicht geloescht werden: {root}")

    if not path_under_root(target, root):
        raise RemoveError(
            f"{label}: Pfad liegt nicht unter erlaubtem Root "
            f"({target} ∉ {root})"
        )

    for forbidden in forbidden_roots or []:
        if forbidden and str(forbidden).strip() and path_under_root(target, forbidden):
            raise RemoveError(
                f"{label}: Pfad liegt unter verbotenem Root (ARCHIVE/NAS): {forbidden}"
            )

    slug = session_dir_slug(session_id)
    if target.name.lower() != slug.lower():
        raise RemoveError(
            f"{label}: Ordnername muss {slug} sein (ist {target.name!r})"
        )

    if target.exists() and _chain_has_reparse(target, stop_at=root):
        raise RemoveError(
            f"{label}: Symlink/Junction in Pfad — Loeschen verweigert: {target}"
        )

    return target


def _rmtree_safe(path: Path) -> None:
    """Loescht Verzeichnisbaum; bei fehlendem Pfad no-op."""
    if not path.exists():
        return
    if path.is_file() or path.is_symlink():
        path.unlink(missing_ok=True)
        return
    if not path.is_dir():
        raise RemoveError(f"Kein Verzeichnis: {path}")

    def _onerror(func: Any, p: str, _exc_info: Any) -> None:
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError as exc:
            raise RemoveError(f"Loeschen fehlgeschlagen: {p}: {exc}") from exc

    shutil.rmtree(path, onerror=_onerror)


def remove_session_storage(
    session_id: int,
    *,
    delete_capture: bool = False,
    delete_work: bool = False,
    delete_db: bool = False,
    force_capture: bool = False,
    db_path: Path | None = None,
    local_capture_root: Path | None = None,
    work_transfer_root: Path | None = None,
    archive_root: Path | None = None,
) -> RemoveResult:
    """Physische CAPTURE/WORK-Bereinigung und optional DB-Zeile.

    Reihenfolge: Disk zuerst, dann Pfade in DB leeren, zuletzt DB-DELETE.
    ARCHIVE/NAS wird nie angefasst.
    """
    if not (delete_capture or delete_work or delete_db):
        return RemoveResult(
            ok=False,
            session_id=int(session_id),
            error="Nichts ausgewaehlt (capture/work/db)",
        )

    settings = load_mele_settings()
    cap_root = local_capture_root if local_capture_root is not None else settings.local_capture_root
    wt_root = work_transfer_root if work_transfer_root is not None else settings.work_transfer_root
    arch_root = archive_root if archive_root is not None else settings.archive_root

    session = get_session(session_id, db_path=db_path)
    if session is None:
        return RemoveResult(ok=False, session_id=int(session_id), error=f"Unbekannte Session: {session_id}")

    if session.lifecycle_status == LIFECYCLE_CAPTURING:
        return RemoveResult(
            ok=False,
            session_id=session.id,
            error="Session ist CAPTURING — zuerst schliessen oder Capture abbrechen",
        )

    result = RemoveResult(ok=True, session_id=session.id)
    forbidden = [arch_root] if arch_root and str(arch_root).strip() else []

    try:
        if delete_capture:
            local = str(session.local_path or "").strip()
            if not local:
                result.skipped.append("capture: kein local_path")
            else:
                completeness = normalize_archive_completeness(
                    getattr(session, "archive_completeness", None)
                )
                if completeness != ARCHIVE_COMPLETENESS_COMPLETE and not force_capture:
                    raise RemoveError(
                        "CAPTURE-Loeschung empfohlen erst nach archive_completeness=complete "
                        "(force_capture=true zum Ueberschreiben)"
                    )
                if completeness != ARCHIVE_COMPLETENESS_COMPLETE and force_capture:
                    result.warnings.append(
                        "CAPTURE trotz archive_completeness≠complete geloescht (force)"
                    )
                target = assert_safe_deletable_session_dir(
                    local,
                    allowed_root=cap_root,
                    session_id=session.id,
                    label="CAPTURE",
                    forbidden_roots=forbidden,
                )
                result.capture_path = str(target)
                _rmtree_safe(target)
                result.deleted_capture = True
                # Pfade erst nach Erfolg leeren (DB behalten)
                if not delete_db:
                    update_session_paths(
                        session.id,
                        local_path="",
                        archive_path=str(session.archive_path or ""),
                        notes=session.notes,
                        db_path=db_path,
                    )

        if delete_work:
            work = str(getattr(session, "work_transfer_path", "") or "").strip()
            if not work:
                result.skipped.append("work: kein work_transfer_path")
            elif not wt_root or not str(wt_root).strip():
                raise RemoveError("work_transfer_root nicht konfiguriert — WORK-Loeschung abgelehnt")
            else:
                target = assert_safe_deletable_session_dir(
                    work,
                    allowed_root=wt_root,
                    session_id=session.id,
                    label="WORK",
                    forbidden_roots=forbidden,
                )
                result.work_path = str(target)
                _rmtree_safe(target)
                result.deleted_work = True
                if not delete_db:
                    update_session_storage_fields(
                        session.id,
                        work_transfer_path="",
                        work_local_path="",
                        db_path=db_path,
                    )

        if delete_db:
            # ARCHIVE-Pfad nur Metadaten — physisch nie loeschen
            ok = delete_session(session.id, db_path=db_path)
            if not ok:
                raise RemoveError("DB-DELETE fehlgeschlagen")
            result.deleted_db = True
            result.session = None
        else:
            refreshed = get_session(session.id, db_path=db_path)
            result.session = refreshed.to_dict() if refreshed else None

    except RemoveError as exc:
        result.ok = False
        result.error = str(exc)
        refreshed = get_session(session.id, db_path=db_path)
        result.session = refreshed.to_dict() if refreshed else None
        return result
    except OSError as exc:
        result.ok = False
        result.error = f"Dateisystem: {exc}"
        refreshed = get_session(session.id, db_path=db_path)
        result.session = refreshed.to_dict() if refreshed else None
        return result

    return result
