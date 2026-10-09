"""Unit-Tests MeLE Equipment-Configurations (Phase 1.5 Abschnitt E)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mele.equipment_profiles import (
    delete_equipment_profile,
    image_scale_arcsec_px,
    load_equipment_profiles,
    set_active_equipment_profile,
    upsert_equipment_profile,
)
from mele.phd2 import Phd2Client


def test_image_scale_formula() -> None:
    assert image_scale_arcsec_px(pixel_size_um=3.75, focal_length_mm=250) == pytest.approx(3.093975)
    assert image_scale_arcsec_px(pixel_size_um=None, focal_length_mm=250) is None
    assert image_scale_arcsec_px(pixel_size_um=3.75, focal_length_mm=0) is None


def test_equipment_profiles_crud_and_active(tmp_path: Path) -> None:
    horizon = tmp_path / "horizon"
    horizon.mkdir()
    empty = load_equipment_profiles(horizon)
    assert empty["profiles"] == []
    assert empty["active_id"] is None

    a = upsert_equipment_profile(
        horizon,
        {
            "name": "NEQ6 + Guide250 + ASI120",
            "guiding_focal_length_mm": 250,
            "guiding_pixel_size_um": 3.75,
            "phd2_profile_name": "NEQ6",
            "phd2_profile_id": 2,
            "mount_id": "neq6",
            "guiding_camera_id": "asi120mc",
        },
    )
    assert a["ok"] is True
    assert len(a["profiles"]) == 1
    assert a["profiles"][0]["mele_image_scale_arcsec_px"] == pytest.approx(3.093975, rel=1e-4)

    b = upsert_equipment_profile(
        horizon,
        {
            "name": "NEQ5 + Guide250 + ASI120",
            "guiding_focal_length_mm": 250,
            "guiding_pixel_size_um": 3.75,
            "phd2_profile_id": 3,
            "phd2_profile_name": "NEQ5",
        },
    )
    assert len(b["profiles"]) == 2

    first_id = a["profile"]["id"]
    activated = set_active_equipment_profile(horizon, first_id)
    assert activated["ok"] is True
    assert activated["active_id"] == first_id
    assert activated["active"]["phd2_profile_name"] == "NEQ6"

    deleted = delete_equipment_profile(horizon, first_id)
    assert deleted["ok"] is True
    assert deleted["active_id"] is None
    assert len(deleted["profiles"]) == 1


def test_try_set_profile_skips_when_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    calls: list[str] = []

    def fake_call(method, params=None, *, timeout_s=8.0):  # noqa: ANN001, ARG001
        calls.append(method)
        if method == "get_connected":
            return True
        raise AssertionError(f"unexpected {method}")

    monkeypatch.setattr(client, "call", fake_call)
    result = client.try_set_profile(2)
    assert result["ok"] is True
    assert result["applied"] is False
    assert result["reason"] == "equipment_connected"
    assert calls == ["get_connected"]


def test_try_set_profile_applies_when_disconnected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Phd2Client(host="127.0.0.1", port=9)
    client._sock = object()  # type: ignore[assignment]
    calls: list[tuple] = []

    def fake_call(method, params=None, *, timeout_s=8.0):  # noqa: ANN001, ARG001
        calls.append((method, params))
        if method == "get_connected":
            return False
        if method == "set_profile":
            return 0
        raise AssertionError(method)

    monkeypatch.setattr(client, "call", fake_call)
    result = client.try_set_profile(5)
    assert result["ok"] is True
    assert result["applied"] is True
    assert ("set_profile", [5]) in calls
