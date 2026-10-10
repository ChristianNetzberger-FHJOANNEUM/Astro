# astro.netzberger.at — öffentliche Plattform (Roadmap)

> Quelle: Chat mit Cursor, 2026-10-10 · Thema: öffentliche Astro-Website getrennt vom MeLE
> Stand: **Roadmap, kein Implementierungsauftrag.** Keine Subdomain, kein Webspace und keine Veröffentlichung werden dadurch eingerichtet.

Der MeLE bleibt die Steuerung der realen Ausrüstung und läuft im Feld ohne Internet. Diese Website ist ein anderes Produkt. Kurzfristig unverändert: immersive Quest-Stufe XR-1 laut [Quest-3-XR-Roadmap](quest3-xr-roadmap.md), lokal im Astro-LAN laut [Feldnetz-Spec](mele-feldnetz-quest-spec.md).

## Drei Adressen, drei Zonen

Namen sind Vorschläge. Sie werden nicht jetzt bei Lupinum angelegt.

| Adresse | Aufgabe | Zugang | Status |
|---|---|---|---|
| `astro.netzberger.at` | Öffentliche interaktive Plattform: Ausrüstung, Berichte, Fotos, später 360° | öffentlich, auch wenn der MeLE aus ist | `GEPLANT` |
| `vr.netzberger.at` | Lokaler immersiver Viewer für die Quest | nur Astro-LAN, Port 8443 | im Hausnetz eingerichtet, nicht diese Website |
| `control.netzberger.at` | Fernzugriff auf ausgewählte MeLE-Funktionen | privat, authentifiziert | `OPTIONAL`, später |

Die öffentliche Seite bekommt **veröffentlichte Kopien**: Bilder, Panoramen, Metadaten. Sie fragt den MeLE nicht live ab. Ein ausgewählter Session-Bericht kann später aus dem Archiv hinüberkopiert werden. Capture, NINA und die Montierung bleiben auf dem MeLE.

## Was Besucher sehen dürfen

| Inhalt | Öffentlich | Administrator | Gast bei einer Vorführung |
|---|---|---|---|
| Ausrüstung, Fotos, Berichte | ja | ja | ja, über die öffentliche Seite |
| 360°-Panorama und Galerie, nur lesend | `GEPLANT` | ja | ja, sobald veröffentlicht |
| Live-Preview, Wetter, Sessionstatus | nein | ja, in der Control-Zone | `OPTIONAL`, nur lesend und gefiltert |
| NINA, Montierung, GoTo, Capture | nein | nur nach Anmeldung und erst nach Prüfung aller Endpunkte | nein |

`app_mele/pano.html` wird nicht veröffentlicht. Diese Seite steuert NINA und GoTo. Ein späterer öffentlicher Viewer ist eine eigene, nur lesende Darstellung derselben Bild- und Norddaten (`north` / `srcw`, equirektangulares JPEG, Three.js). Interne Netze, Tailscale-Adressen und API-Ports stehen nicht im öffentlichen Inhalt.

Port 8082 wird nicht über einen öffentlichen Reverse-Proxy ins Internet gestellt. Ein Login auf einer Website ersetzt das nicht. Bevor irgendwer von außen die App sieht, sind die Endpunkte und besonders die Steuerbefehle auf Authentifizierung zu prüfen. Für den persönlichen Zugriff reicht vorerst das vorhandene Tailscale. Ein Tunnel (zum Beispiel Cloudflare) ist `OPTIONAL` und setzt voraus, dass am ZTE-Router kein Port für die App geöffnet wird.

## Damit der interaktive Weg offen bleibt

Die Plattform soll später Panoramen, eine Galerie und Club-Vorführungen tragen, ohne neu gebaut zu werden. Dafür gelten jetzt schon diese Grenzen, auch solange nichts davon entsteht:

- Inhalte sind Dateien und Metadaten, nicht die laufende App. Eine erste Fassung darf statisch sein (HTML, CSS, JavaScript), ohne Datenbank und ohne CMS.
- Kein CMS wählen, das eigenes JavaScript und lokale Bildpfade verbietet. Sonst lässt sich der 360°-Viewer später nicht auf derselben Seite ergänzen.
- Veröffentlichte Panoramen behalten die bestehende Nordkonvention, damit nicht eine zweite Orientierung entsteht.
- Vorschauen und exportierte JPEG/PNG/WebP, keine RAW- oder FITS-Dateien als Web-Textur.
- Die Quest-Galerie (XR-2 bis XR-4) und die öffentliche Galerie dürfen dieselben veröffentlichten Bilder meinen. Sie teilen sich nicht den Programmcode der MeLE-Steuerung.
- Raumschiff und Planetarium für Clubs bleiben die experimentellen Stufen XR-9 und XR-10 beziehungsweise eine spätere Lesefassung davon. Sie sind nicht Teil der ersten Website.

Lupinum kann DNS und, falls der Vertrag Webspace hergibt, die öffentliche Seite hosten. Ob Webspace für eine weitere Site im bestehenden Vertrag liegt, ist `OFFEN`.

## Reihenfolge, wenn es soweit ist

1. Öffentliche Seiten: Ausrüstung, Galerie, Berichte. Noch ohne Live-Daten.
2. Dieselbe Site um einen nur lesenden 360°-Bereich ergänzen.
3. Persönlicher Fernzugriff, zuerst über Tailscale, nicht über eine offene App.
4. Optional ein lesender Gastmodus für eine Vorführung, erst nach der Endpunkt-Prüfung.
5. Optional automatisches Kopieren fertiger Bilder aus dem Archiv.

Das steht hinter dem lokalen Quest-Panorama. Es ist kein Auftrag, die Website jetzt zu bauen.

## Verwandte Seiten

- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
- [MeLE Feldnetz, Reiserouter und Quest 3](mele-feldnetz-quest-spec.md)
- [Session Storage](mele-session-storage-weather-archive-spec.md) — Archiv als spätere Quelle veröffentlichter Kopien
