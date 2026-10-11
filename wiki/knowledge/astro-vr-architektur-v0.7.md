# Astro-VR Architektur v0.7 — Objektinfo im Dashboard

> Quelle: Abnahme des Controllerstrahls am 2026-10-11
> Stand: **Auf der Quest abgenommen, 2026-10-11.** Azimut und Höhe im Objektfenster rücken alle 15 Sekunden im Zehntelgrad. `TEST` ist danach entfernt. `OBJEKTE` bleibt.

Keine Teleskopbewegung, kein NINA, kein GoTo. Die Auswahl zeigt nur, was der Desktop im Infokasten aus dem Overlay schon anzeigt.

## Was der Desktop schon hat

`showInfo` in `pano.html` liest das angetippte Overlay-Objekt. Dieselben Felder stehen in `/sky-overlay`: Name, Art, Helligkeit, RA, Dec, Azimut, Höhe, beim Mond die Phase. RA und Dec formatiert der Desktop mit `fmtRa` und `fmtDec`. Das ist Anzeige, keine zweite Rechnung.

`/sky-track` zeichnet die Bahn über Stunden. `/catalog/favorites` und `/observe/tonight/markers` sind eigene Listen. Diese drei Routen sind auf Port 8443 nicht freigegeben. Die erste Objektinfo öffnet sie nicht und ändert Caddy nicht.

Die Quest holt heute Sterne, Sternbildlinien, Namen und `bodies`. Messier und NGC bleiben aus. Sonne, Mond und die Planeten über dem Gartenprofil sind damit schon in der letzten Antwort, ebenso benannte Sterne mit `az`, `alt`, `ra` und `dec`.

## Kennung, Sortierung, Update

`bodies` kommt in fester Reihenfolge aus `solar_system_bodies`: Sonne, Mond, dann Merkur bis Neptun. Der Horizontfilter lässt diese Reihe stehen und wirft nur unsichtbare Gestirne heraus. Die Liste sortiert `bodies` nicht noch einmal.

Danach benannte Sterne, aufsteigend nach `mag`, bei gleicher Helligkeit nach `name`. Höchstens sechs Einträge. Felder, die das Overlay wirklich hat: `id`, `name`, `kind`, `hip`, `ra`, `dec`, `az`, `alt`, `mag`, beim Mond `phase`. Nichts davon wird neu gerechnet. RA und Dec nutzen dasselbe Format wie `fmtRa` und `fmtDec`.

Die Kennung ist `kind` plus `hip`, sonst `kind` plus `id`, sonst `kind` plus `name`. Die Auswahl speichert diese Kennung, nicht die Zeilennummer. Ein 15-Sekunden-Update sucht dieselbe Kennung. Die Detailfläche bleibt offen. Nur wenn sich der Text ändert, wird diese eine Canvas neu gezeichnet. Zeilen-Texturen bleiben, solange Kennung und Beschriftung gleich sind. Verschwindet das Objekt, bleiben die letzten Zahlen und die Zeile `nicht mehr in der Liste`. Ein Overlay-Fehler schreibt `lastBodies` und `lastStars` nicht um.

## Liste

Die registrierte Schaltfläche `OBJEKTE` nutzt dieselbe Abzug-Regel wie in [v0.6](astro-vr-architektur-v0.6.md). Die Panelfläche selbst bleibt kein Treffer.

`OBJEKTE` zeigt höchstens sechs Zeilen aus der letzten erfolgreichen Overlay-Antwort. Zuerst die Gestirne aus `bodies`, dann benannte Sterne nach Helligkeit, bis sechs voll sind. Jede Zeile ist eine eigene Schaltfläche. Kein Scrollen, keine Suche, keine Favoriten.

## Detail

Der Abzug auf eine Zeile lässt das Panel offen und zeigt:

- Name
- Art
- RA und Dec in derselben Stunden- und Gradform wie der Desktop
- Azimut und Höhe aus dem Overlay, auf eine Nachkommastelle
- Helligkeit, wenn sie mitkommt
- Mondphase in Prozent, wenn sie mitkommt

Die Zahlen kommen aus dem Objekt, nicht aus einer neuen Python-Funktion. Alle 15 Sekunden, wenn das Overlay neu ist und dasselbe Objekt noch in der Antwort steht, werden Höhe und Azimut ersetzt. Fehlt es, weil es unter dem Gartenprofil liegt, bleibt der letzte Text und eine Zeile sagt, dass es nicht mehr in der Liste ist.

`TEST` ist nach der Abnahme entfernt. `OBJEKTE` bleibt.

## Grenzen

Nur `app_mele/vr.html`, sobald freigegeben. Kein Messier-Zeichnen, kein `/sky-track`, keine Favoriten, kein Tonight, keine neue Route, kein Caddy-Eintrag. GoTo bleibt aus, auch als Knopf.

## Abnahme

1. `OBJEKTE` öffnet die Liste. `TEST` ist entfernt.
2. `OBJEKTE` öffnet höchstens sechs Zeilen. Das Panel bleibt offen.
3. Ein Abzug auf eine Zeile zeigt Name, RA, Dec, Azimut und Höhe.
4. Dieselben Werte stehen zur selben Zeit im Desktop-Infokasten.
5. Ein Abzug neben den Flächen schließt das Dashboard wie bisher.
6. Nach dem erneuten Öffnen ist die Liste wieder aus der letzten Antwort, nicht aus einem gespeicherten Stand.
7. Der Sternenhimmel sieht aus wie zuvor.

## Verwandte Seiten

- [Astro-VR Architektur v0.6](astro-vr-architektur-v0.6.md)
- [Astro-VR Architektur v0.8](astro-vr-architektur-v0.8.md) — XR-3b Telrad, auf der Quest abgenommen
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
