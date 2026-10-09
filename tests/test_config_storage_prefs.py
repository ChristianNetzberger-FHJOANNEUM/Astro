"""Prefs: Storage-Pfade nach mele.yaml schreiben."""

from __future__ import annotations

from pathlib import Path

from mele.config import load_mele_settings, save_storage_paths


def test_save_storage_paths_preserves_comments(tmp_path: Path) -> None:
    cfg = tmp_path / "mele.yaml"
    cfg.write_text(
        "# keep me\n"
        "local_capture_root: C:/Old/Capture\n"
        "archive_root: //NAS/Old\n"
        "# WORK comment\n"
        'work_transfer_root: ""\n'
        'work_local_root: ""\n'
        "siril_home_dirname: siril_home\n"
        "ui_port: 8082\n",
        encoding="utf-8",
    )
    save_storage_paths(
        work_transfer_root="//100.97.226.18/Astro/Work/Mele",
        work_local_root="C:/Astro/Work/Mele",
        path=cfg,
    )
    text = cfg.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "# WORK comment" in text
    assert "100.97.226.18" in text
    assert "C:/Astro/Work/Mele" in text
    settings = load_mele_settings(cfg)
    assert settings.work_transfer_root is not None
    assert "100.97.226.18" in str(settings.work_transfer_root).replace("\\", "/")
    assert "Astro/Work/Mele" in str(settings.work_transfer_root).replace("\\", "/")
    assert settings.work_local_root is not None
    assert str(settings.work_local_root).replace("\\", "/").endswith("Astro/Work/Mele")
    assert settings.local_capture_root == Path("C:/Old/Capture")
