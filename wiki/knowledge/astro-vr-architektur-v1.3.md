# Astro-VR Architektur v1.3 — XR-8f Zielführung

> Quelle: abgenommenes [v1.2](astro-vr-architektur-v1.2.md)
> Stand: **Auf der Quest bestätigt** am 2026-10-11. Nur `app_mele/vr.html`. Keine neue Route, kein Python, kein `pano.html`. Fortschreibung: [v1.4](astro-vr-architektur-v1.4.md).

XR-8e bleibt. NGC-Filter, persönliche Auswahl, TYPEN, Unruhe, Zeitsteuerung, Sechserliste, roter Telrad, Hysterese, Tafelgröße und die Controllerrollen sind unverändert. NINA, SynScan, GoTo und Aufnahme bleiben unberührt.

## Navigationsziel

Ein eigenes Ziel, getrennt von Telrad-Kandidat, Detailansicht, Himmels-Schaltern und der Sechserliste. Es merkt sich Schlüssel, Namen, Art, Azimut, Höhe und, wenn vorhanden, RA/Dec.

`ZIEL FINDEN` steht in der Detailansicht über `ZURÜCK`. Es übernimmt das gerade gezeigte Objekt. Die Tafel bleibt offen. Die Sechserliste bleibt.

Dieselbe Übernahme kann später ein Objekt aus `/catalog/resolve` aufnehmen, auch wenn es nicht im Overlay steht. Die Suche selbst ist nicht gebaut. Ein solches Ziel bekommt die Herkunft `resolve` und wird nicht als Horizontfall behandelt, solange keine Overlay-Zeile dazu kommt.

## Grüner Telrad

Dieselben drei Ringe wie der rote Telrad, Durchmesser aus den vorhandenen Einstellungen, Farbe `0x4ade80`. Er sitzt auf der Sternschale an der gespeicherten Azimut/Höhe, mit derselben Norddrehung wie die übrigen Marken. Er folgt nicht dem Controller. Der rote Telrad bleibt unverändert und folgt weiter der Controller-Richtung.

Liegt der Winkel unter der Treffer-Einstellung, werden die grünen Ringe heller. Es gibt keine automatische Auswahl, kein Schließen der Tafel und kein GoTo.

## Pfeil und Winkel

Der Winkel ist der am Kugelmittelpunkt zwischen der Richtung zum roten Telrad und der Richtung zum Ziel:

`acos(clamp(dot(controllerRichtung, zielRichtung), -1, 1))`

Die Anzeige steht neben dem roten Telrad, zum Beispiel `M13 · 14,2°`, eine Nachkommastelle. Ihre Höhe ist mindestens 7, dieselbe Untergrenze wie die Namensschilder, und sie wächst mit der Einstellung Namen. Ohne gültige Controller-Richtung gibt es keine Gradzahl.

Der Pfeil ist ein kleines grünes Dreieck, etwa 0,7° lang, knapp außerhalb des äußeren roten Rings, in der Tangentialebene der Controller-Richtung. Seine Spitze zeigt auf den Anteil der Zielrichtung, der senkrecht zur Controller-Richtung steht. Die Himmelskugel und die Kamera drehen sich nicht. Es gibt keine Linie bis zur 480-m-Schale.

Unter 3° verschwindet der Pfeil. Dort wird die Richtung numerisch unruhig. Zahl und Ringe bleiben. Ab 165° ist die kürzeste Drehung nicht mehr stabil. Statt eines springenden Pfeils liegt dann ein zusätzlicher grüner Ring um den roten Telrad, ohne Vorzugsrichtung. Die Gradzahl läuft weiter. Ein kurzer grüner Zielstrahl ist nicht gebaut.

## Schalter aus und Horizont

Kommt das Ziel in der nächsten gültigen Overlay-Antwort vor, werden Azimut und Höhe nachgeführt. LIVE und ein fester Zeitpunkt nutzen dieselbe Antwort wie der übrige Himmel. Eine verworfene oder fehlerhafte Antwort lässt die letzte Position stehen.

