# Beiträge & KI-Antworten

Dieses Wiki speichert **Wissen** (Astronomie, Inventar, Galerie).  
Die **App-Bedienung** (Horizont, NINA, Wetter, …) bleibt unter **Hilfe** (`app_mele/help.html`).

## Empfohlenes Format: Markdown

| Format | Empfehlung |
|--------|------------|
| **Markdown (`.md`)** | **Ja** — lesbar, diff-freundlich, KI-Antworten lassen sich direkt einfügen |
| HTML | Nur wenn nötig; schwieriger zu pflegen und zu mergen |
| PDF / DOCX | Nein — nicht versionsfreundlich |

**Pfad im Repo:** `wiki/` (neben `app_mele/`, `mele/`, …)

**Navigation:** `wiki/index.yaml` — neue Kapitel hier eintragen.

## So persistierst du eine KI-Antwort

1. Neues File anlegen, z. B. `wiki/knowledge/mein-thema.md`
2. Inhalt als Markdown speichern (Überschriften mit `#` / `##`, Listen, Formeln als Klartext oder Code)
3. In `wiki/index.yaml` unter der passenden Section eintragen:

```yaml
- id: mein-thema
  title: Mein Thema
  file: knowledge/mein-thema.md
```

4. Wiki in der App neu laden (F5) — die Seite erscheint links in der Navigation.

Optional: am Dateianfang Quelle notieren:

```markdown
> Quelle: Chat mit Cursor, 2026-10-03 · Thema: Sternzeit
```

## Inventar & Galerie

- **Inventar-Text:** `wiki/inventar/hardware.md`
- **Inventar-Fotos:** `wiki/inventar/media/<ID>_01.jpg` (z. B. `OKU-001_01.jpg`) — im Wiki unter `/wiki-media/…`
- **Optik-Parameter (FOV später):** `wiki/inventar/components.yaml` — IDs = Foto-IDs
- **Galerie:** `wiki/galerie/beste-fotos.md` + später `wiki/galerie/media/`

Fotos aus dem Original-HTML neu extrahieren:

```text
python scripts/extract_inventar_images.py
```

## Tipps für kompakte Kapitel

- Ein Thema pro Datei
- Kurz einleiten, dann Formeln / Schritte
- Verweise auf App-Hilfe statt Workflows zu duplizieren
