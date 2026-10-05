"""Einmal-Konverter: Astro-Inventar HTML → Markdown für wiki/inventar/."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


class ToMD(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip = 0
        self.row: list[str] = []
        self.table_rows: list[list[str]] = []
        self.buf = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style", "nav"):
            self.skip += 1
            return
        if self.skip:
            return
        if tag in ("h1", "h2", "h3", "h4"):
            self.stack.append(tag)
            self.buf = ""
        elif tag == "p":
            self.stack.append("p")
            self.buf = ""
        elif tag == "br":
            self.buf += "\n"
        elif tag == "li":
            self.stack.append("li")
            self.buf = ""
        elif tag == "table":
            self.table_rows = []
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.buf = ""
        elif tag == "img":
            pass  # Bilder später gesammelt ersetzen
        elif tag == "hr":
            self.out.append("\n---\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "nav"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag in ("h1", "h2", "h3", "h4") and self.stack and self.stack[-1] == tag:
            level = int(tag[1])
            text = re.sub(r"\s+", " ", self.buf).strip()
            text = text.replace(" ↑ Inhalt", "").replace("↑ Inhalt", "").strip()
            self.stack.pop()
            self.buf = ""
            if text:
                self.out.append("\n" + ("#" * level) + " " + text + "\n")
        elif tag == "p" and self.stack and self.stack[-1] == "p":
            text = re.sub(r"[ \t]+", " ", self.buf).strip()
            self.stack.pop()
            self.buf = ""
            if text:
                self.out.append("\n" + text + "\n")
        elif tag == "li" and self.stack and self.stack[-1] == "li":
            text = re.sub(r"\s+", " ", self.buf).strip()
            self.stack.pop()
            self.buf = ""
            if text:
                self.out.append("- " + text + "\n")
        elif tag in ("td", "th"):
            self.row.append(re.sub(r"\s+", " ", self.buf).strip())
            self.buf = ""
        elif tag == "tr":
            if any(self.row):
                self.table_rows.append(self.row)
            self.row = []
        elif tag == "table":
            if self.table_rows:
                hdr = self.table_rows[0]
                self.out.append("\n| " + " | ".join(hdr) + " |\n")
                self.out.append("| " + " | ".join("---" for _ in hdr) + " |\n")
                for r in self.table_rows[1:]:
                    while len(r) < len(hdr):
                        r.append("")
                    self.out.append("| " + " | ".join(r[: len(hdr)]) + " |\n")
                self.out.append("\n")
            self.table_rows = []

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        self.buf += data


def main() -> None:
    src = Path(r"C:\Astro\Docs\Inventory\Astro_Inventar_V1_Ausfuehrlich.html")
    dest = Path(__file__).resolve().parents[1] / "wiki" / "inventar" / "hardware.md"
    raw = src.read_bytes()
    html = raw.decode("utf-8")
    html = re.sub(r'src="data:image/[^"]+"', 'src=""', html)
    parser = ToMD()
    parser.feed(html)
    parser.close()
    body = "".join(parser.out)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body = body.replace("Arbeitsstand: 18. September 2026Filter", "Arbeitsstand: 18. September 2026. Filter")
    body = re.sub(r"^•\s+", "- ", body, flags=re.M)
    # Ersten H1 als Fließtext-Titel behandeln
    body = re.sub(
        r"^# Astro-Inventar[^\n]*\n+",
        "**Astro-Inventar – Version 1** (ausführliche Fassung)\n\n",
        body,
        count=1,
    )
    body = re.sub(r"^Ausführliche Fassung\n+", "", body)

    header = (
        "# Astro-Inventar (V1)\n\n"
        "> Quelle: `C:\\Astro\\Docs\\Inventory\\Astro_Inventar_V1_Ausfuehrlich.html` "
        "(und `.docx`). Eingebettete Fotos hier ausgelassen — "
        "Original-HTML/DOCX behalten die Bilder.\n\n"
        "Bearbeiten: `wiki/inventar/hardware.md` · Navigation: `wiki/index.yaml`.\n\n"
        "---\n\n"
        "> *[Inventarfotos: 48 Bilder im Original-HTML eingebettet; hier ausgelassen]*\n\n"
    )
    md = header + body + "\n"
    dest.write_text(md, encoding="utf-8", newline="\n")
    sample = dest.read_text(encoding="utf-8")
    assert "OKU-001" in sample and "Lacerta" in sample
    print(f"Wrote {dest} ({len(md)} chars, utf-8)")


if __name__ == "__main__":
    main()
