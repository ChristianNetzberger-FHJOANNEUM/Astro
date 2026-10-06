"""PreviewService: FITS/Kamera-RAW → gestretchtes JPEG + Header."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from PIL import Image

from mele.preview_service import (
    PreviewError,
    StretchParams,
    find_latest_fits,
    fits_header_dict,
    generate_preview,
    preview_for_session,
    preview_path_for,
    read_fits_header,
    session_preview_status,
)


def _write_synthetic_fits(
    path: Path,
    *,
    shape: tuple[int, int] = (240, 320),
    peak: float = 5000.0,
    bias: float = 100.0,
    exptime: float = 60.0,
    gain: float = 100.0,
) -> Path:
    """Schwach kontaminierter Deep-Sky-ähnlicher Frame (Hintergrund + Stern)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h // 2, w // 2
    data = np.full((h, w), bias, dtype=np.float32)
    data += np.random.default_rng(42).normal(0, 5.0, size=(h, w)).astype(np.float32)
    r2 = (yy - cy) ** 2 + (xx - cx) ** 2
    data += peak * np.exp(-r2 / (2 * 4.5**2))
    hdr = fits.Header()
    hdr["EXPTIME"] = exptime
    hdr["GAIN"] = gain
    hdr["INSTRUME"] = "SyntheticCam"
    hdr["DATE-OBS"] = "2026-10-02T20:15:00"
    hdr["BAYERPAT"] = ""
    fits.PrimaryHDU(data=data.astype(np.float32), header=hdr).writeto(path, overwrite=True)
    return path


def test_generate_preview_writes_jpeg_and_header(tmp_path: Path) -> None:
    session = tmp_path / "M31" / "2026-10-02" / "s00001"
    session.mkdir(parents=True)
    fits_path = _write_synthetic_fits(session / "LIGHT_001.fits")
    original_mtime = fits_path.stat().st_mtime
    original_bytes = fits_path.read_bytes()

    result = generate_preview(fits_path, session_dir=session, force=True)

    assert result.created is True
    assert result.preview_path.is_file()
    assert result.preview_path.parent.name == "preview"
    assert result.preview_path.name == "LIGHT_001.preview.jpg"
    assert result.width <= 1600
    assert result.height <= 1200
    assert result.source_width == 320
    assert result.source_height == 240
    assert result.header.get("EXPTIME") == 60.0
    assert result.header.get("GAIN") == 100.0
    assert result.header.get("INSTRUME") == "SyntheticCam"
    assert result.header.get("DATE-OBS") == "2026-10-02T20:15:00"
    assert result.stretch.get("mode") in ("auto", "asinh")

    with Image.open(result.preview_path) as img:
        assert img.format == "JPEG"
        assert img.size == (result.width, result.height)
        # Stretch muss Struktur sichtbar machen (nicht komplett schwarz)
        arr = np.asarray(img, dtype=np.float32)
        assert float(arr.max()) > 20.0

    # Original unverändert
    assert fits_path.read_bytes() == original_bytes
    assert fits_path.stat().st_mtime == original_mtime


def test_preview_skips_regeneration_without_force(tmp_path: Path) -> None:
    session = tmp_path / "s00002"
    session.mkdir()
    fits_path = _write_synthetic_fits(session / "frame.fits", shape=(100, 160))
    first = generate_preview(fits_path, session_dir=session, force=True)
    mtime = first.preview_path.stat().st_mtime
    second = generate_preview(fits_path, session_dir=session, force=False)
    assert second.created is False
    assert second.preview_path == first.preview_path
    assert second.preview_path.stat().st_mtime == mtime


def test_neu_strecken_force_rewrites(tmp_path: Path) -> None:
    session = tmp_path / "s00003"
    session.mkdir()
    fits_path = _write_synthetic_fits(session / "frame.fits", shape=(80, 120))
    first = preview_for_session(session, force=True)
    assert first.created is True
    linear = preview_for_session(
        session,
        stretch=StretchParams(mode="linear", percentile=99.0),
        force=True,
    )
    assert linear.created is True
    assert linear.stretch.get("mode") == "linear"
    assert linear.preview_path.is_file()


