# Astro-VR Architektur v1.14 — Tafel bleibt stehen

> Quelle: abgenommene Kamera in [v1.13](astro-vr-architektur-v1.13.md)
> Stand: **14. Oktober 2026, Nacht.** Auf der Quest bestätigt: Tafel bleibt stehen, Lights, Tubus abdecken, Darks, `ZURÜCK` und Wetterexport. Der virtuelle Monitor ist eingebaut und auf der Quest noch nicht geprüft. Nächstes Konzept: [v1.15](astro-vr-architektur-v1.15.md).

Ein Abzug neben der Tafel oder auf ihre freie Fläche lässt die Tafel stehen. Schließen geht nur über `SCHLIESSEN`. Das ersetzt das abgenommene XR-7b-Verhalten „Abzug auf leere Fläche blendet aus“.

## Bedienung

| Aktion | Wirkung |
| --- | --- |
| Abzug neben der Tafel | keine |
| Abzug auf die freie Tafelfläche | keine |
| `SCHLIESSEN` | Tafel ausblenden |
| Ziehen über `ZIEHEN` | verschieben, Weltposition bleibt |
| Anderes Katalogobjekt | dessen Detail öffnen |
| Tafel erneut einblenden | Übersicht neu vor dem Kopf |

`SCHLIESSEN` liegt rechts neben `ZIEHEN`, in jeder Tafel, und steht in `pointerButtons`. Ein Treffer darauf startet kein Ziehen. `syncPanelButtons` lässt beide Flächen sichtbar, auch nach dem Neuaufbau von Übersicht, Himmel, Montierung, Objekt, Session und Kamera.

`SCHLIESSEN` setzt nur `dashboard.visible` auf falsch. Objekt, `panelMode`, Sessionentwurf und ein laufender Aufnahmeauftrag bleiben. Es geht kein GOTO, kein STOP und kein anderer Serverbefehl hinaus. Die Quest ist die Oberfläche. Der Auftrag läuft auf dem MeLE.

## Wieder öffnen, später

Beim erneuten Öffnen zeigt `placeDashboard()` weiter die Übersicht vor dem Kopf und ruft `resetObjectPanel()` auf. Sichtbarkeit und Inhalt sind damit beim Öffnen noch gekoppelt. `SCHLIESSEN` selbst löscht den Inhalt nicht.

Für später, ohne die Navigation jetzt umzubauen: `placeDashboard()` überspringt `resetObjectPanel()`, wenn die Tafel nur ausgeblendet war. `panelMode`, `selectedItem` und der Sessionentwurf sind dann noch da. `syncPanelButtons()` und `paintDashboard()` zeichnen die letzte Tafel. Eine laufende Aufnahme erscheint wieder, weil die Kameratafel den Status beim Zeichnen liest. Die Position kann bleiben oder neu vor den Kopf gesetzt werden. Ein erstes Öffnen ohne vorherige Tafel zeigt weiter die Übersicht.

Keine Änderung an Backend, Caddy, Sessionverwaltung, Kamera oder NINA.

## Quest-Prüfung der Tafel

Auf der Quest bestätigt: `SCHLIESSEN` blendet die Tafel aus. Ein Danebenklick schließt sie nicht.

## Lights und Darks

`LIGHTS` und `DARKS` liegen nebeneinander. Jede Art behält ihre eigene Bildanzahl. Ein Wechsel überschreibt die andere Zahl nicht. Darks beginnen bei 0, solange die Session keine geplante Anzahl hat. Lights beginnen bei 1.

`AUFNAHME` auf Lights startet nur die Lights. Sind danach Darks größer als 0 und die Lights fertig, bleibt die Kameratafel offen. Die Meldung lautet: Tubus abdecken, kein Licht, danach die gewählte Zahl Darks. `TUBUS ABGEDECKT` startet die Darks. `OHNE DARKS` lässt sie aus. Das entspricht der Desktop-Rückfrage vor den Darks. Die Tafel springt dabei nicht zur Sessionliste.

## ZURÜCK speichert die Session

Nach Lights und Darks ist die Session noch offen. `ZURÜCK` in der Kameratafel schließt sie über `POST /astro/capture/session-close`. Das ist derselbe Close wie am Desktop: Status `closed`, Wetterdateien unter `weather/` im Sessionordner. Ein früherer Lauf speicherte das Wetter, nahm aber keine Darks auf, weil die Tafel nach den Lights zurückging.

Eine geschlossene Session steht nicht mehr unter den offenen. Deshalb war die Liste danach leer. Die gerade gespeicherte Session bleibt als Zeile `gespeichert` sichtbar, mit dem Wetterstatus. Ein Klick darauf öffnet keine neue Aufnahme. Eine laufende Aufnahme schließt `ZURÜCK` nicht. `SCHLIESSEN` blendet nur die Tafel aus.

## Quest-Prüfung dazu

Am späteren Abend des 14. Oktober 2026 hat der Ablauf auf der Quest gehalten: Lights, Hinweis zum Abdecken, Darks, `ZURÜCK`, Wetterexport.

## Virtueller Monitor, erster Schnitt

Eingebaut, auf der Quest noch nicht geprüft. Die Tafel, Lights, Darks, `ZURÜCK` und der Wetterexport bleiben wie bestätigt.

Der Monitor ist eine eigene Fläche neben der Tafel. `MONITOR` in der Kameratafel blendet ihn ein, `AUS` blendet nur ihn aus. `ZIEHEN` verschiebt ihn. Beides ändert weder Session noch Aufnahmeauftrag. Die Bildquelle ist `light_preview`. `phd2_fullframe`, `phd2_star` und `plate_solve` sind benannt und antworten noch mit „Quelle noch nicht vorhanden“.

Ein einzelnes Light, `frames` gleich 1, startet nach dem Speichern der RW2 einen eigenen Lauf. Eine Serie tut das nicht. `ZURÜCK` erzeugt danach dasselbe JPEG, das der Desktop aus der neuesten Light-Datei baut: `generate_preview` in `mele/preview_service.py`, Stretch nur im JPEG. Die RW2 bleibt unverändert. Liegen JPEG und Statistik schon, wird nicht neu gerechnet.

Die Statistik liest die linearen Bayer-Rohdaten ohne Debayer. Schwarz- und Weißwert kommen aus der Datei. Geliefert werden Hintergrund-Median, robustes Rauschen, Maximum, 99,9-%-Perzentil, Sättigungsanteil und ein Histogramm. Die senkrechte Achse im Monitor ist logarithmisch. Bild und Zahlen tragen denselben Dateinamen. Es gibt keine neue Spalte in der Session-Datenbank.

`GET /astro/capture/preview` und `GET /astro/capture/preview/file` sind lesend und starten keine Berechnung. Caddy gibt nur diese beiden Pfade zusätzlich frei, nicht `/phd2` und nicht `/astro/sessions/*`. Ein Analysefehler bleibt im Vorschaulauf. Der Aufnahmeauftrag läuft weiter. PHD2, FWHM, Sternzahl und Plate Solving sind nicht in diesem Schnitt.
