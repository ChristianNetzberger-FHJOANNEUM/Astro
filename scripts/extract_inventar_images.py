"""Extrahiert Inventar-Fotos aus dem HTML und verknüpft sie in hardware.md.

Zielstruktur:
  wiki/inventar/media/<ID>_01.jpg  …
  wiki/inventar/hardware.md        (mit ![](/wiki-media/…) unter jeder Komponente)

Später: dieselben IDs für FOV/Brennweite im 360-Viewer.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = Path(r"C:\Astro\Docs\Inventory\Astro_Inventar_V1_Ausfuehrlich.html")
MEDIA = ROOT / "wiki" / "inventar" / "media"
MD = ROOT / "wiki" / "inventar" / "hardware.md"
URL_PREFIX = "/wiki-media"


def _decode_data_uri(src: str) -> tuple[str, bytes] | None:
    m = re.match(r"data:(image/[\w+.-]+);base64,(.+)$", src, re.S)
    if not m:
        return None
    mime = m.group(1).lower()
    raw = base64.b64decode(re.sub(r"\s+", "", m.group(2)))
    ext = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/pjpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".bin")
    return ext, raw


def extract() -> dict[str, list[Path]]:
    html = HTML.read_text(encoding="utf-8")
    MEDIA.mkdir(parents=True, exist_ok=True)
    # alte extrahierte Dateien ersetzen
    for old in MEDIA.glob("*"):
        if old.is_file():
            old.unlink()

    # Abschnitte an h1/h2 splitten, Figuren dem letzten Inventar-ID zuordnen
    token_re = re.compile(
        r"(<h([12])[^>]*>(.*?)</h\2>)|(<(?:div|figure) class=\"figure\">(.*?)</(?:div|figure)>)",
        re.S | re.I,
    )
    current_id = "_intro"
    by_id: dict[str, list[tuple[str, bytes, str]]] = {}
    id_pat = re.compile(r"\b([A-Z]{2,4}-\d{3})\b")

    for m in token_re.finditer(html):
        if m.group(1):  # heading
            text = re.sub(r"<[^>]+>", "", m.group(3))
            text = re.sub(r"\s+", " ", text).replace("↑ Inhalt", "").strip()
            found = id_pat.search(text)
            current_id = found.group(1) if found else "_intro"
            continue
        block = m.group(5) or ""
        src_m = re.search(r'src="(data:image/[^"]+)"', block)
        alt_m = re.search(r'alt="([^"]*)"', block)
        cap_m = re.search(r'class="caption"[^>]*>(.*?)</', block, re.S)
        if not src_m:
            continue
        decoded = _decode_data_uri(src_m.group(1))
        if not decoded:
            continue
        ext, data = decoded
        alt = (alt_m.group(1) if alt_m else "") or "Inventarfoto"
        cap = re.sub(r"<[^>]+>", "", cap_m.group(1)).strip() if cap_m else ""
        caption = cap or alt
        # Hero-/TOC-Galerie ohne Inventar-ID überspringen (meist Duplikate)
        if current_id == "_intro":
            continue
        by_id.setdefault(current_id, []).append((ext, data, caption))

    written: dict[str, list[Path]] = {}
    for cid, items in by_id.items():
        paths: list[Path] = []
        for i, (ext, data, _cap) in enumerate(items, start=1):
            name = f"{cid}_{i:02d}{ext}"
            path = MEDIA / name
            path.write_bytes(data)
            paths.append(path)
        written[cid] = paths
        print(f"{cid}: {len(paths)} image(s)")
    return written


def update_markdown(by_id: dict[str, list[Path]]) -> None:
    md = MD.read_text(encoding="utf-8")
    # alte Media-Links / Foto-Hinweise entfernen
    md = re.sub(
        r"\n> \*\[Inventarfotos:.*?\]\*\n",
        "\n",
        md,
        count=1,
    )
    md = re.sub(
        r"\n!\[([^\]]*)\]\(/wiki-media/[^)]+\)\n(?:\*[^\n]+\*\n)?",
        "\n",
        md,
    )
    md = re.sub(r"\nFotodokumentation des vorhandenen Teils\.\n", "\n", md)

    def gallery(cid: str) -> str:
        paths = by_id.get(cid) or []
        if not paths:
            return ""
        lines = ["", f"**Fotodokumentation ({cid})**", ""]
        for i, path in enumerate(paths, start=1):
            url = f"{URL_PREFIX}/{path.name}"
            lines.append(f"![{cid} Foto {i}]({url})")
            lines.append("")
        return "\n".join(lines)

    # Nach jeder ## ID-Überschrift Galerie einfügen (nach der ersten Tabelle)
    heading_re = re.compile(r"(^## ([A-Z]{2,4}-\d{3})\b[^\n]*\n)", re.M)

    def inject_after_section(match: re.Match[str]) -> str:
        head = match.group(1)
        cid = match.group(2)
        return head  # Galerie kommt nach Tabelle — zweiter Pass

    # Einfacher: vor "Funktion und Verwendung" bzw. am Ende der Section-Tabelle
    section_re = re.compile(
        r"(^## ([A-Z]{2,4}-\d{3})\b[^\n]*\n)(.*?)(?=^## [A-Z]{2,4}-\d{3}\b|^# \d|\Z)",
        re.M | re.S,
    )

    def repl_section(match: re.Match[str]) -> str:
        head, cid, body = match.group(1), match.group(2), match.group(3)
        # vorhandene Galerie-Blöcke dieser ID entfernen
        body = re.sub(
            rf"\n\*\*Fotodokumentation \({re.escape(cid)}\)\*\*\n(?:\n!\[[^\]]*\]\(/wiki-media/[^)]+\)\n)*",
            "\n",
            body,
        )
        gal = gallery(cid)
        if not gal:
            return head + body
        # nach erster Markdown-Tabelle einfügen
        table_end = re.search(r"(\n\|[^\n]+\|\n(?:\|[^\n]+\|\n)+)", body)
        if table_end:
            pos = table_end.end()
            body = body[:pos] + gal + body[pos:]
        else:
            body = gal + body
        return head + body

    md = section_re.sub(repl_section, md)

    # Intro-Galerie (oft Duplikate vor den Detail-Überschriften) nicht einbinden —
    # Zuordnung läuft über <ID>_01.jpg bei jeder Komponente.
    md = re.sub(
        r"\n\*\*Übersichtsfotos\*\*\n(?:\n!\[[^\]]*\]\(/wiki-media/[^)]+\)\n)*",
        "\n",
        md,
    )

    # Hinweis oben
    if "wiki/inventar/media/" not in md:
        md = md.replace(
            "Bearbeiten: `wiki/inventar/hardware.md`",
            "Fotos: `wiki/inventar/media/<ID>_01.jpg` · "
            "Bearbeiten: `wiki/inventar/hardware.md`",
            1,
        )

    MD.write_text(md, encoding="utf-8", newline="\n")
    print(f"Updated {MD}")


def main() -> None:
    by_id = extract()
    update_markdown(by_id)
    total = sum(len(v) for v in by_id.values())
    print(f"Done: {total} images -> {MEDIA}")


if __name__ == "__main__":
    main()
