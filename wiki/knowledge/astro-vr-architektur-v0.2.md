# Astro-VR Architektur v0.2 — XR-6a Sternenhimmel

> Quelle: v0.1 plus die Präzisierung vom 2026-10-11
> Stand: **XR-6a abgenommen, 2026-10-11.** Dieselben charakteristischen Sternpositionen liegen auf dem Desktop und in der Quest. Die Punktwolke bis mag 5,5 rückt alle 15 Sekunden mit. Linien, Messier, Planeten und das Dashboard sind nicht dran.

[v0.1](astro-vr-architektur-v0.1.md) bleibt die Grundlage. Python (`mele/sky.py`, `mele/catalog.py`, `mele/ephemeris.py`) bleibt die astronomische Referenz. `GET /sky-overlay` bleibt die gemeinsame Quelle. Keine JavaScript-Astrometrie, keine zweite Datenbank, keine Änderung an GoTo, NINA oder der Mehrclient-Logik. Die [Quest-Roadmap](quest3-xr-roadmap.md) bleibt. XR-6a ist nur der erste dünne Schnitt von XR-6: Sterne im bestehenden Gartenpanorama, ohne Dashboard.

15 Sekunden Sternbewegung sind höchstens 3,75 Bogenminuten. Das reicht für die erste Ansicht. Interpolation kommt erst, wenn die Quest das als Ruck zeigt. Die Szene selbst läuft mit der Bildwiederholrate. Nur die Punktwolke wird ersetzt.

## 1. Koordinaten

Beide Viewer lesen `north` und `srcw` gleich:

`northOffset = 360 * north / srcw` (sonst 0).

Three.js r170, `SphereGeometry`: am Äquator liegt Texturspalte `u` bei Winkel `phi = u · 360°` auf

`x = -cos(phi)`, `z = sin(phi)`, danach `geometry.scale(-1, 1, 1)`, also `x = cos(phi)`, `z = sin(phi)`.

Die Nordspalte des Fotos hat `u = northOffset / 360`. Nach der Spiegelung liegt sie bei

`(cos northOffset, 0, sin northOffset)`.

### Desktop, `pano.html`

Die Kugel hängt direkt in der Szene, ohne Eltern-Drehung. `azAltToVec` setzt einen Stern auf

`viewLon = az + northOffset`, `phi = 90° − Höhe`,

`x = sin(phi) cos(viewLon)`, `y = cos(phi)`, `z = sin(phi) sin(viewLon)`.

Azimut 0, Höhe 0 ist damit genau die Nordspalte. Die Kamera startet mit `lon = northOffset`, `lat = 18` und `lookAt` auf denselben Vektor. Ziehen nach rechts erhöht `lon` und blickt nach Ost (`az = 90°`). Foto, Sterne und Maus sind im Desktop ein System.

### Quest, `vr.html`

Dieselbe Kugel liegt in einer Gruppe mit

`sphere.rotation.y = northOffset + 90°`.

Diese Drehung schiebt die Nordspalte auf `(0, 0, -1)`. Die Kamera mit Gierwinkel 0 blickt längs `-Z`. Der erste Blick ohne Headset ist also Nord, wie beabsichtigt. Azimut 90° (Ost) landet nach derselben Drehung auf `+X`, Süd auf `+Z`, West auf `-X`, sofern die Sterne **in der Gruppe** mit derselben `azAltToVec`-Formel sitzen und die Drehung mitmachen.

Die Maus der Quest-Seite erhöht `lon` wie der Desktop, die Blickrechnung ist aber eine Euler-Drehung um Y, kein `lookAt`. Plus 90° Gier blickt nach `-X`, also auf die West-Marke, nicht auf Ost. Das gilt nur für die Maus außerhalb der VR-Sitzung. In der Sitzung ist der Zeiger aus, die Headset-Pose zählt. Ob die Headset-Drehung nach rechts auf die Ost-Marke zeigt, sieht man nur auf der Quest.

Sterne im Weltkoordinatensystem mit der Desktop-Formel, neben der gedrehten Gruppe, liegen nicht auf dem Foto. Sie müssen Kinder von `sphere` sein.

Eine Abweichung wird dokumentiert und nicht still korrigiert.

### Kalibrierungsprüfung

Polaris allein reicht nicht. Er steht knapp neben dem Pol. Eine vertauschte Ost-West-Richtung verschiebt ihn kaum.

Vier temporäre Marken, Kinder von `sphere`, Höhe etwa 20°, damit sie über dem Gartenrand bleiben:

| Marke | Azimut | Erwartete Weltlage nach der Gruppen-Drehung |
|---|---|---|
| Nord | 0° | `(0, Höhe, -1)` |
| Ost | 90° | `(+X, Höhe, 0)` |
| Süd | 180° | `(0, Höhe, +Z)` |
| West | 270° | `(-X, Höhe, 0)` |

Abnahme auf der Quest, 2026-10-11: Nord liegt beim Betreten vorn, eine Rechtsdrehung des Kopfes zeigt Ost, danach Süd und West. Die Marken bleiben am Foto. Die Maus am PC ist kein Abnahmekriterium. Die Marken bleiben hinter `debugDirections=1`. XR-6a.2 legt Polaris und Vega mit derselben `azAltToVec`-Formel in dieselbe Gruppe. Quest, 2026-10-11: beide Sterne waren mit Namensschild sichtbar. Die Schilder hingen an der Kugel und gingen beim Neigen des Kopfes mit. XR-6a.3 ersetzt die zwei Schilder durch die Punktwolke bis mag 5,5. Quest, 2026-10-11: die Sterne sind sichtbar, das Vorrücken im 15-Sekunden-Takt ist erkennbar, und charakteristische Sternpositionen decken sich mit dem Desktop zur selben Zeit.