Fehlt das Ziel, weil sein Anzeigeschalter aus ist, bleibt die Identität. Der grüne Telrad bleibt auf der letzten Position. Die Anzeige erhält `fest`. Er wechselt nicht auf ein anderes Objekt. Ohne Overlay-Zeile kann der Browser die Position nicht neu rechnen.

Fehlt ein Ziel mit Herkunft Overlay, obwohl sein Schalter an ist, verschwindet der grüne Telrad. Die Anzeige lautet `Ziel unter Horizont`. Die Identität bleibt. Bei Messier ist das der Horizont. Bei NGC kann dieselbe Lücke auch von der Helligkeits- oder Bewertungsgrenze kommen. Der Server liefert die Ursache nicht mit.

## Zielhilfe

Die vorhandene Rolle `aimToggle` blendet den roten Telrad aus und wieder ein. Ist sie Griff und wird ausgeschaltet, endet auch das Navigationsziel. Pfeil, Winkel und grüner Telrad gehen mit. Das Wiedereinschalten zeigt nur den roten Telrad. Die Tafel bleibt über ihre eigene Taste bedienbar. Standard ist weiterhin keine Zielhilfe. Für den Test unter EINSTELLUNGEN, Tasten, `Zielhilfe` auf Griff stellen.

## Quest-Abnahme

1. Ein bereits ausgewähltes Objekt lässt sich mit `ZIEL FINDEN` markieren.
2. Der grüne Telrad steht an der Himmelsposition des Objekts.
3. Der rote Telrad bleibt mit dem Controller beweglich.
4. Der Richtungspfeil weist zum Ziel.
5. Der Winkelabstand folgt der Controllerbewegung, eine Nachkommastelle.
6. Ein Ziel außerhalb des Blickfelds lässt sich finden.
7. Nahe am Ziel passen Pfeil und Winkel zusammen. Unter 3° bleibt der Pfeil aus, die Zahl bleibt.
8. Ab 165°, auch bei einer Drehung von etwa 180°, springt der Pfeil nicht. Der Ersatzring und die Gradzahl bleiben stabil.
9. Innerhalb der Treffertoleranz werden die grünen Ringe heller. Es wird nichts ausgewählt und nichts geschlossen.
10. LIVE und ein Zeitsprung verschieben das Ziel mit dem Himmel. Ein fehlgeschlagener Abruf behält die letzte Position.
11. Messier oder NGC aus löscht das Ziel nicht. Die Anzeige erhält `fest`.
12. Zielhilfe aus beendet die Navigation. Zielhilfe an zeigt nur den roten Telrad.
13. NGC, Messier, Tafel und Preferences bleiben. Es geht kein Gerätebefehl hinaus.

Vor dem Test die App neu starten und die Quest-Seite neu öffnen.

## XR-8g, nur untersucht

Nicht gebaut. Festgelegt bleibt: Suche unter OBJEKTE, höchstens sechs Zeilen, Weiter und Zurück, nur `GET /catalog/search` und `GET /catalog/resolve`, kein Schreibzugriff, keine Freigabe von `/catalog/picks`. Beide Suchpfade brauchen eine eigene Freigabe auf Port 8443. Ein Treffer soll `adoptNavTarget` mit Herkunft `resolve` rufen.

Der Tastaturtest steht in [v1.4](astro-vr-architektur-v1.4.md). Die Suche selbst ist nicht gebaut.

Fällt das Systemfeld aus, wäre die Rückfalle eine kleine 3D-Tastatur aus vorhandenen Textknöpfen, seitenweise und ohne Scrollfläche. Die ist deutlich schwerer und erst nach dem Gerätetest zu bauen.

## Verwandte Seiten

- [Astro-VR Architektur v1.2](astro-vr-architektur-v1.2.md)
- [Astro-VR Architektur v1.4](astro-vr-architektur-v1.4.md) — XR-8g.1 Tastaturtest
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