def test_find_latest_fits_ignores_preview_subdir(tmp_path: Path) -> None:
    session = tmp_path / "s00004"
    (session / "preview").mkdir(parents=True)
    older = _write_synthetic_fits(session / "old.fits", shape=(40, 40), peak=1000)
    newer = _write_synthetic_fits(session / "new.fits", shape=(40, 40), peak=2000)
    # timestamp erzwingen
    older.touch()
    import time

    time.sleep(0.05)
    newer.touch()
    # Fake-FITS im preview-Ordner darf nicht gewinnen
    decoy = session / "preview" / "decoy.fits"
    _write_synthetic_fits(decoy, shape=(40, 40))
    time.sleep(0.05)
    decoy.touch()

    latest = find_latest_fits(session)
    assert latest == newer
    assert preview_path_for(newer, session) == session / "preview" / "new.preview.jpg"


def test_preview_for_session_missing_fits(tmp_path: Path) -> None:
    session = tmp_path / "empty"
    session.mkdir()
    try:
        preview_for_session(session)
        assert False, "expected PreviewError"
    except PreviewError as exc:
        assert "Kein FITS" in str(exc)


def test_session_preview_status(tmp_path: Path) -> None:
    session = tmp_path / "s00005"
    session.mkdir()
    status = session_preview_status(session)
    assert status["has_fits"] is False
    assert status["has_preview"] is False
    _write_synthetic_fits(session / "a.fits", shape=(50, 60))
    preview_for_session(session, force=True)
    status = session_preview_status(session)
    assert status["has_fits"] is True
    assert status["has_preview"] is True


def test_read_fits_header_json_safe(tmp_path: Path) -> None:
    path = _write_synthetic_fits(tmp_path / "hdr.fits", shape=(32, 32))
    header = read_fits_header(path)
    assert isinstance(header, dict)
    assert header["EXPTIME"] == 60.0
    # round-trip über fits_header_dict
    with fits.open(path, mode="readonly") as hdul:
        d = fits_header_dict(hdul[0].header)
    assert d["INSTRUME"] == "SyntheticCam"


def test_large_frame_downscales_to_max_width(tmp_path: Path) -> None:
    session = tmp_path / "s00006"
    session.mkdir()
    # > 1600 px Breite
    fits_path = _write_synthetic_fits(session / "wide.fits", shape=(400, 2000), peak=8000)
    result = generate_preview(fits_path, session_dir=session, force=True, max_width=1600)
    assert result.width <= 1600
    assert result.source_width == 2000
    assert result.width == 1600


def test_grey_and_color_preview_paths(tmp_path: Path) -> None:
    session = tmp_path / "s_modes"
    session.mkdir()
    h, w = 48, 64
    cfa = np.random.default_rng(3).integers(100, 900, size=(h, w)).astype(np.uint16)
    hdr = fits.Header()
    hdr["BAYERPAT"] = "RGGB"
    path = session / "m.fits"
    fits.PrimaryHDU(data=cfa, header=hdr).writeto(path, overwrite=True)

    grey = preview_for_session(session, force=True, color=False)
    assert grey.color is False
    assert grey.preview_path.name.endswith(".preview.grey.jpg")
    with Image.open(grey.preview_path) as img:
        assert img.mode == "L"

    color = preview_for_session(session, force=True, color=True)
    assert color.color is True
    assert color.preview_path.name.endswith(".preview.jpg")
    assert color.preview_path != grey.preview_path
    with Image.open(color.preview_path) as img:
        assert img.mode == "RGB"


