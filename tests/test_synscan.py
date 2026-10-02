"""Tests fuer SynScan-Pro-Start/Status (ohne echte EXE noetig)."""

from __future__ import annotations

from pathlib import Path

from mele import synscan
from mele.synscan import get_synscan_status, resolve_synscan_exe, start_synscan


def test_resolve_exe_file_and_dir(tmp_path: Path) -> None:
    exe = tmp_path / "SynScanPro.exe"
    exe.write_bytes(b"x")
    assert resolve_synscan_exe(exe) == exe
    assert resolve_synscan_exe(tmp_path) == exe


def test_status_missing_exe(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "SynScanPro.exe"
    monkeypatch.setattr(synscan, "is_synscan_running", lambda **_k: False)
    status = get_synscan_status(missing)
    assert status.running is False
    assert status.exe_exists is False


def test_start_missing_exe(tmp_path: Path) -> None:
    result = start_synscan(tmp_path / "SynScanPro.exe")
    assert result.ok is False
    assert "nicht gefunden" in (result.error or "")


def test_start_already_running(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "SynScanPro.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(synscan, "is_synscan_running", lambda **_k: True)
    result = start_synscan(exe)
    assert result.ok is True
    assert result.already_running is True


def test_start_launches(tmp_path: Path, monkeypatch) -> None:
    exe = tmp_path / "SynScanPro.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(synscan, "is_synscan_running", lambda **_k: False)

    class _FakeProc:
        pid = 4242

    monkeypatch.setattr(synscan.subprocess, "Popen", lambda *a, **k: _FakeProc())
    result = start_synscan(exe)
    assert result.ok is True
    assert result.already_running is False
    assert result.pid == 4242
