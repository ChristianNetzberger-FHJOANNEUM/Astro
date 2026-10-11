# Astro-VR Architektur v0.5 — XR-7a lesendes Dashboard

> Quelle: Abnahme von [v0.4](astro-vr-architektur-v0.4.md) plus die Freigabe vom 2026-10-11
> Stand: **XR-7a und XR-7b auf der Quest abgenommen, 2026-10-11.** Der Zeigefingerabzug blendet das Panel aus. Nach einer Kopfdrehung steht es beim Einblenden wieder vor dem Blick. Größe und Abstand bleiben.

Das Panel ist eine eigene Gruppe in der Szene, kein Kind der Panoramakugel. Es liest nur Zustände, die die Seite schon hat. Keine neue Route, keine Gerätebefehle.

## Aufbau

Eine Gruppe `dashboard` hängt direkt in der Szene. Darin eine Ebene, 0,68 m mal 0,38 m, mit einer Canvas-Textur. Vier Felder: Zeit, Standort, Himmel, System. Unten der Hinweis `Nur Anzeige`.

Die Textur wird einmal angelegt. Ein neuer Anstrich setzt nur `needsUpdate`. Geometrie und Material bleiben. Beim Verlassen der Sitzung wird die Gruppe unsichtbar, nicht gelöscht. Der nächste Eintritt benutzt dieselben Objekte.

## Position

Referenzraum ist `local`. Im ersten Frame mit gültiger Headset-Pose liegt das Panel 1,75 m in Blickrichtung und 0,22 m darunter. `lookAt` dreht die Vorderseite zum Kopf. Danach bleibt die Gruppe stehen. Sie folgt der Kopfbewegung nicht. Die Desktop-Mausrichtung wird nicht benutzt.

## Aktualisierung

Ein Schlüssel aus Uhrzeit auf die Sekunde, Ort, Sternzahl, Sternbildzahl, Overlay-Zeit und Fehlertext. Nur wenn der Schlüssel sich ändert, wird die Textur neu gezeichnet. Das ist etwa einmal pro Sekunde wegen der Uhr, und zusätzlich nach jedem erfolgreichen oder fehlgeschlagenen Overlay. Der Renderloop baut die Textur nicht pro Frame neu. Ein Overlay-Fehler steht im Feld System. Sterne, Linien und Gestirne bleiben.

Himmel zeigt die Sternzahl und die Zahl der Sternbildnamen aus der letzten guten Antwort, plus den Zeitpunkt `when` dieser Antwort. Standort ist Breite und Länge, die die Seite schon für das Overlay benutzt. Live heißt, dass keine eigene Simulationszeit gesetzt wird.

## Quest-Test

Nach Neustart von `mele_app` die Seite neu öffnen und Enter VR drücken. Auf dem Desktop bleibt das Panel aus.

1. Der Sternenhimmel sieht aus wie zuvor.
2. Das Panel erscheint vor dem Blick, etwas unter der Mitte, und verdeckt nicht die ganze Sicht.
3. Nach einer Kopfdrehung bleibt es an derselben Stelle im Raum.
4. UTC-Zeit und Live stehen im Feld Zeit. Breite und Länge stimmen mit dem Standort überein.
5. Sternzahl und Sternbildzahl passen zur Statuszeile. Das Overlay-Datum rückt mit dem 15-Sekunden-Takt.
6. Die Schrift bleibt lesbar, auch wenn der Kopf geneigt wird.
7. Beim Beenden der Sitzung ist das Panel weg.

Größe, Abstand und die leichte Absenkung bleiben. XR-7a ist auf der Quest abgenommen.

## XR-7b

`vr.html` hatte keine Controller-Eingabe. Die Meta-Taste bleibt dem System. A, B, X und Y hängen an wechselnden Gamepad-Nummern und werden nicht benutzt. Der Griff (`squeeze`) bleibt frei.

Der Zeigefingerabzug ist das WebXR-Ereignis `select`, einmal pro Druck, ohne Tastennummer. Ein zweites Ereignis innerhalb von 400 ms wird verworfen.

Sichtbar: der Abzug blendet das Panel aus. Der Himmel läuft weiter, `dashboardPlaced` bleibt gesetzt, damit der nächste Frame es nicht sofort wieder hinlegt. Ausgeblendet: der Abzug ruft dieselbe Platzierung wie beim Sitzungsstart auf, mit der aktuellen Headset-Pose, demselben Abstand und derselben Größe. Danach steht das Panel wieder fest. Neu ausrichten heißt ausblenden, den Kopf drehen und wieder einblenden. Kein langer Druck, keine zweite Taste.

Eine neue Sitzung zeigt das Panel wieder vor dem ersten Blick. Das Sitzungsende nimmt den Listener ab und blendet das Panel aus.

Die Abzug-Regel für eine spätere Schaltfläche steht in [v0.6](astro-vr-architektur-v0.6.md). Strahlen und Gerätebefehle gibt es hier nicht.

### Quest-Test

1. Abzug am Controller: das Panel verschwindet, der Himmel ist frei.
2. Nochmal Abzug: das Panel steht vor dem aktuellen Blick.
3. Kopf deutlich drehen, ausblenden, wieder einblenden: das Panel folgt dieser neuen Richtung und bleibt dann stehen.
4. Ein einzelner Druck schaltet nur einmal.
5. Sterne, Sternbilder, Sonne, Mond und Planeten bleiben. Die Meta-Taste öffnet das System, nicht das Panel.

## Verwandte Seiten

- [Astro-VR Architektur v0.4](astro-vr-architektur-v0.4.md)
- [Astro-VR Architektur v0.6](astro-vr-architektur-v0.6.md) — XR-3 Strahl, noch kein Code
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
