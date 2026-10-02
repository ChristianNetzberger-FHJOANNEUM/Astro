"""Tests fuer NINA-Desktop-Start/Status (ohne echte EXE noetig)."""

from __future__ import annotations

from pathlib import Path

from mele import nina_launch
from mele.nina_launch import get_nina_app_status, resolve_nina_exe, start_nina_app


def test_resolve_nina_exe_file_and_dir(tmp_path: Path) -> None:
    exe = tmp_path / "NINA.exe"
    exe.write_bytes(b"x")
    assert resolve_nina_exe(exe) == exe
    assert resolve_nina_exe(tmp_path) == exe


def test_status_missing_exe(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "NINA.exe"
    monkeypatch.setattr(nina_launch, "is_nina_running", lambda **_k: False)
    status = get_nina_app_status(missing)
    assert status.running is False
    assert status.exe_exists is False


def test_start_missing_exe(tmp_path: Path) -> None:
    result = start_nina_app(tmp_path / "NINA.exe")
    assert result.ok is False
    assert "nicht gefunden" in (result.error or "")


def test_start_already_running(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "NINA.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(nina_launch, "is_nina_running", lambda **_k: True)
    result = start_nina_app(exe)
    assert result.ok is True
    assert result.already_running is True


def test_start_launches(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "NINA.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(nina_launch, "is_nina_running", lambda **_k: False)

    class _FakeProc:
        pid = 5150

    monkeypatch.setattr(nina_launch.subprocess, "Popen", lambda *a, **k: _FakeProc())
    result = start_nina_app(exe)
    assert result.ok is True
    assert result.already_running is False
    assert result.pid == 5150
