"""Tests weather_server Launch-Helfer."""

from __future__ import annotations

from pathlib import Path

from mele.weather_server_launch import (
    _port_from_url,
    resolve_python,
    start_weather_server_app,
)


def test_resolve_python_prefers_venv(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    exe = scripts / "python.exe"
    exe.write_bytes(b"x")
    assert resolve_python(tmp_path) == exe


def test_port_from_url() -> None:
    assert _port_from_url("http://127.0.0.1:8765") == 8765
    assert _port_from_url("http://localhost") == 80


def test_start_already_running(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "mele.weather_server_launch.get_weather_server_app_status",
        lambda *a, **k: type(
            "S",
            (),
            {
                "running": True,
                "reachable": True,
                "python_exists": True,
                "python_path": "x",
                "error": None,
            },
        )(),
    )
    result = start_weather_server_app()
    assert result.ok and result.already_running


def test_start_blocked_when_process_unhealthy(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        "mele.weather_server_launch.get_weather_server_app_status",
        lambda *a, **k: type(
            "S",
            (),
            {
                "running": True,
                "reachable": False,
                "python_exists": True,
                "python_path": "x",
                "error": None,
            },
        )(),
    )
    result = start_weather_server_app()
    assert not result.ok and result.already_running
    assert "API" in (result.error or "")
