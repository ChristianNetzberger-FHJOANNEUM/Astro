# Astro-VR Architektur v0.1 (Prüfung)

> Quelle: externer Entwurf, geprüft im Repo am 2026-10-11
> Stand: **Grundlage akzeptiert.** Der nächste Schnitt ist [XR-6a](astro-vr-architektur-v0.2.md), noch ohne Code.

Die Quest soll eine zweite Darstellung derselben `mele_app` werden, vor allem für den 360°-Himmel. Die App bleibt die Instanz für Katalog, Ort, Geräte und Befehle. Diese Seite hält fest, was an dem Entwurf passt und was der vorhandene Code schon anders löst.

## Was übernommen wird

Eine App, zwei Renderer. Keine zweite Astro-Anwendung, keine zweite Datenbank, keine Gerätebefehle aus dem VR-Renderer, kein Plugin-Framework. Desktop-Funktionen bleiben. Der Server berechnet den Sternkatalog nicht pro Frame und nicht jede Sekunde neu.

Der Himmel im Browser darf zwischen zwei Katalogen weiterlaufen. Ein neuer Python-Dienst ist dafür nicht nötig.

Die Simulationszeit gilt pro Viewer, nicht global. Die echte Uhr läuft immer. Die Quest zeigt zunächst den aktuellen Himmel. Der Desktop darf daneben einen anderen Zeitpunkt zeigen, so wie er das heute schon tut. Eine spätere Kopplung wäre ein eigener Schalter, nicht der Normalfall.

Die Nordlage des Gartenpanoramas ist eine gemeinsame Definition. Dieselbe `north`- und `srcw`-Angabe, dieselbe Azimut-Nullrichtung. Zwei unabhängig kalibrierte Kugeln wären ein Fehler.

GoTo, Stop und NINA bleiben die vorhandenen Backend-Routen und stehen hinter der Mehrclient-Koordination. Das ist XR-8, nicht der nächste Schritt.

## Was der Code heute schon tut

| Thema | Wo | Verhalten |
|---|---|---|
| Sternkatalog | `data/catalogs/sky.sqlite`, `mele/catalog.py` `query_overlay`, `GET /sky-overlay` | Python rechnet RA/Dec nach Azimut/Höhe und filtert unter dem Horizontprofil |
| Sternzeit | `mele/sky.py` `gmst_degrees`, `lst_degrees`, `radec_to_az_alt` | Meeus, für die Anzeige. Dieselbe Formel steht noch einmal in `app_mele/pano.html` |
| Ephemeriden | `mele/ephemeris.py` | Sonne, Mond, Planeten, über dasselbe Overlay, nicht im Browser |
| Desktop-Himmel | `app_mele/pano.html`, Three.js r170, `THREE.Points` | Bekommt Az/Höhe als JSON. Live-Modus holt das Overlay alle 15 Sekunden neu, nicht pro Frame |
| Zeit im Desktop | Eingabe, „jetzt“, Fotozeit, Schritt-Knöpfe, `chk-live` | Pro geöffnetem Viewer. Keine globale Simulationsuhr auf dem Server |
| Ort | Query `lat`/`lon` an `/sky-overlay`, sonst EXIF oder `configs/mele.yaml` | Kein eigener Zeitdienst |
| Nord, Desktop | `azAltToVec`: Azimut plus `northOffset` | `northOffset` aus `north` / `srcw` |
| Nord, VR | `app_mele/vr.html`: `sphere.rotation.y = northOffset + 90°` | Dieselbe Quelle, andere Formel. Sterne sind dort nicht gezeichnet |
| Horizont für Sterne | `horizon.json` über `_horizon_alts` | Nicht die PNG-Alpha-Maske. Die Maske ist das sichtbare Gartenfoto |
| VR-Stand | `/vr-view`, HTTPS, Quest, dunkler Himmel, transparentes PNG | XR-1. Der Hinweis in der Seite sagt, dass Sterne nur in der 360-Ansicht liegen |
| Bibliothek | `app_mele/static/three/three.module.js` | Eine Kopie, beide Viewer. Kein CDN |

`pano.html` ist die laufende Desktop-Schleife mit NINA-Polling, Labels und GoTo. Sie wird nicht in den VR-Renderloop gezogen. Das bleibt ADR-VR-003.

## Funktionsmatrix

