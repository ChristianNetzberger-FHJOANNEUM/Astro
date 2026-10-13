# Astro-VR Architektur v1.11 — XR-10c Stufe B2

> Quelle: Totmann in [v1.10](astro-vr-architektur-v1.10.md)
> Stand: **Implementiert am 2026-10-13, nicht abgenommen.** Die Quest-Feldabnahme bleibt offen.

XR-10b ist abgenommen. Der Desktop-Stopp vom 2026-10-13 hat mehrmals innerhalb weniger Sekunden gehalten. Diese Seite beschreibt die Quest-Bedienung. Sie löst keine Montierungsbewegung aus.

Telrad, Panorama, Tagesbahn, Katalogsuche, GoTo-Einheiten, der feste Kopplungscode, Parken und Hibernate bleiben unverändert.

## Controller

Die bisherige Belegung liest keinen Joystick. Dashboard und Auswahl bleiben `select` (Abzug), die optionale Zielhilfe bleibt `squeeze` (Griff), Ziehen bleibt `selectstart`/`selectend`. Der rechte Stick ist frei.

Die Achse nimmt nur die rechte Hand. `gamepad.mapping` muss `xr-standard` sein. Der Stick der Quest liegt auf `axes[2]` und `axes[3]`. `axes[0]` und `axes[1]` sind das Touchpad und bleiben auf diesem Controller 0. Rechts ist RA Ost, links RA West, oben Dec Nord, unten Dec Süd. Die stärkere Achse gewinnt. Profile `oculus-touch`, `meta-quest-touch-plus`, `generic-thumbstick` oder `generic-trigger` werden erkannt. Eine andere Mapping-Zeichenkette wird nicht geraten. Liegt der Stick innerhalb von 0,2, gilt das als Mitte.

Solange der Modus aus ist, zeigt die Montierungstafel nur diese Lesung. Es geht kein Bewegungsbefehl hinaus.

## Bedienung

Im Montierungsblatt steht **MANUELLE ACHSE**, standardmäßig aus. Einschalten braucht die bestehende Kopplung und einen freien Zustand. Danach muss der Stick zuerst in der Mitte stehen. Erst eine Auslenkung danach sendet Bewegung. Die Stufe beginnt bei 0,01 Grad pro Sekunde. Plus und Minus wählen 0,005, 0,01, 0,02, 0,05, 0,1 oder 0,5. Eine freie Zahl oder die Handsteuerungsstufe 9 wird abgelehnt. Plus allein fährt nicht.

Die Tafel unterscheidet AUS, BEREIT, BEWEGT, STOPPT, GESPERRT und FEHLER. **STOP** bleibt der GoTo-Abbruch über `slew/stop`. **STOP ACHSE** sendet `move/stop`. Die beiden Knöpfe liegen getrennt.

Solange der Stick ausgelenkt bleibt, wiederholen sich die Impulse. Ein von der Achse selbst gemeldetes Slewing ist kein GoTo und löst keinen Stopp aus. Loslassen, Verlassen des Blattes, Verlust des rechten Controllers, Ende der XR-Sitzung und ein Verbindungsfehler fordern sofort Rate 0 an. Danach sendet die Quest keine weiteren Impulse dieser Aktivierung. Ein neuer Impuls wartet auf die Mitte und auf den Zustand bereit. Ein Timeout allein setzt nicht bereit.

## Server

Die Quest öffnet keine NINA-WebSocket. Sie nutzt `POST /nina/mount/move` und `POST /nina/mount/move/stop`, mit derselben Sitzung und demselben CSRF-Kopf wie GoTo. Port 8443 gibt nur diese beiden zusätzlichen Pfade frei, keine pauschale `/nina`-Freigabe. Port 8082 prüft dieselbe Berechtigung.

Jeder Quest-Impuls trägt die Nummer seiner Aktivierung. Stopp und Totmann setzen diese Nummer außer Kraft. Ein späterer oder verzögerter Impuls derselben Nummer setzt keine Richtung und verlängert den Totmann nicht. Eine neuere Nummer nach bestätigtem bereiten Zustand darf wieder anfangen. Ein älterer Stopp beendet eine neuere Aktivierung nicht. Das Desktop-Pad sendet keine Nummer und bleibt der bisherige Weg.

Der Totmann bleibt 0,4 Sekunden Wiederholung und 1,5 Sekunden bis Rate 0. Es gibt keine Befehlswarteschlange: ein Impuls unterwegs, der nächste erst nach der Antwort. PHD2 verbunden und nicht führend sperrt nicht. Führung, Kalibrierung und ein nicht lesbarer PHD2-Zustand sperren. Beginnt die Führung während der Achse, sendet der Server Rate 0. GoTo und Achse schließen einander aus. Ein Achsen-Stopp ruft `slew/stop` nicht auf.

## Feldtest, noch offen

Zuerst die Joysticklesung bei ausgeschaltetem Modus, ohne Auslenkung in den Modus. Danach eine langsame Fahrt nur von Hand: Loslassen, Verbindungsverlust und STOP ACHSE müssen an der Montierung nachvollziehbar sein. Erst dann kann XR-10c abgenommen werden.

## Verwandte Seiten

- [Astro-VR Architektur v1.10](astro-vr-architektur-v1.10.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
