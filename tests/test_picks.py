import json

import pytest

from mele.picks import PicksCorrupt, eligible_keys, load_picks, picks_path, upsert_pick


def test_missing_file_is_empty_selection(tmp_path) -> None:
    loaded = load_picks(tmp_path)
    assert loaded["objects"] == {}
    assert loaded["corrupt"] is False
    assert not picks_path(tmp_path).exists()


def test_corrupt_file_is_not_replaced(tmp_path) -> None:
    path = picks_path(tmp_path)
    path.write_text("{", encoding="utf-8")
    loaded = load_picks(tmp_path)
    assert loaded["corrupt"] is True
    assert loaded["objects"] == {}
    with pytest.raises(PicksCorrupt):
        upsert_pick(tmp_path, "NGC6426", rating=5, quest=True, note="")
    assert path.read_text(encoding="utf-8") == "{"


def test_upsert_validates_and_filters_eligibility(tmp_path) -> None:
    with pytest.raises(ValueError):
        upsert_pick(tmp_path, "NGC6426", rating=9, quest=True, note="")
    with pytest.raises(ValueError):
        upsert_pick(tmp_path, "NGC6426", rating=True, quest=True, note="")
    saved = upsert_pick(tmp_path, "NGC6426", rating=2, quest=True, note="schwach")
    assert eligible_keys(saved["objects"], 1) == {"NGC6426"}
    assert eligible_keys(saved["objects"], 3) == set()
    released = upsert_pick(tmp_path, "NGC7000", rating=None, quest=True, note="")
    assert "NGC7000" not in eligible_keys(released["objects"], 1)
    cleared = upsert_pick(tmp_path, "NGC7000", rating=None, quest=False, note="")
    assert "NGC7000" not in cleared["objects"]
    stored = json.loads(picks_path(tmp_path).read_text(encoding="utf-8"))
    assert stored["schema"] == 1
    assert stored["objects"]["NGC6426"]["rating"] == 2
    assert stored["objects"]["NGC6426"]["quest"] is True