def test_debayer_rggb_produces_rgb_preview(tmp_path: Path) -> None:
    session = tmp_path / "s_color"
    session.mkdir()
    h, w = 64, 96
    # Synthetisches RGGB: R hell in (0,0), B hell in (1,1)
    cfa = np.zeros((h, w), dtype=np.float32)
    cfa[0::2, 0::2] = 1000  # R
    cfa[0::2, 1::2] = 200  # G
    cfa[1::2, 0::2] = 200  # G
    cfa[1::2, 1::2] = 800  # B
    hdr = fits.Header()
    hdr["BAYERPAT"] = "RGGB"
    hdr["EXPTIME"] = 1.0
    path = session / "bayer.fits"
    fits.PrimaryHDU(data=cfa.astype(np.uint16), header=hdr).writeto(path, overwrite=True)

    result = preview_for_session(session, force=True)
    assert result.color is True
    assert result.bayer == "RGGB"
    with Image.open(result.preview_path) as img:
        assert img.mode == "RGB"
        arr = np.asarray(img)
        assert arr.ndim == 3
        assert arr[..., 0].mean() > arr[..., 1].mean()  # R dominant


def test_roi_focus_crop(tmp_path: Path) -> None:
    session = tmp_path / "s_roi"
    light = session / "LIGHT"
    light.mkdir(parents=True)
    h, w = 200, 300
    cfa = np.random.default_rng(0).integers(50, 400, size=(h, w)).astype(np.uint16)
    cfa[90:110, 140:160] = 20000
    hdr = fits.Header()
    hdr["BAYERPAT"] = "RGGB"
    path = light / "frame.fits"
    fits.PrimaryHDU(data=cfa, header=hdr).writeto(path, overwrite=True)

    from mele.preview_service import generate_roi_preview

    focus = generate_roi_preview(path, session_dir=session, x=100, y=50, width=64, height=64, scale=2)
    assert focus.kind == "focus"
    assert focus.preview_path.name.endswith(".focus.jpg")
    assert focus.roi is not None
    assert focus.width >= 64  # 2× scale
    with Image.open(focus.preview_path) as img:
        assert img.mode == "RGB"


