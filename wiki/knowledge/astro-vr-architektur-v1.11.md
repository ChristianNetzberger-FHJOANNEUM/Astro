# Astro-VR Architektur v1.11 — XR-10c Stufe B2

> Quelle: Totmann in [v1.10](astro-vr-architektur-v1.10.md). Fortschreibung: [v1.12](astro-vr-architektur-v1.12.md)
> Stand: **Abgenommen am 2026-10-13.** Feldtest des beschriebenen Umfangs.

XR-10b ist abgenommen. Der Desktop-Stopp vom 2026-10-13 hat mehrmals innerhalb weniger Sekunden gehalten. Diese Seite beschreibt die Quest-Bedienung. Sie löst keine Montierungsbewegung aus.

Telrad, Panorama, Tagesbahn, Katalogsuche, GoTo-Einheiten, der feste Kopplungscode, Parken und Hibernate bleiben unverändert.

## Controller

Die bisherige Belegung liest keinen Joystick. Dashboard und Auswahl bleiben `select` (Abzug), die optionale Zielhilfe bleibt `squeeze` (Griff), Ziehen bleibt `selectstart`/`selectend`. Der rechte Stick ist frei.

Die Achse nimmt nur die rechte Hand. `gamepad.mapping` muss `xr-standard` sein. Der Stick der Quest liegt auf `axes[2]` und `axes[3]`. `axes[0]` und `axes[1]` sind das Touchpad und bleiben auf diesem Controller 0. Rechts ist RA Ost, links RA West, oben Dec Nord, unten Dec Süd. Die stärkere Achse gewinnt. Profile `oculus-touch`, `meta-quest-touch-plus`, `generic-thumbstick` oder `generic-trigger` werden erkannt. Eine andere Mapping-Zeichenkette wird nicht geraten. Liegt der Stick innerhalb von 0,2, gilt das als Mitte.

Solange der Modus aus ist, zeigt die Montierungstafel nur diese Lesung. Es geht kein Bewegungsbefehl hinaus.

## Bedienung

Im Montierungsblatt steht **MANUELLE ACHSE**, standardmäßig aus. Einschalten braucht die bestehende Kopplung und einen freien Zustand. Danach muss der Stick zuerst in der Mitte stehen. Erst eine Auslenkung danach sendet Bewegung. Die Stufe beginnt bei 0,01 Grad pro Sekunde. Plus und Minus wählen 0,005, 0,01, 0,02, 0,05, 0,1 oder 0,5. Eine freie Zahl oder die Handsteuerungsstufe 9 wird abgelehnt. Plus allein fährt nicht.

Die Tafel unterscheidet AUS, BEREIT, BEWEGT, STOPPT, GESPERRT und FEHLER. **STOP** bleibt der GoTo-Abbruch über `slew/stop`. **STOP ACHSE** sendet `move/stop`. Die beiden Knöpfe liegen getrennt.

Neben der Geschwindigkeit steht die Lage-Abfrage. Minus verkürzt sie von 1 s auf 0,5 s und 0,25 s, Plus setzt sie wieder herauf. Der Anfang bleibt 1 s. Sie ändert den Totmann nicht. NINA liefert Azimut und Höhe etwa alle 2 s unverändert weiter. Eine kürzere Abfrage macht den gelben Telrad deshalb nicht feiner und verkürzt den Stopp nur um den Rest bis zur nächsten NINA-Meldung.

Solange der Stick ausgelenkt bleibt, wiederholen sich die Impulse. Ein von der Achse selbst gemeldetes Slewing ist kein GoTo und löst keinen Stopp aus. Loslassen, Verlassen des Blattes, Verlust des rechten Controllers, Ende der XR-Sitzung und ein Verbindungsfehler fordern sofort Rate 0 an. Danach sendet die Quest keine weiteren Impulse dieser Aktivierung. Ein neuer Impuls wartet auf die Mitte und auf den Zustand bereit. Ein Timeout allein setzt nicht bereit.

## Server

Die Quest öffnet keine NINA-WebSocket. Sie nutzt `POST /nina/mount/move` und `POST /nina/mount/move/stop`, mit derselben Sitzung und demselben CSRF-Kopf wie GoTo. Port 8443 gibt nur diese beiden zusätzlichen Pfade frei, keine pauschale `/nina`-Freigabe. Port 8082 prüft dieselbe Berechtigung.

Jeder Quest-Impuls trägt die Nummer seiner Aktivierung. Stopp und Totmann setzen diese Nummer außer Kraft. Ein späterer oder verzögerter Impuls derselben Nummer setzt keine Richtung und verlängert den Totmann nicht. Eine neuere Nummer nach bestätigtem bereiten Zustand darf wieder anfangen. Ein älterer Stopp beendet eine neuere Aktivierung nicht. Das Desktop-Pad sendet keine Nummer und bleibt der bisherige Weg.

Der Totmann bleibt 0,4 Sekunden Wiederholung und 1,5 Sekunden bis Rate 0. Es gibt keine Befehlswarteschlange: ein Impuls unterwegs, der nächste erst nach der Antwort. PHD2 verbunden und nicht führend sperrt nicht. Führung, Kalibrierung und ein nicht lesbarer PHD2-Zustand sperren. Beginnt die Führung während der Achse, sendet der Server Rate 0. GoTo und Achse schließen einander aus. Ein Achsen-Stopp ruft `slew/stop` nicht auf.

## Abnahme

Abgenommen am 2026-10-13 für den getesteten Umfang.

| Feldprüfung | Ergebnis |
| --- | --- |
| Gehaltene Joystick-Fahrt einschließlich Richtungswechsel | Bestanden |
| STOP ACHSE an der realen Montierung | Bestanden |
| Unterbrechung der Quest und anschließende Wiederaufnahme des Betriebs | Bestanden |

Rate 0 ist gesendet, wenn der Stick losgelassen wird, STOP ACHSE kommt oder die Quest abreißt. Die Montierung hält in endlicher Zeit. Das ist kein sofortiger Stillstand.

Ein Abbruch von NINA blendet den gelben Telrad aus und holt ihn nach der nächsten Lage zurück. Die Zeile „GoTo läuft“ und „Achse GESPERRT“ bleibt danach nicht stehen, sobald die Montierung wieder bereit ist. Die Sprünge des gelben Telrads folgen der NINA-Meldung, etwa alle 2 s. Name, Tour, Parken und Hibernate gehören nicht zu dieser Abnahme. Der nächste Schritt ist die Abnahme von [v1.12](astro-vr-architektur-v1.12.md), nicht ein neues Funktionskapitel.

## Verwandte Seiten

- [Astro-VR Architektur v1.10](astro-vr-architektur-v1.10.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
