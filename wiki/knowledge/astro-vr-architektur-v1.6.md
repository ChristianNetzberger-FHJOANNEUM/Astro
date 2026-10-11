# Astro-VR Architektur v1.6 — XR-9a Tagesbahn

> Quelle: abgenommene Katalogsuche in [v1.5](astro-vr-architektur-v1.5.md)
> Stand: **Implementiert, Quest-Abnahme offen.** `app_mele/vr.html` und `GET /sky-track` auf Port 8443. Keine neue Python-Route, keine Chart-Bibliothek, kein GoTo.

XR-8g.2 bleibt. Suche, Telrade, Pfeil, Winkel, Messier, NGC, TYPEN, Unruhe, LIVE und die Tafelgröße sind unverändert. NINA, SynScan, GoTo und Aufnahme bleiben unberührt. Eine Mindesthöhe von 25° ist nicht eingebaut.

## Bedienung

In der Detailansicht steht `TAGESBAHN` neben `ZIEL FINDEN`, sobald das Objekt RA und Dec hat. Die Ansicht liegt auf derselben Tafel. `ZURÜCK` führt zum Detail. Der grüne Telrad, der rote Telrad und aimToggle bleiben.

Am Himmel liegt die Bahn der ganzen Beobachtungsnacht, von lokalem Mittag bis zum nächsten Mittag. Die Farben sind dieselben wie im Desktop: Nacht türkis und durchgezogen, Dämmerung gelb und gestrichelt, Tag orange und gepunktet. Liegt ein Abschnitt unter dem Horizont, bleibt er dort und wird blasser. Eine weiße Kugel markiert den Bahnpunkt der eingestellten Zeit. Volle Stunden tragen eine Marke und die lokale Uhrzeit, wie die Stundenoption im Desktop. Die Bahn bleibt stehen, wenn die Tafel geschlossen, verschoben oder zur Liste zurückgekehrt wird, und auch bei LIVE und +1 h. Ein anderes Objekt löscht sie. Die Farbe eines Abschnitts kommt von seinem eigenen Punkt, nicht vom Anschluss an den Nachbarabschnitt. Stundenmarken liegen auf der Bahn. Eine Marke mit Höhe bis 0° wird nicht gezeichnet.

Oben auf der Tafel liegt der Streifen `ZIEHEN`. Die Revolvertaste hält ihn am Strahl fest und lässt die Tafel beim Loslassen dort stehen. Loslassen daneben schließt die Tafel wie bisher.

## Kurve und Fenster

Die Kurve auf der Tafel zeigt die nächsten 12 Stunden ab der Himmelszeit. LIVE benutzt den Zeitpunkt der letzten Himmelsantwort, eine feste Zeit den eingestellten Zeitpunkt. Die Nulllinie ist der geometrische Horizont. Mit geladener Gartenmaske entscheidet `above` je Azimut. Ohne Maske steht dort Horizont 0°.

Die höchste Höhe in diesem Abschnitt wird genannt. Kulmination heißt sie nur, wenn sie im Inneren des Abschnitts liegt. Nachtfenster kommen aus `summary.observable_windows`: Nacht und über dem Horizont. Liegt das Objekt im Abschnitt durchgehend darunter, bleibt die Kurve und der Hinweis sagt das.

Ein Abruf gilt für Objekt, Standort, Maske und diese Nacht. +1 h verschiebt die Marke auf den vorhandenen Punkten. Neu geladen wird, wenn die nächsten 12 Stunden aus der gelieferten Nacht hinauslaufen. Eine ältere Antwort überschreibt keine neuere.

Planeten und Mond nutzen die RA/Dec des Detailzeitpunkts, keine neue Ephemeride.

## Schnittstelle

`GET /sky-track?ra=&dec=&lat=&lon=&when=&stem=&tz_offset_min=`

Ohne `when` ist es die aktuelle UTC-Zeit. `stem` lädt die Gartenmaske. Die Antwort hat `points` mit `when`, `az`, `alt`, `above`, `light`, dazu `summary.above_windows` und `summary.observable_windows`. Der Almanach bleibt geschlossen.

Auf Port 8443 ist nur dieser GET-Pfad ergänzt:

```
@sky_track {
    method GET
    path /sky-track
}
handle @sky_track {
    reverse_proxy 127.0.0.1:8082
}
```

## Quest-Abnahme

Die Phase ist erst nach diesem Lauf abgeschlossen. Vorher die App neu starten und die Quest-Seite neu öffnen.

1. M13 suchen und das Detail öffnen.
2. TAGESBAHN öffnen.
3. Die Bahn am Himmel prüfen: Nacht türkis, unter dem Horizont blasser.
4. Die Höhenkurve, die Zeitachse und die Höhenachse lesen.
5. Maximale Höhe und Kulmination prüfen.
6. Das Nachtfenster prüfen.
7. ZURÜCK führt zum Detail, die Bahn am Himmel bleibt.
8. ZIEL FINDEN setzt den grünen Telrad.
9. LIVE und +1 h: die weiße Marke wandert auf der Bahn.
10. Ein Objekt unter dem Horizont: die Bahn wird nicht über den Horizont gehoben.
11. Katalogsuche und Telrade bleiben benutzbar.
12. Es werden keine Gerätebefehle ausgelöst.

## Verwandte Seiten

- [Astro-VR Architektur v1.5](astro-vr-architektur-v1.5.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
