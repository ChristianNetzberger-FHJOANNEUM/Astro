# Astro-VR Architektur v1.0 — XR-8c Navigation

> Quelle: freigegebenes [Panelkonzept v0.1](astro-vr-panelkonzept-v0.1.md), nach der Abnahme von [v0.9](astro-vr-architektur-v0.9.md)
> Stand: **Auf der Quest abgenommen am 2026-10-11.** Fortschreibung: [v1.1](astro-vr-architektur-v1.1.md).

Ein Dashboard, eine Gruppe. Größe 0,68 m × 0,38 m und Abstand 1,75 m bleiben. Strahl, Telrad, `select`, `squeeze` und die 400 ms bleiben. Keine neue Route.

## Übersicht

Drei Flächen, keine Platzhalter:

| Fläche | Untertitel | Öffnet |
|---|---|---|
| OBJEKTE | Liste und Details | die bisherige Liste, höchstens sechs Zeilen |
| HIMMEL | Anzeige und Zeit | nur die Überschrift und `ZURÜCK` |
| EINSTELLUNGEN | VR-Preferences | das Panel aus v0.9 |

BEOBACHTUNG, MONTIERUNG und AUFNAHME sind im Konzept reserviert und auf der Quest nicht sichtbar.

Oben auf der Übersicht steht die Uhr und die Sternzahl, dazu der Overlay-Fehler, falls einer da ist. Die vier alten Statusblöcke sind dieser einen Zeile gewichen, weil die Flächen den Rest decken.

## Stufen

`ZURÜCK` geht eine Stufe. Von der Liste, vom Himmel und von einem Telrad-Detail, das auf der Übersicht oder bei geschlossenem Panel entstand, zur Übersicht. Vom Detail einer Liste zurück in die Liste. Vom Detail, das über einer offenen Gruppe entstand, zurück in diese Gruppe. `FERTIG` in den Einstellungen geht zur Übersicht, nicht durch die vier Reiter.

Ausblenden vergisst die Gruppe. Einblenden mit dem Abzug zeigt die Übersicht.

Ausnahme: Das Telrad bei geschlossenem Panel stellt das Dashboard vor den Blick und öffnet das Detail dieses Objekts. `ZURÜCK` daraus geht zur Übersicht. Ein Abzug daneben schließt. Der nächste Abzug ohne Treffer zeigt wieder die Übersicht.

Die Liste, die Kennung, die 15-Sekunden-Aktualisierung im offenen Detail und die Hysterese sind unverändert. In dieser Fassung zeigt HIMMEL nur den Hinweis. Die Schalter stehen in [v1.1](astro-vr-architektur-v1.1.md).

## Abnahme

1. Das Dashboard öffnet mit der Übersicht und den drei Flächen.
2. Die drei Flächen sind zuverlässig treffbar.
3. OBJEKTE zeigt Liste und Detail wie bisher. Azimut und Höhe laufen im offenen Detail weiter.
4. EINSTELLUNGEN speichert, setzt Standardwerte und belegt die Tasten wie bisher.
5. HIMMEL zeigt nur den Hinweis und `ZURÜCK`.
6. Ausblenden und Einblenden beginnt bei der Übersicht.
7. Telrad bei geschlossenem Panel öffnet das Detail. `ZURÜCK` führt zur Übersicht.
8. Telrad bei offenem Himmel oder offener Liste kehrt mit `ZURÜCK` dorthin zurück.
9. Panorama, Sterne und Planeten sehen aus wie zuvor.

## Verwandte Seiten

- [Astro-VR Architektur v1.1](astro-vr-architektur-v1.1.md) — XR-8d Himmel
- [Astro-VR Panelkonzept v0.1](astro-vr-panelkonzept-v0.1.md)
- [Astro-VR Architektur v0.9](astro-vr-architektur-v0.9.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