def test_nina_style_bzero_fits_and_latest_in_light_subdir(tmp_path: Path) -> None:
    """NINA: LIGHT/ Unterordner + BZERO/BSCALE — memmap=False, neuestes FITS."""
    session = tmp_path / "s00016"
    light = session / "LIGHT"
    light.mkdir(parents=True)
    older = light / "2026-10-02_23-21-42_2.00s_0000.fits"
    newer = light / "2026-10-02_23-35-08_2.00s_0000.fits"

    # uint16 + BZERO wie typische Kamera-FITS (memmap würde scheitern)
    h, w = 48, 64
    data = (np.random.default_rng(1).integers(100, 800, size=(h, w))).astype(np.uint16)
    data[h // 2, w // 2] = 50000
    hdr = fits.Header()
    hdr["BZERO"] = 32768
    hdr["BSCALE"] = 1
    hdr["EXPTIME"] = 2.0
    hdr["INSTRUME"] = "Lumix S5IIX"
    fits.PrimaryHDU(data=data, header=hdr).writeto(older, overwrite=True)
    import time

    time.sleep(0.05)
    fits.PrimaryHDU(data=data, header=hdr).writeto(newer, overwrite=True)
    newer.touch()

    latest = find_latest_fits(session)
    assert latest == newer

    result = preview_for_session(session, force=True)
    assert result.created is True
    assert result.source_path == newer
    assert result.preview_path.is_file()
    assert result.header.get("EXPTIME") == 2.0


def test_find_capture_files_includes_rw2(tmp_path: Path) -> None:
    lights = tmp_path / "LIGHTS"
    lights.mkdir()
    rw2 = lights / "2026-10-06_21-07-19_3.00s_0000.rw2"
    rw2.write_bytes(b"0" * 2048)
    fits_file = lights / "old.fits"
    fits_file.write_bytes(b"SIMPLE  =                    T" + b" " * 2000)

    from mele.preview_service import find_capture_files, is_capture_path

    assert is_capture_path(rw2)
    found = find_capture_files(lights)
    names = {p.name for p in found}
    assert rw2.name in names
    assert fits_file.name in names


def test_wait_for_new_capture_file_stable_rw2(tmp_path: Path) -> None:
    import threading
    import time

    from mele.preview_service import wait_for_new_capture_file

    lights = tmp_path / "LIGHTS"
    lights.mkdir()
    existing = lights / "already.rw2"
    existing.write_bytes(b"x" * 2048)
    before = {str(existing)}
    target = lights / "new.rw2"

    def _write_later() -> None:
        time.sleep(0.3)
        with target.open("wb") as fh:
            fh.write(b"a" * 1500)
            fh.flush()
            time.sleep(0.2)
            fh.write(b"b" * 1500)

    threading.Thread(target=_write_later, daemon=True).start()
    found = wait_for_new_capture_file(
        lights,
        before=before,
        timeout_s=5.0,
        poll_s=0.15,
        min_size_bytes=1024,
        stable_s=0.4,
    )
    assert found is not None
    assert found.name == target.name
    assert found.stat().st_size >= 3000


def test_generate_preview_from_rw2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """RW2-Preview: rawpy-Decode → Stretch-JPEG (ohne echte LibRaw-Datei)."""
    import types

    from mele import preview_service as ps

    class _FakeSizes:
        width = 64
        height = 48
        iwidth = 64
        iheight = 48

    class _FakeRaw:
        sizes = _FakeSizes()
        color_desc = b"RGBG"
        raw_pattern = np.array([[0, 1], [3, 2]], dtype=np.uint8)
        black_level_per_channel = [100, 100, 100, 100]
        white_level = 16000
        camera_whitebalance = [1.3, 1.0, 1.8, 0.0]
        raw_image = (np.random.default_rng(0).integers(100, 400, size=(48, 64))).astype(np.uint16)

        def postprocess(self, **kwargs):  # noqa: ANN003
            del kwargs
            yy, xx = np.mgrid[0:24, 0:32]
            base = 200 + 20 * np.sin(xx / 5.0) + 15 * np.cos(yy / 4.0)
            star = 8000 * np.exp(-((yy - 12) ** 2 + (xx - 16) ** 2) / 8.0)
            plane = (base + star).astype(np.uint16)
            return np.stack([plane, plane * 0.9, plane * 1.1], axis=-1).astype(np.uint16)

        def __enter__(self):
            return self

        def __exit__(self, *args):  # noqa: ANN002
            return False

    fake_rawpy = types.SimpleNamespace(imread=lambda _p: _FakeRaw())
    monkeypatch.setitem(__import__("sys").modules, "rawpy", fake_rawpy)

    rw2 = tmp_path / "LIGHTS"
    rw2.mkdir()
    src = rw2 / "frame.rw2"
    src.write_bytes(b"fake-rw2")
    result = ps.generate_preview(src, session_dir=tmp_path, force=True, color=True)
    assert result.created is True
    assert result.preview_path.is_file()
    assert result.color is True
    assert result.source_width == 64
    assert result.source_height == 48
    with Image.open(result.preview_path) as img:
        assert img.mode == "RGB"
        assert img.size[0] > 0


def test_preview_for_session_prefers_rw2_in_lights(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from mele import preview_service as ps

    lights = tmp_path / "LIGHTS"
    lights.mkdir()
    rw2 = lights / "new.rw2"
    rw2.write_bytes(b"x" * 100)

    called: list[Path] = []

    def fake_generate(source, **kwargs):  # noqa: ANN003
        called.append(Path(source))
        dest = tmp_path / "preview" / "x.preview.jpg"
        dest.parent.mkdir(exist_ok=True)
        Image.new("RGB", (8, 8), (1, 2, 3)).save(dest)
        return ps.PreviewResult(
            preview_path=dest,
            source_path=Path(source),
            created=True,
            width=8,
            height=8,
            color=True,
        )

    monkeypatch.setattr(ps, "generate_preview", fake_generate)
    out = ps.preview_for_session(tmp_path, force=True)
    assert called == [rw2]
    assert out.preview_path.is_file()
