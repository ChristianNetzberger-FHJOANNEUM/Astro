# Astro-VR Architektur v1.2 — XR-8e persönliche NGC-Auswahl

> Quelle: freigegebener Zuschnitt nach [v1.1](astro-vr-architektur-v1.1.md)
> Stand: **Auf der Quest bestätigt** am 2026-10-11: NGC-Filter, Typen, Unruhe, Zeitsprung +1 h, Tafel lesbar. Mindesthöhe ist nicht gebaut. Fortschreibung: [v1.3](astro-vr-architektur-v1.3.md).

`sky.sqlite` und `favorites.json` bleiben unverändert. XR-8f (grüner Ziel-Telrad, Richtungspfeil, Winkelabstand) und XR-8g (Katalogsuche auf der Quest) sind nicht Teil dieses Schritts. NINA, SynScan, GoTo und Aufnahme bleiben unberührt. Eine Vorauswahl nach Mindesthöhe, etwa 25° über dem Horizont, ist nicht eingebaut.

## Daten

Neue Datei `data/horizon/object-picks.json`, Schema 1. Der Schlüssel ist nur der kanonische `dso.key`. Ein als NGC 224 gesuchtes Objekt wird als `M31` gespeichert und nicht zusätzlich unter der NGC-Nummer.

```json
{
  "schema": 1,
  "objects": {
    "NGC7000": { "rating": 5, "quest": true, "note": "" }
  }
}
```

Rating ist 1–5 oder fehlt. `quest` ist eine eigene Freigabe. In MEINE AUSWAHL erscheint ein Objekt nur mit `quest=true` und Rating mindestens der gewählten Schwelle. Eine fehlende Datei ist eine leere Auswahl und wird nicht angelegt. Eine beschädigte Datei wird protokolliert, der Himmel bleibt leer für NGC MEINE, und sie wird nicht überschrieben. Ein Speichern liefert dann den Fehler, bis die Datei von Hand repariert ist.

Schreiben prüft den Katalogschlüssel und die Werte. Rating außerhalb 1–5, ein Wahrheitswert als Rating und eine Notiz über 240 Zeichen werden abgelehnt. Die Datei wird über eine temporäre Datei ersetzt.

Die Verwaltung liegt im Objektinfo der Desktop-Suche auf Port 8082: Name, kanonischer Schlüssel, Bewertung, Quest-Freigabe, Notiz. `GET /catalog/picks` und `PUT /catalog/picks` gibt es nur dort. Port 8443 bleibt ohne diese Pfade.

## Overlay

`GET /sky-overlay` versteht zusätzlich `ngc_mode=off|mine|all` und `ngc_min=1..5`.

| Modus | Bedeutung |
|---|---|
| `off` | Keine NGC-Objekte. Standard. Entspricht dem bisherigen `ngc=0`. |
| `mine` | Nur freigegebene Objekte mit Rating ab `ngc_min`. Keine Magnitudengrenze. Horizont und Maske bleiben. |
| `all` | Bisherige NGC/IC-Helligkeit `mag <= max(Grenze+3, 9)`. Nicht der ganze DSO-Katalog. |

Fehlt `ngc_mode`, gilt weiter der alte Schalter: `ngc=1` ist `all`, `ngc=0` ist `off`. Ist `ngc_mode` gesetzt, gewinnt er. Die Quest sendet `ngc=0` und dazu den Modus.

Messier bleibt ein eigener Schalter. Ein Objekt mit Schlüssel `M…` kommt nur aus dem Messier-Zweig, auch wenn der Katalog NGC oder IC lautet.

Die 2.133 Objekte aus der Bestandsanalyse sind die Kandidaten vor dem Horizont bei Grenzhelligkeit 5,5. Das ist keine Obergrenze. Gemessen am 2026-10-11, 20:00 UTC, Standort 48,25475° N, 14,36614° E, Grenzhelligkeit 5,5, Messier an:

| Lage | NGC über dem Horizont | Overlay |
|---|---|---|
| flacher Horizont | 891 | 302 kB, davon 55 Messier |
| Gartenmaske `CAM_20260927182811_0941_D` | 642 | 222 kB |

MEINE mit einem freigegebenen Objekt (`NGC7000`) und dem Messier-Schlüssel `M31` lieferte genau ein NGC-Objekt. `M31` blieb eine Messier-Zeile. Es gibt keine zweite Datenbankabfrage pro Objekt.

## Quest

Im Himmel-Panel: `NGC AUS`, `NGC MEINE`, `NGC ALLE`. Die Mindestbewertung `≥ 1` bis `≥ 5` erscheint nur bei MEINE. Standard ist AUS und Schwelle 1. Die Tafel ist 0,44 m hoch. Der Zusatz liegt unten. `ZURÜCK` sitzt unter der Bewertung, mit Abstand.

SCHEIBE/TYPEN, die Farben und Unruhe gelten für Messier und NGC gemeinsam. Unruhe bleibt standardmäßig aus. Es gibt keinen Timer pro Objekt. Die Punktwolke bekommt eine gemeinsame Zeit. Schilder gibt es bei MEINE dauerhaft, bei ALLE nicht. Der Name erscheint dort erst am Telrad und im Detail. Die Sechserliste unter OBJEKTE bleibt Gestirne und benannte Sterne.

Ein Schalterwechsel erhöht die Abrufnummer. Eine ältere Antwort, auch mit anderem Modus oder anderer Schwelle, ersetzt den Himmel nicht. Nicht mehr gebrauchte Punkte und Schilder werden freigegeben.

## Quest-Abnahme

1. NGC startet AUS.
2. Der Desktop speichert Rating und Freigabe auf Port 8082.
3. Die Datei bleibt nach einem Neustart der App erhalten.
4. MEINE AUSWAHL zeigt nur freigegebene und ausreichend bewertete Objekte.
5. Ein schwaches freigegebenes Objekt bleibt trotz der bisherigen Magnitudengrenze sichtbar, wenn es über dem Horizont steht.
6. NGC-Objekte lassen sich mit dem Telrad auswählen.
7. Messier und NGC erscheinen nicht doppelt. NGC 224 liegt als `M31` nur bei Messier.
8. Messier bleibt unabhängig vom NGC-Modus.
9. SCHEIBE und TYPEN gelten auch für NGC.
10. Unruhe AUS und EIN funktionieren auch bei NGC ALLE.
11. NGC ALLE bleibt auf der Quest flüssig. Erwartete Menge mit der Gartenmaske: etwa 642 Punkte, ohne Dauerschilder.
12. Die Sechserliste und die Controllerbedienung bleiben.
13. Eine fehlende oder beschädigte `object-picks.json` beendet weder die App noch das Overlay. MEINE bleibt dann leer.

Vor dem Test die App neu starten und die Quest-Seite neu öffnen. `vr.html` wird beim Prozessstart gelesen.

## Verwandte Seiten

- [Astro-VR Architektur v1.1](astro-vr-architektur-v1.1.md)
- [Astro-VR Architektur v1.3](astro-vr-architektur-v1.3.md) — XR-8f Zielführung
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
