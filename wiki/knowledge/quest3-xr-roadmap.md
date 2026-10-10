# Quest 3 — XR-Architektur und langfristige Roadmap

> Quelle: Chat mit Cursor, 2026-10-10 · Thema: Quest-Roadmap neben der MeLE-App
> Stand: **Roadmap, kein Implementierungsauftrag.** Nichts davon ist `IN ENTWICKLUNG`. Keine Bibliothek, keine Route und keine Klasse wird dadurch angelegt.

Verbindung und der erste Panorama-Viewer: [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md) (ADR-VR-001 bis ADR-VR-003). Diese Seite wiederholt das nicht. Sie hält nur fest, welche späteren Wege offen bleiben, ohne die `mele_app` dafür umzubauen.

Die Stufen heißen hier **XR-1 bis XR-10**. Die Buchstaben Q1–Q3 in der Feldnetz-Spec bedeuten etwas anderes (Browser bereits bestätigt, Panorama als erste VR-Version, Steuerung erst danach). Dieselbe Nummer nicht für zwei Dinge verwenden.

## Zwei Richtungen

| Richtung | Was sie ist | Wo sie lebt |
|---|---|---|
| A + B, Beobachtung und Steuerzentrale | Immersive Ansicht und später Bedienung der bestehenden App | Dieselbe `mele_app`, Route später `/vr-view`, Daten über vorhandene APIs |
| C, Weltraumumgebungen | Raumschiff, Flug, Museum, Simulation | Eigenes Projekt, nicht ein Paket in `app_mele` |

Beide dürfen dieselben astronomischen Daten und später dieselben HTTP-Schnittstellen nutzen. Sie werden nicht dieselbe Anwendung. Die produktive Astro-Steuerung läuft ohne Quest, ohne WebXR und ohne eine native Headset-App.

## Was der Code heute hergibt

| Thema | Status |
|---|---|
| App auf `0.0.0.0:8082` | `IMPLEMENTIERT` |
| 2D-Viewer `/pano-view`, `app_mele/pano.html` | `IMPLEMENTIERT` |
| Three.js r170 lokal | Bibliothek, von `/vr-view` für WebXR benutzt. Kein CDN |
| Kugel `scale(-1, 1, 1)`, equirektangulares JPEG, Nord aus `north` / `srcw` | `IMPLEMENTIERT` im 2D-Viewer |
| Quest-Browser zeigt App und 2D-Panorama | praktisch bestätigt |
| `/vr-view`, `app_mele/vr.html` | Prototyp in der App. 2D am PC geprüft. Enter VR auf der Quest wartet auf HTTPS |
| WCS / Plate-Solving im Repo | nicht vorhanden, für XR-5 `GEPLANT` |
| Stellarium-Anbindung | `OPTIONAL`, nicht eingebaut |
| Native Quest-App, Unity, Godot, Unreal | nicht Teil dieses Repos |

Der 2D-Viewer bleibt die Fläche mit Himmel, Kalibrierung und NINA. WebXR kommt nicht in diese Schleife. Das steht in ADR-VR-003 und gilt weiter.

## XR-Stufen

Empfohlene Reihenfolge, keine starre Kette. Ein Raumschiff-Experiment darf parallel entstehen, solange es die App nicht anfasst.

| Stufe | Inhalt | Priorität | Status |
|---|---|---|---|
| XR-1 | Gartenpanorama, `immersive-vr`, Kopfbewegung, Start und Ende | hoch | Auf der Quest gesehen. Dauerbetrieb nach Reboot noch offen |
| XR-2 | Ein eigenes Foto als schwebende Fläche, Vorschau aus einer Session | hoch | `GEPLANT` |
| XR-3 | Controller: zeigen, wählen, verschieben, skalieren. Noch kein GoTo | hoch | `GEPLANT` |
| XR-4 | Galerie mehrerer Aufnahmen, Metadaten, offline wenn die Vorschau lokal liegt | mittel | `GEPLANT` |
| XR-5 | Foto an der Himmelsposition: RA/Dec, Maßstab, Drehung, Gesichtsfeld, optional WCS | mittel | `GEPLANT` |
| XR-6 | Planetarium über dem echten Horizont, Katalog und Ephemeriden der App, Headset-Nordkalibrierung | mittel | `GEPLANT` |
| XR-7 | Schwebende Statuspanels: Wetter, Montierung, Guiding, Vorschau. Nur lesen | mittel | `GEPLANT` |
| XR-8 | GoTo, Guiding, Capture aus VR | später | `OPTIONAL` |
| XR-9 | Eigenes Raumschiff oder eine Brücke | experimentell | `EXPERIMENTELL` |
| XR-10 | Flug, Monde, Sonnensystem | langfristig | `EXPERIMENTELL` |

