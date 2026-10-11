# Astro-VR Architektur v0.4 — XR-6c Sonne, Mond und Planeten

> Quelle: Abnahme von [v0.3](astro-vr-architektur-v0.3.md) plus die Freigabe vom 2026-10-11
> Stand: **Auf der Quest abgenommen, 2026-10-11.** Sonne, Mond und Planeten sind mit Schild sichtbar. Die Desktop-Statuszeile nennt dieselben Gestirne, zum Beispiel `6 Gestirne`. Linien-Deckkraft 0,85 und Schildhöhe 7 bleiben.

Python bleibt die Quelle. `GET /sky-overlay` mit `planets=1` liefert `bodies[]`. Erde kommt nicht vor. Keine neue Rechnung, keine neue Route, kein Dashboard.

## Was das Overlay liefert

Geprüft an der laufenden App. Felder: `id`, `name`, `kind`, `az`, `alt`, `ra`, `dec`, `mag`, dazu bei Sonne und Mond `diam_deg` 0,5. Der Mond hat `phase` sowie `sun_az` und `sun_alt`. `kind` ist `sun`, `moon` oder `planet`. Namen: Sonne, Mond, Merkur, Venus, Mars, Jupiter, Saturn, Uranus, Neptun. Unter dem Gartenprofil fehlt das Gestirn in der Liste.

## Darstellung

Dieselbe Himmelsgruppe und dieselbe `azAltToVec`-Formel wie Sterne und Sternbilder. Eine flache Scheibe, `MeshBasicMaterial`, kein Licht, kein Bloom.

| Objekt | Farbe | Scheibenradius | Schild |
|---|---|---|---|
| Sonne | `0xfde68a`, Deckkraft 0,72 | 3,2 | Sonne |
| Mond | `0xe5e7eb`, Deckkraft 0,9 | 3,0 | Mond und Prozent, zum Beispiel `Mond 1%` |
| Planeten | je eine eigene Farbe, Deckkraft 0,9 | 1,8 | Katalogname |

Die Scheibe blickt zum Ursprung, das Schild ist ein Sprite und dreht bei Kopfneigung mit. Schildhöhe 7 und Linien-Deckkraft 0,85 bleiben. Der wahre Winkeldurchmesser 0,5° wäre auf der Quest kaum sichtbar. Die Mondphase steckt im Schild, nicht in einem Beleuchtungsshader. Der Desktop-Shader für die beleuchtete Mondkugel ist nicht übernommen.

Der 15-Sekunden-Takt holt Sterne, Linien, Namen und Gestirne in einer Antwort. Der neue Satz ersetzt den alten erst, wenn er fertig ist. Ein einzelnes Gestirn, das sich nicht bauen lässt, fällt weg. Ein fehlgeschlagener Abruf lässt den Himmel stehen. Namenstexturen bleiben nach dem Schlüssel erhalten. Die Mond-Textur wechselt nur, wenn sich die gerundete Phase ändert.

## Abnahme auf der Quest

Nach Neustart von `mele_app` die Seite neu öffnen. Die Statuszeile nennt die Zahl der Gestirne.

1. Sonne, Mond und die gerade über dem Garten stehenden Planeten liegen auf denselben Stellen wie im Desktop.
2. Die Sonne ist eine gedämpfte gelbe Scheibe, kein Blendfleck.
3. Das Mondschild zeigt die Phase in Prozent.
4. Die Namen bleiben bei Kopfneigung lesbar.
5. Sterne und Sternbilder sehen aus wie zuvor.
6. Der 15-Sekunden-Takt läuft weiter.
7. Saturn, Uranus und Neptun fehlen, solange sie unter dem Gartenprofil liegen.

## Danach

Das lesende Dashboard ist XR-7 und beginnt hier nicht.

## Verwandte Seiten

- [Astro-VR Architektur v0.3](astro-vr-architektur-v0.3.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
