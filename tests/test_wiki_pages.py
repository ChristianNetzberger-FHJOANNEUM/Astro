from pathlib import Path

from mele.wiki_pages import index_payload, page_payload, render_markdown, wiki_root


def test_wiki_index_and_sternzeit_page() -> None:
    root = wiki_root()
    assert root.is_dir()
    data = index_payload(root)
    assert data["ok"] is True
    assert data["format"] == "markdown"
    ids = [p["id"] for s in data["sections"] for p in s["pages"]]
    assert "sternzeit-ra-azimut" in ids
    assert "hardware" in ids
    assert "beitragen" in ids

    page = page_payload("sternzeit-ra-azimut", root)
    assert page["ok"] is True
    assert "LST" in page["markdown"] or "Sternzeit" in page["markdown"]
    assert "<h1>" in page["html"]
    assert Path(page["path"]).is_file()


def test_render_markdown_basics() -> None:
    html = render_markdown("# Titel\n\nHallo **Welt**\n\n- a\n- b\n")
    assert "<h1>Titel</h1>" in html
    assert "<strong>Welt</strong>" in html
    assert "<ul>" in html
