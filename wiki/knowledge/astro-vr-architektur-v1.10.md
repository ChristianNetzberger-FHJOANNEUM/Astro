# Astro-VR Architektur v1.10 — XR-10c Stufe A

> Quelle: abgenommenes Quest-GoTo in [v1.9](astro-vr-architektur-v1.9.md)
> Stand: **Desktop-Stopp am 2026-10-13: die Achse hielt mehrmals innerhalb weniger Sekunden.** Stufe B1 ist nicht als Ganzes abgenommen. Fortschreibung: [v1.11](astro-vr-architektur-v1.11.md).

XR-10b ist am 2026-10-13 abgenommen. Diese Seite klärt nur den Totmann. Es gibt keine Quest-Bedienung, keine neue Caddy-Route und keine Fahrt an der Montierung.

Eine manuelle Achsbewegung darf nicht davon abhängen, dass der Browser noch einen STOP sendet. Ein laufendes GoTo läuft nach dem Verlust der Quest weiter. Telrad, Tagesbahn, Katalogsuche und der feste Kopplungscode bleiben.

## Vorhandener Weg

Das Desktop-Pad sendet `POST /nina/mount/move` mit Richtung `east`, `west`, `north` oder `south` und einer Rate in Grad pro Sekunde. Die App hält danach eine WebSocket-Verbindung zu NINA, `ws://127.0.0.1:1888/v2/mount`, und sendet `{"direction","rate"}`. Das ist ASCOM `MoveAxis`. `POST /nina/mount/move/stop` sendet für alle vier Richtungen die Rate 0. Port 8443 gibt diese beiden Pfade nicht frei. Dieselbe Sitzung wie bei GoTo gilt schon auf Port 8082.

Der Mover in `mele/nina_mount_move.py` wiederholt die letzte Richtung alle 0,4 Sekunden, solange der letzte Auftrag höchstens 1,5 Sekunden alt ist. Danach ruft er selbst `stop` auf. Dieser Timer läuft im MeLE-Prozess. Er braucht keinen STOP aus dem Browser. Das ist der vorhandene Totmann.

## NINA 2.2.15.2

Installiert ist Advanced API 2.2.15.2. Seit Version 2.2.0.0 stoppt das Schließen der WebSocket die Achse nicht mehr. Das wurde entfernt, weil der Stopp PHD2 gestört hat. Die verbleibende Sicherung des Plugins ist eine Verzögerung von etwa 2 Sekunden ohne neue Nachricht.

Daraus folgt: ein Abbruch der Verbindung zu NINA ist kein Stopp. Der MeLE muss die Rate 0 senden, solange die WebSocket noch offen ist. Stirbt der MeLE-Prozess vorher, sendet niemand diese Rate. Das ist das Restrisiko dieser Plugin-Version. Ein zusätzlicher Wächter außerhalb der App ist nicht Teil von Stufe A.

Die Zeit bis zum Stillstand ist nicht an der Montierung gemessen. Nach dem letzten gültigen Impuls vergehen höchstens 1,5 Sekunden, bis der MeLE die Rate 0 schickt. Der Versand selbst geht über localhost. Wie schnell der SynScan-App-Treiber die Achse danach anhält, ist offen.

`stop` meldet heute Erfolg, auch wenn der Versand fehlschlägt. Stufe B muss einen fehlgeschlagenen Rate-0-Versand als unklar behandeln und ihn wiederholen, nicht als Stillstand.

## Guiding

Das Pad lehnt eine Achsbewegung ab, während PHD2 führt oder kalibriert, und auch bei geparkter Montierung. GoTo lehnt zusätzlich einen nicht lesbaren PHD2-Zustand ab. Das Pad tut das nicht.

`MoveAxis` und das Pulse-Guiding von PHD2 benutzen dieselbe Montierung. Der Plugin-Autor hat den Stopp beim Verbindungsende gerade deshalb entfernt. Eine manuelle Achse während des Guidings kann die Führung stören.

Stufe B übernimmt die Ablehnung bei Führung, Kalibrierung und Parken. Ein nicht lesbarer PHD2-Zustand lehnt den Impuls ab, wie beim GoTo. Wird die Führung erst während einer laufenden Achse erkannt, stoppt der Server mit Rate 0.

## Grenze zum GoTo

Der Totmann darf nur die manuelle Achse beenden. Er ruft nicht `slew/stop` auf. Ein GoTo bleibt von einem verlorenen Quest-Impuls unberührt. Der Timer sendet Rate 0 nur, solange die laufende Bewegung eine Achsbewegung ist.

## Stufe B1

Vor jedem Impuls sperren ein nicht erreichbares oder unklares PHD2, Führung, Kalibrierung, Pause und ein verlorener Leitstern. Beginnt die Führung während der Achse, sendet der MeLE Rate 0. Ein neuer Impuls in demselben Augenblick tut dasselbe.

`stop` meldet Erfolg nur, wenn Rate 0 angekommen ist. Die Antwort trägt `sent` und `settled: false`. Stillstand ist damit nicht bestätigt. Schlägt der Versand fehl, bleibt der Zustand unklar mit „Rate 0 nicht gesendet“. Eine frische Leermeldung setzt ihn nicht auf bereit. Der nächste Stopp ist sofort möglich, der Totmann wiederholt frühestens nach 0,4 Sekunden.

Der Totmann-Schritt `tick` läuft im eigenen Thread und sendet Rate 0 auch, während ein Impuls noch auf dem Transport hängt. Ein Achsen-Stopp bei laufendem GoTo sendet keine Rate 0 und ruft nicht `slew/stop` auf.

Fällt der MeLE-Prozess aus, kann er keine Rate 0 mehr senden. Advanced API 2.2.15.2 stoppt beim Schließen der WebSocket nicht. Die Plugin-Frist von etwa 2 Sekunden ist nur eine zusätzliche Schicht und wurde nicht an der Montierung gemessen.

## Realer Test

Am 2026-10-13, am Desktop im Guiding-Fenster, bei Tageslicht. PHD2 lieferte Kamerabilder und führte nicht. Die Montierung stoppte mehrmals innerhalb weniger Sekunden. Dieselbe endliche Zeit gilt auch für den Handcontroller. Eine Stoppuhr-Zeit liegt nicht vor. Der WebSocket-Abriss und ein Prozessende wurden nicht geprüft.

## Stufe B2

Die Quest-Bedienung steht in [v1.11](astro-vr-architektur-v1.11.md). Sie ist implementiert und nicht abgenommen. Parken und Hibernate bleiben draußen.

## Verwandte Seiten

- [Astro-VR Architektur v1.9](astro-vr-architektur-v1.9.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