| Funktion | Modul | Desktop | VR | Gemeinsam | Risiko |
|---|---|---|---|---|---|
| Katalog und Overlay | `query_overlay`, `/sky-overlay` | ja | nein | VR ruft dieselbe Route mit `stem`, `lat`, `lon`, `when` | gering, solange die Route unverändert bleibt |
| Massenrechnung RA/Dec | `mele/sky.py` | ja | nein | Python bleibt die Quelle für das Overlay | ein zweites JS-Modul wäre die dritte Kopie |
| Einzelobjekt im Viewer | Funktionen in `pano.html` | ja | nein | vorerst dort lassen | Herauslösen heißt `pano.html` anfassen |
| Planeten und Mond | `mele/ephemeris.py` | ja | nein | über das Overlay | nicht nach JavaScript portieren |
| Live-Zeit | 15-Sekunden-Timer im Desktop | ja | nein | Quest startet mit der echten Uhr | keine Server-Simulationsuhr |
| Garten-Nord | `north` / `srcw` | Formel A | Formel B | erst Polaris in beiden prüfen | ohne diesen Test keine Sterne in VR |
| Horizont ausblenden | `horizon.json` | ja | nein | `stem` an `/sky-overlay` | PNG-Alpha nicht noch einmal abtasten |
| GoTo, NINA, Guiding | bestehende Routen, Starter in `mele/` | ja | nein | erst XR-8 | Mehrclient ist `OFFEN` |
| Three.js | r170, eine Datei | ja | ja | dieselbe Datei | keine zweite Bibliothek |

## Korrektur am Entwurf

Die Aufgabenteilung „Katalog vom Server, Bewegung im Browser“ ist das Ziel für einen flüssigen VR-Himmel. Sie ist nicht der erste Schnitt.

Heute liefert der Server fertige Azimut/Höhe. Der Desktop legt daraus einmal eine `THREE.Points`-Geometrie und ersetzt sie alle 15 Sekunden im Live-Modus. Eine Kugelrotation wäre nur richtig, wenn die Punkte im Äquatorialsystem lägen. Die vorhandenen Punkte sind schon horizontal. Sie einfach mit der Sternzeit zu drehen, verschiebt den Himmel gegen das Gartenfoto.

Deshalb die kleinste Änderung, wenn der Sternenhimmel an der Reihe ist:

1. Dieselben Query-Parameter wie der Desktop an `/sky-overlay`.
2. Dieselbe Punktwolke wie in `addDiscs`, in der VR-Szene, unterhalb des geometrischen Horizonts bereits vom Server entfernt.
3. Polaris und die vier Himmelsrichtungen gegen den Desktop prüfen, bevor irgendetwas an `pano.html` geändert wird.
4. Erst wenn das Overlay die Quest ausbremst, Punkte im Äquatorialsystem halten und nur die Orientierung mit der Sternzeit nachführen. Das ist eine Optimierung, keine Voraussetzung.

Ein gemeinsames JavaScript-Modul `astro-core` wird nicht angelegt, solange `mele/sky.py` das Overlay rechnet und `pano.html` die einzige zweite Kopie für Einzelobjekte ist. Neue Verzeichnisnamen `viewer-vr`, `vr-ui` und `device-services` bleiben Rollen, keine Pakete.

## Einordnung in die Roadmap

| Entwurf | Entspricht | Wann |
|---|---|---|
| Phase 0, diese Prüfung | diese Seite | jetzt, ohne Code |
| Gemeinsamer Sternenhimmel | XR-6, erster dünner Schnitt nur über `/sky-overlay` | nach bestandener Nordprüfung |
| Dashboard mit Controllern | XR-3 und XR-7 | nach dem Himmel, nur lesen |
| GoTo, NINA, Guiding | XR-8 | nach der Mehrclient-Koordination |

XR-2 bis XR-5 (schwebendes Foto, Galerie, Plate-Solve) werden durch diesen Entwurf nicht gestrichen und nicht vorgezogen. Der Sternenhimmel ist die gewünschte nächste inhaltliche Stufe für die Quest, nicht ein Umbau der App.

## Offene Punkte, erst beim Schnitt zu klären

- Die beiden Nordformeln und die Gruppen-Drehung sind in [v0.2](astro-vr-architektur-v0.2.md) ausgerechnet. Die Headset-Drehung bleibt eine Quest-Prüfung, keine stille Korrektur.
- Ob die Quest `/sky-overlay` über den Caddy-Pfad erreichen darf. Heute sind nur `/vr-view`, `/vr/current`, Static, Media und Export freigegeben. Ein neues Präfix braucht eine bewusste Ergänzung der Caddyfile, keinen offenen Proxy.
- Headset-Nordkalibrierung bleibt außerhalb von XR-6-Start. Zuerst gilt die Nordmarke des Fotos.
- Präzession, Nutation und Eigenbewegung sind in `mele/sky.py` nicht eingebaut. Für die Anzeige bleibt die dort dokumentierte Genauigkeit. Keine zusätzliche Theorie, bevor Polaris sitzt.

## Verwandte Seiten

- [Astro-VR Architektur v0.2](astro-vr-architektur-v0.2.md) — XR-6a
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
- [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md) — ADR-VR-001 bis ADR-VR-003
- [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md)
- [Sternzeit, RA und Azimut](sternzeit-ra-azimut.md)
