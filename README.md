# Astro

Session-Manager fuer Astronomie-Aufnahmen (Sonnenfinsternis, Lumix, Newton, ...).
NiceGUI am PC, Domänenlogik in `core/`. Originale auf der NAS (`N:\Astro`) bleiben unveraendert.

## Phase 1

Katalogisieren, Burst-Erkennung, Eclipse-Phasen, Browser-GUI.

### Setup

```powershell
cd C:\_Git\Astro
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Katalog aufbauen

```powershell
python -m core scan
python -m core summary
```

### App starten

```powershell
python -m app_astro
```

Browser: http://localhost:8081

- Links: Sessions unter `N:\Astro` (z.B. Sofi-26)
- Mitte: Burst-Gruppen mit JPG-Vorschau
- Rechts: EXIF, Phase, C2-Offset, Dateiliste
- Button **NAS scannen** liest Metadaten, benennt und verschiebt nichts

### Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## MeLE Astro-Computer

Separates Paket mele/ fuer den Garten-Mini-PC (Horizont, spaeter Sichtbarkeit).
Nicht Teil der Foto-GUI.

`powershell
python -m mele horizon media\CAM_20260923151419_0942_D.JPG
`

Ergebnis unter data/horizon/ (CSV, JSON, Overlay). Norden mit --north-x setzen.

