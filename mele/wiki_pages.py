"""MeLE-Wissens-Wiki: Markdown-Kapitel unter ``wiki/`` im Repo-Root.

Format: Markdown (empfohlen für KI-Antworten und manuelle Pflege).
Darstellung: Server rendert nach HTML; die Dateien selbst bleiben ``.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

import yaml

# Repo-Root / wiki
WIKI_ROOT = Path(__file__).resolve().parents[1] / "wiki"
INDEX_NAME = "index.yaml"


@dataclass
class WikiPage:
    id: str
    title: str
    file: str
    section_id: str
    section_title: str

    def path(self) -> Path:
        return (WIKI_ROOT / self.file).resolve()


def wiki_root() -> Path:
    return WIKI_ROOT


def load_index(root: Path | None = None) -> dict[str, Any]:
    base = root or WIKI_ROOT
    index_path = base / INDEX_NAME
    if not index_path.is_file():
        return {"sections": [], "edit_hint": str(base)}
    data = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"sections": [], "edit_hint": str(base)}
    data.setdefault("edit_hint", str(base))
    return data


def list_pages(root: Path | None = None) -> list[WikiPage]:
    data = load_index(root)
    pages: list[WikiPage] = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        sid = str(section.get("id") or "").strip()
        stitle = str(section.get("title") or sid)
        for page in section.get("pages") or []:
            if not isinstance(page, dict):
                continue
            pid = str(page.get("id") or "").strip()
            if not pid:
                continue
            pages.append(
                WikiPage(
                    id=pid,
                    title=str(page.get("title") or pid),
                    file=str(page.get("file") or f"{pid}.md"),
                    section_id=sid,
                    section_title=stitle,
                )
            )
    return pages


def get_page(page_id: str, root: Path | None = None) -> WikiPage | None:
    want = str(page_id or "").strip()
    for page in list_pages(root):
        if page.id == want:
            return page
    return None


def read_page_markdown(page_id: str, root: Path | None = None) -> tuple[WikiPage, str]:
    page = get_page(page_id, root)
    if page is None:
        raise FileNotFoundError(f"Wiki-Seite unbekannt: {page_id}")
    path = page.path()
    base = (root or WIKI_ROOT).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise FileNotFoundError("Ungültiger Wiki-Pfad") from exc
    if not path.is_file():
        raise FileNotFoundError(f"Wiki-Datei fehlt: {page.file}")
    text = path.read_text(encoding="utf-8")
    # optional YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].lstrip("\n")
    return page, text


def render_markdown(md: str) -> str:
    """Kompakter MD→HTML für Wiki (ohne Extra-Dependency)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_code = False
    code_lang = ""
    code_buf: list[str] = []
    list_type: str | None = None

    def flush_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    def inline(text: str) -> str:
        s = escape(text)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        # Bilder vor normalen Links
        s = re.sub(
            r"!\[([^\]]*)\]\(([^)]+)\)",
            r'<img src="\2" alt="\1" loading="lazy" />',
            s,
        )
        s = re.sub(
            r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)",
            r'<a href="\2" target="_blank" rel="noopener">\1</a>',
            s,
        )
        return s

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            if in_code:
                out.append(f'<pre class="code"><code class="lang-{escape(code_lang)}">')
                out.append(escape("\n".join(code_buf)))
                out.append("</code></pre>")
                code_buf = []
                in_code = False
                code_lang = ""
            else:
                flush_list()
                in_code = True
                code_lang = line[3:].strip()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if not line.strip():
            flush_list()
            i += 1
            continue

        if line.strip() == "---":
            flush_list()
            out.append("<hr>")
            i += 1
            continue

        img_only = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line.strip())
        if img_only:
            flush_list()
            alt = escape(img_only.group(1))
            src = escape(img_only.group(2), quote=True)
            out.append(
                f'<figure class="wiki-fig"><img src="{src}" alt="{alt}" loading="lazy" />'
                f"<figcaption>{alt}</figcaption></figure>"
            )
            i += 1
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        if line.startswith("> "):
            flush_list()
            note_lines = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith("> "):
                note_lines.append(lines[i][2:])
                i += 1
            out.append('<div class="note">' + "<br>".join(inline(x) for x in note_lines) + "</div>")
            continue

        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            if list_type != "ul":
                flush_list()
                out.append("<ul>")
                list_type = "ul"
            out.append(f"<li>{inline(m.group(1))}</li>")
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            if list_type != "ol":
                flush_list()
                out.append("<ol>")
                list_type = "ol"
            out.append(f"<li>{inline(m.group(2))}</li>")
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(
            r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", lines[i + 1]
        ):
            flush_list()
            rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|")
                if re.match(r"^[\s|:-]+$", lines[i]):
                    i += 1
                    continue
                cells = [inline(c.strip()) for c in raw.split("|")]
                tag = "th" if not rows else "td"
                rows.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
                i += 1
            out.append("<table>" + "".join(rows) + "</table>")
            continue

        flush_list()
        # Absatz: Folgezeilen ohne Leerzeile anhängen
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,3}\s|[-*]\s|\d+\.\s|```|> |---\s*$|\|)", lines[i]
        ):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{inline(' '.join(x.strip() for x in para))}</p>")

    flush_list()
    if in_code:
        out.append(f'<pre class="code"><code>{escape(chr(10).join(code_buf))}</code></pre>')
    return "\n".join(out)


def index_payload(root: Path | None = None) -> dict[str, Any]:
    base = root or WIKI_ROOT
    data = load_index(base)
    sections_out = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        pages_out = []
        for page in section.get("pages") or []:
            if not isinstance(page, dict):
                continue
            pid = str(page.get("id") or "").strip()
            if not pid:
                continue
            rel = str(page.get("file") or "")
            pages_out.append(
                {
                    "id": pid,
                    "title": str(page.get("title") or pid),
                    "file": rel,
                    "path": str((base / rel).resolve()) if rel else "",
                }
            )
        sections_out.append(
            {
                "id": str(section.get("id") or ""),
                "title": str(section.get("title") or ""),
                "pages": pages_out,
            }
        )
    return {
        "ok": True,
        "wiki_root": str(base.resolve()),
        "index_file": str((base / INDEX_NAME).resolve()),
        "format": "markdown",
        "edit_hint": (
            "Kapitel als Markdown unter wiki/ bearbeiten; "
            "Navigation in wiki/index.yaml ergänzen. "
            "Hilfe (App-Bedienung) bleibt app_mele/help.html."
        ),
        "sections": sections_out,
    }


def page_payload(page_id: str, root: Path | None = None) -> dict[str, Any]:
    page, md = read_page_markdown(page_id, root)
    return {
        "ok": True,
        "id": page.id,
        "title": page.title,
        "section_id": page.section_id,
        "section_title": page.section_title,
        "file": page.file,
        "path": str(page.path()),
        "format": "markdown",
        "markdown": md,
        "html": render_markdown(md),
    }
