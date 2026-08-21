# Astro - Architektur

## Ziel

Software und Konfiguration in Git, Fotos auf der NAS (`N:\Astro`).
Die App ist ein Astro Session Manager; SoFi 2026 ist das erste Spezialmodul.

Siril bleibt fuer Convert/Register/Stack. Siril erkennt keine semantischen
Gruppen wie "Burst 17 rund um C2" - das macht `core/`.

## Schichten

```
app_astro/     NiceGUI, Port 8081
core/          Scan, EXIF, Burst, Eclipse, SQLite (kein NiceGUI)
N:\Astro       Originale: niemals umbenennen oder verschieben
```

Alles, was spaeter CLI, Siril-Export oder andere UIs braucht, gehoert in `core/`.

## Was nicht in Git liegt

- RAW, JPG, FITS, Videos
- `data/astro.sqlite` (lokaler Katalog)

## NAS-Konvention

```
N:\Astro\
  Sofi-26\
    Lumix\Camera\     Originale (RW2 + JPG), unveraendert
    Lumix\excluded\
    Siril\            bestehender Hand-Workflow (wird nicht importiert)
    siril_work\       vom Manager erzeugte Burst-Workspaces (Links)
      burst_058\
        P1046xxx.RW2   Hardlink/Symlink auf Original
        metadata.json
    resolve\          Schnitt (wird nicht importiert)
```

Spaetere Sessions (Mond, H-alpha, Newton, Deep Sky) als weitere Ordner unter `N:\Astro`.
Originale werden nicht nach originals/ umgezogen. Siril bekommt pro Burst einen
Ordner unter `siril_work/burst_NNN` mit Links, keine RAW-Kopien.

## Burst-Erkennung

Keine physischen Burst-Ordner noetig. Der Detektor gruppiert nach:

1. Zeitdifferenz aufeinanderfolgender Aufnahmen
2. Kameradateinummer (Lumix P1046662), falls EXIF nur sekundengenau ist

Konfigurierbar in `configs/app.yaml`:

- Abstand <= 0.2 s  -> gleicher Burst
- Abstand > 1.0 s   -> neuer Burst
- dazwischen: aufeinanderfolgende Dateinummern halten den Burst zusammen

SH30 (~30 fps) wird aus Framezahl/Dauer geschaetzt. JPG+RAW mit gleichem Stem
sind eine logische Aufnahme.

Arbeitsnamen fuer spaetere Siril-Sequenzen (Kopien, nicht Originale), z.B.:

`SOFI2026_C2_B017_0001.fit`

## Eclipse-Modul

`configs/sessions/sofi-26.yaml` haelt C1/C2/C3/C4 und optional
`camera_clock_offset_s`, falls die Kamerauhr nicht CEST ist.

Jedes Bild bekommt Phase und Offset relativ zu C2.

## Datenmodell (SQLite)

```
session          -- Sofi-26, spaeter Mond / Newton / ...
burst            -- logische Einheit fuer Siril-Sequences
image            -- frame_id = image.id (stabil), Pfad, EXIF, phase
siril_workspace  -- Pfad zum Burst-Ordner, Link-Modus
```

Session -> Phase -> Burst -> Frames. Siril denkt in Sequences; ein Burst ist eine Sequence.

## Siril-Workspace

Button "Siril-Workspace" erzeugt Links + metadata.json.
CLI: `python -m core workspace` (groesster Burst der ersten Session).

Als Naechstes: Siril-CLI starten, conversion.txt einlesen, Burst-Stack.

## Naechste Ausbaustufen

- Siril GUI/CLI mit Working Directory oeffnen
- conversion.txt -> frame_id Mapping
- Burst-Stack und spaeter Phasen-Zeitreihe
- Rating / Notizen in der GUI
- Deep-Sky: Lights/Darks/Flats/Bias
