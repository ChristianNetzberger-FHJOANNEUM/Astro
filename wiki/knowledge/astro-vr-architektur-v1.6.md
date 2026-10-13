# Astro-VR Architektur v1.6 — XR-9a Tagesbahn

> Quelle: abgenommene Katalogsuche in [v1.5](astro-vr-architektur-v1.5.md)
> Stand: **Auf der Quest bestätigt** am 2026-10-12. `app_mele/vr.html` und `GET /sky-track` auf Port 8443. Keine neue Python-Route, keine Chart-Bibliothek, kein GoTo. Fortschreibung: [v1.7](astro-vr-architektur-v1.7.md).

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

Auf der Quest bestätigt am 2026-10-12.

Geprüft: Höhenkurve, Kulmination, Nachtfenster, Nacht türkis, Dämmerung gelb, Tag orange, blasse Fortsetzung unter dem Horizont, Stundenmarken auf der Bahn und keine Marke bei Höhe bis 0°, Bahn bleibt bei geschlossener oder verschobener Tafel und bei LIVE sowie +1 h. ZIEL FINDEN, Katalogsuche und Telrade blieben benutzbar. Es wurden keine Gerätebefehle ausgelöst.

Zusätzlich zur Spec und ebenfalls bestätigt: ZIEHEN, Himmels-Schalter lokal auf der Quest mit LIVE immer beim Start an, Panorama-Helligkeit Foto von 0 bis 100, Stern als hellblaue Scheibe mit Kreuz, Doppelstern als gelbe und rote Scheibe.

## Verwandte Seiten

- [Astro-VR Architektur v1.5](astro-vr-architektur-v1.5.md)
- [Astro-VR Architektur v1.7](astro-vr-architektur-v1.7.md) — XR-10a auf der Quest abgenommen
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