## 2. Overlay

`GET /sky-overlay` in `app_mele/main_app.py`, Rechnung in `query_overlay`.

| Parameter | Default | Bedeutung |
|---|---|---|
| `lat`, `lon` | keine | fehlen sie, Antwort 400 und leere Listen |
| `when` | jetzt, UTC | ISO-Zeit. Ohne Zeitzone wird UTC angenommen |
| `mag` | 5,5 | Grenzhelligkeit der gezeichneten Sterne |
| `stars`, `const`, `messier`, `planets` | 1 | an |
| `ngc` | 0 | aus |
| `dso_types` | leer | sonst Filter |
| `stem` | leer | ohne Stamm nur der geometrische Horizont (Höhe 0). Mit Stamm und vorhandener `{stem}.horizon.json` das Gartenprofil |

Ein Stern: `az`, `alt`, `mag`, `ra`, `dec`, dazu `hip`, `name`, `con` wenn vorhanden. Keine Farbe. Der Desktop macht daraus Größe und Grauwert (`starDisc` in `pano.html`).

Weiter: `lines` (`iau`, `az1`, `alt1`, `az2`, `alt2`), `labels`, `dso`, `bodies` (Sonne, Mond, Planeten, optional `phase`, `diam_deg`). Oben im JSON: `when`, `latitude_deg`, `longitude_deg`. Fehlt der Katalog, kommt `error`, Planeten können trotzdem da sein.

`/vr/current` liefert schon `stem`, `lat`, `lon`, `north`, `srcw`. Dieselben Werte gehen an das Overlay. XR-6a holt zuerst nur `stars=1` und die übrigen Schalter auf 0. Linien, Messier und Planeten bleiben aus, bis die Himmelsrichtungen sitzen.

`addDiscs` bleibt in `pano.html`. Die VR-Seite bekommt eine kurze eigene Punktwolke. Dieselbe Geometrie-Idee, kein Import aus der großen Datei.

## 3. Darstellung und Last

Ein `THREE.Points` in der Kugel-Gruppe, Three.js r170. Position aus `az`/`alt` wie `azAltToVec`, Radius knapp innerhalb 500, damit die Punkte vor dem Foto liegen. Größe aus `mag` wie `starDisc`. Alle 15 Sekunden neu laden, alte Geometrie und altes Material `dispose`. Kein Rechnen im Animationsframe.

Kein Abruf, solange die Seite verborgen ist oder kein Panorama geladen ist. Schlägt der Abruf fehl, bleibt die letzte Wolke stehen und die Statuszeile nennt den Fehler. Der Renderloop läuft weiter.

Bei Grenzhelligkeit 5,5 sind es die Katalogzeilen bis zu dieser Helligkeit, als JSON alle 15 Sekunden. Das ist ein Brocken, kein Strom pro Frame.

## 4. Caddy

In der bestehenden Site `https://vr.netzberger.at:8443` steht `/sky-overlay` in der Pfadliste. Kein Wildcard, kein `/catalog`, kein `/sky-track`, kein `/nina`. Query-Parameter hängen an derselben Route. DNS, Zertifikat, Firewall und die übrigen Pfade sind unverändert. Nach `caddy validate` hat `caddy reload` die laufende Instanz übernommen. Ein Aufruf über `192.168.0.176:8443` liefert 200, `/catalog` bleibt 404.

## 5. Test, jeder Schritt auf der Quest vor dem nächsten

1. Nordrechnung auf dieser Seite gegen das Foto: Blick beim Sitzungsstart ist die Nordspalte.
2. Vier Marken. Rechtsdrehung des Kopfes zeigt Ost. Maus außerhalb der Sitzung ist kein Abnahmekriterium.
3. `https://vr.netzberger.at:8443/sky-overlay` mit `lat`, `lon`, `stem`, `stars=1` und den übrigen Schaltern 0 liefert JSON. Vorher die Caddy-Zeile, danach erst der Aufruf.
4. Wenige Referenzsterne, darunter Polaris und ein zweiter benannter Stern. Vergleich mit dem Desktop zur selben `when`.
5. Sterne bis zur Grenzhelligkeit, Gartenprofil über `stem`.
6. Live-Takt 15 Sekunden. Ein fehlgeschlagener Abruf löscht die Wolke nicht.
7. Desktop und Quest nebeneinander, derselbe Zeitpunkt. Abgenommen 2026-10-11 an charakteristischen Sternpositionen.
8. Die Panorama-Bewegung bleibt flüssig. Kein neuer Python-Prozess.

Abnahme von XR-6a, 2026-10-11: die vier Marken stimmen, die Sternpositionen decken sich mit dem Desktop, das Gartenfoto ist unverändert, NINA und GoTo sind unberührt.

## Später, nicht in XR-6a

Dashboard, Zeitumschaltung in der Quest, Interpolation zwischen den 15 Sekunden, Sternbilder, Planeten, GoTo. Die Headset-Nordkalibrierung bleibt außerhalb. Zuerst gilt die Nordmarke des Fotos.

Geplante Dateien, sobald dieser Plan freigegeben ist: nur `app_mele/vr.html`, und getrennt davon eine Zeile in `C:\Caddy\Caddyfile`. Nicht `pano.html`, nicht `mele/sky.py`.

## Verwandte Seiten

- [Astro-VR Architektur v0.1](astro-vr-architektur-v0.1.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
- [Astro-VR Dauerbetrieb](astro-vr-dauerbetrieb.md)
