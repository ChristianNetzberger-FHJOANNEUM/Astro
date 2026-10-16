# Astro-VR Architektur v1.15 — Sessionansicht

> Quelle: Monitor in [v1.14](astro-vr-architektur-v1.14.md)
> Stand: **16. Oktober 2026.** Auf der Quest geprüft. Eine gespeicherte Session zeigt Belichtung und ISO. Der Monitor zeigt das Vorschaubild und die Statistik. Nächster Entwurf: [v1.16](astro-vr-architektur-v1.16.md).

Eine Zeile `geschlossen` oder `gespeichert` öffnet Datum, Belichtung, ISO, Lights, Darks und Wetter. `MONITOR` zeigt das vorhandene JPEG. `ZURÜCK` geht zur Liste und schließt nichts. Eine offene Zeile geht weiter auf die Kameratafel.

Die Kameratafel bleibt in der bestätigten Größe. Weitere Knöpfe kommen auf eigene Seiten derselben Tafel, so wie die Einstellungen schon Seiten haben. Das Vorschaubild bleibt auf dem eigenen Monitor.

## Warum der Monitor-Knopf fehlte

`MONITOR` liegt auf der Kameratafel, Mitte, zwischen der Kopfzeile und `LIGHTS` / `DARKS`. Die Fläche ist 0,28 m breit und 0,036 m hoch. Unten überdeckt sie `LIGHTS` und `DARKS` um etwa 9 mm und jeweils die innere Hälfte dieser beiden Knöpfe. Ein Strahl trifft dort zuerst die Aufnahmetasten.

Während einer Aufnahme ist der Knopf ausgeblendet. Nach `ZURÜCK` verlässt die Quest die Kameratafel, der Knopf ist mit weg. Das JPEG im Sessionordner entsteht trotzdem. Eine größere Tafel würde diese eine Zeile freimachen und die bereits geprüften Treffer von `LIGHTS`, `DARKS`, `ZURÜCK` und `SCHLIESSEN` verschieben. Für Belichtung, ISO, Vorschau und Histogramm einer alten Session reicht eine Zeile zusätzlich nicht.

## Desktop, zum Vergleich

Eine Session im Desktop, offen oder geschlossen, zeigt Datum, Kennung, Lights und Darks, Belichtungszeit, Integrationszeit, Archiv, Status und Wetter. Daneben liegt das JPEG der neuesten Light-Datei. Capture ist bei einer geschlossenen Session gesperrt. Bearbeiten, Timing, erneuter Wetterexport, Work, Archiv und Entfernen bleiben Aktionen des Desktops.

Die Quest zeigt in der Sessionliste nur offene Sessions und die gerade gespeicherte Zeile. Ein Klick auf `gespeichert` öffnet keine Ansicht und keine Aufnahme.

## Gliederung

Drei Seiten, derselbe Rahmen, dieselben Knöpfe `ZIEHEN`, `SCHLIESSEN` und `ZURÜCK`.

| Seite | Inhalt | Knöpfe |
| --- | --- | --- |
| Sessions | offene und geschlossene Sessions des Objekts | eine Zeile pro Session, `＋ NEUE SESSION` |
| Sessionansicht | Datum, Belichtung, ISO, Lights, Darks, Wetter | `MONITOR`, und nur bei offener Session `AUFNAHME` |
| Kameratafel | unverändert: ISO, Belichtung, Bildzahl, Lights, Darks | ohne `MONITOR` |

Eine geschlossene Zeile öffnet die Sessionansicht nur zum Lesen. Sie startet keine Aufnahme und ändert die Session nicht. Eine offene Zeile öffnet dieselbe Ansicht. `AUFNAHME` führt von dort auf die bestehende Kameratafel.

`MONITOR` auf der Sessionansicht blendet die eigene Monitorfläche ein. Sie liest das JPEG und die Statistik, die zu dieser Session schon liegen. Eine fehlende Datei bleibt eine leere Anzeige. Es wird kein Aufnahmeauftrag gestartet und keine RAW-Datei neu ausgemessen, solange die Statistik schon geschrieben ist. `AUS` und `ZIEHEN` bleiben am Monitor.

Nicht auf die Quest: Bearbeiten, Timing, Work, Archiv, Entfernen, erneuter Wetterexport. Keine neue Spalte in der Session-Datenbank. Die Montierung bleibt unberührt.
