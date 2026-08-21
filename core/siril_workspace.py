"""Siril-Workspaces pro Burst: Links auf Originale, keine Kopien."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.catalog import BurstRow, ImageRow, SessionRow


RAW_SUFFIXES = {".rw2", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf"}


@dataclass
class WorkspaceResult:
    path: Path
    link_mode: str
    linked: int
    skipped: int
    metadata_path: Path


class WorkspaceError(RuntimeError):
    pass


def workspace_path(session_root: Path, burst_no: int, subdir: str = "siril_work") -> Path:
    return Path(session_root) / subdir / f"burst_{burst_no:03d}"


def _link_file(src: Path, dst: Path) -> str:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        os.symlink(src, dst)
        return "symlink"


def build_metadata(
    session: SessionRow,
    burst: BurstRow,
    frames: list[ImageRow],
    link_mode: str,
) -> dict:
    first = frames[0] if frames else None
    return {
        "session": session.title,
        "session_slug": session.slug,
        "burst": burst.burst_no,
        "burst_id": burst.id,
        "type": burst.drive_guess,
        "kind": burst.kind,
        "phase": burst.phase,
        "frames": burst.frame_count,
        "c2_start": burst.c2_offset_start_s,
        "c2_end": burst.c2_offset_end_s,
        "camera": (first.camera if first else "") or "",
        "lens": (first.lens if first else "") or "",
        "focal_length_mm": first.focal_length if first else None,
        "shutter": (first.exposure if first else "") or "",
        "iso": first.iso if first else None,
        "aperture": (first.aperture if first else "") or "",
        "link_mode": link_mode,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [
            {
                "frame_id": img.id,
                "frame_in_burst": img.burst_index,
                "original": Path(img.filepath).name,
                "original_path": img.filepath,
            }
            for img in frames
        ],
    }


def create_workspace(
    session: SessionRow,
    burst: BurstRow,
    frames: list[ImageRow],
    *,
    work_subdir: str = "siril_work",
) -> WorkspaceResult:
    """Erzeugt siril_work/burst_NNN mit Links. Originale bleiben unveraendert."""
    dest_dir = workspace_path(Path(session.root_path), burst.burst_no, work_subdir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    modes: list[str] = []
    linked = 0
    skipped = 0
    errors: list[str] = []

    for img in frames:
        src = Path(img.filepath)
        if src.suffix.lower() not in RAW_SUFFIXES:
            skipped += 1
            continue
        if not src.is_file():
            skipped += 1
            errors.append(f"fehlt: {src}")
            continue
        dst = dest_dir / src.name
        try:
            modes.append(_link_file(src, dst))
            linked += 1
        except OSError as exc:
            errors.append(f"{src.name}: {exc}")

    if linked == 0:
        raise WorkspaceError(
            "Keine RAW-Links erzeugt. Hardlinks brauchen dasselbe Volume; "
            "Symlinks oft den Windows-Entwicklermodus. "
            + (" ".join(errors[:3]) if errors else "")
        )

    link_mode = modes[0] if len(set(modes)) == 1 else "mixed"
    meta = build_metadata(session, burst, frames, link_mode)
    meta_path = dest_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return WorkspaceResult(
        path=dest_dir,
        link_mode=link_mode,
        linked=linked,
        skipped=skipped,
        metadata_path=meta_path,
    )


def open_folder(path: Path) -> None:
    os.startfile(path)  # noqa: S606  Windows Explorer