XR-1 ist als eigene Seite `/vr-view` in der MeLE-App. Ohne Parameter verwendet sie das in der App geladene Panorama (`/vr/current`), derselbe Norden wie die 360-Ansicht. Ein Knopf **VR** öffnet dasselbe Bild. `pano.html` bleibt unverändert. Am PC: Mausziehen. Auf der Quest läuft Enter VR über `https://vr.netzberger.at:8443/vr-view`. Port 8082 bleibt HTTP. Was nach einem Neustart noch von Hand gestartet werden muss, steht im [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md). RAW und FITS werden nie direkt als WebGL-Textur geladen. Ein positioniertes Foto ist kein 3D-Modell des Objekts. Ein RA/Dec-Mittelpunkt allein reicht für XR-5 nicht.

XR-8 wartet auf die Mehrclient-Koordination in der Feldnetz-Spec. Eine Controllerbewegung löst keinen Befehl aus. Bestätigung bleibt Pflicht. Befehle gehen nur durch die bestehenden Backend-Routen.

XR-9 hat zwei denkbare Modi, beide außerhalb der App: Simulation ohne Teleskop, oder eine Brücke, die MeLE-Daten nur anzeigt. Die Sonnensystemsimulation ist nicht Teil des Cockpits, sondern XR-10.

## Werkzeuge

Für XR-1 bis XR-7 ist die Laufzeit **WebXR plus das vorhandene Three.js**. Kostenfrei, im Quest-Browser, keine native App, kein App-Store. Das Meta Immersive Web SDK wird frühestens geprüft, wenn Controller und Panels wirklich gebaut werden. Nicht in XR-1.

Native Engines nur für Richtung C, als eigenes Projekt:

| Werkzeug | Rolle | Kosten, privater Einstieg |
|---|---|---|
| Three.js, WebXR | XR-1 bis XR-8 | kostenlos (MIT / offener Standard) |
| Meta Immersive Web SDK | später prüfen | SDK kostenlos, API und Lizenz vor dem Einbau neu lesen |
| Unity Personal + Meta XR SDK | Kandidat für XR-9 | Personal innerhalb der dann gültigen Grenzen; vor Veröffentlichung neu prüfen |
| Godot + OpenXR | Alternative zu Unity | kostenlos (MIT); Quest-Plugins vorher prüfen |
| Unreal | nicht der Einstieg | kostenloser Start, kommerzielle Grenzen lizenzabhängig; schwere Assets für die Quest-GPU |
| Blender | Modelle, Export glTF/GLB | kostenlos; keine VR-Laufzeit |
| VS Code / Cursor | Editor | Editor kostenlos; KI-Werkzeuge können extra kosten |

Gekaufte Modelle, Plugins, Cloud und eine Store-Veröffentlichung können Geld kosten. Lizenztexte gelten zum Zeitpunkt der Veröffentlichung, nicht als Dauerzusage dieser Seite.

## Architektur, die nicht verbaut werden darf

- Keine native Quest-App als Voraussetzung für den Astro-Betrieb.
- Keine VR-Engine im Python-Backend.
- Keine zweite Montierungs- oder Kamerasteuerung, auch nicht über Stellarium.
- Stellarium bleibt `OPTIONAL`: Objekttexte und Abgleich, keine eingebettete Desktopfläche, keine Laufzeitpflicht.
- Eine native App darf später per HTTP oder WebSocket lesen und, erst ab XR-8, bestätigte Befehle senden. Die App bleibt das Backend.
- Konzeptnamen wie `XRRuntime`, `PanoramaScene`, `GalleryScene` sind Verantwortlichkeiten, keine Dateien und keine Klassen. Sie werden nicht vorgezogen. Eine zweite Szene ist der Zeitpunkt, eine Interaktion herauszulösen, nicht XR-1.
- Die Rendering-Schleife pollt das Backend nicht pro Frame.
- Ein Absturz der Quest beendet keine Aufnahme.

## Offene Prüfungen, erst wenn die Stufe dran ist

- Dauerbetrieb nach Reboot, siehe [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md). Die Quest-URL selbst ist im Hausnetz schon in Betrieb.
- Headset-Nordkalibrierung vor XR-5 und XR-6, nicht vorher.
- Ob Session-Previews für XR-2 schon die richtige Größe und Deckung haben.
- WCS-Quelle, sobald XR-5 konkret wird. Im Repo gibt es sie noch nicht.
- Meta Immersive Web SDK gegen Three r170, sobald XR-3 mehr als ein eigener Raycaster wäre.
- Unity- oder Godot-Lizenz und Quest-Entwicklermodus, sobald XR-9 ein eigenes Projekt wird.

## Verwandte Seiten

- [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md)
- [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md)
- [Session Storage](mele-session-storage-weather-archive-spec.md) — Sessions und Vorschauen, keine zweite Bilddatenbank
- [astro.netzberger.at](astro-netzberger-roadmap.md) — spätere öffentliche Plattform, kein Teil dieser Quest-Stufen
