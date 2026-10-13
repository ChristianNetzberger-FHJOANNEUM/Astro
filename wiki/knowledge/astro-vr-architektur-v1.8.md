# Astro-VR Architektur v1.8 — XR-10b GoTo-Sperre

> Quelle: abgenommene Montierungsanzeige in [v1.7](astro-vr-architektur-v1.7.md)
> Stand: **Bewegungstests am 2026-10-12 abgeschlossen, XR-10b nicht abgenommen.** Fortschreibung: [v1.9](astro-vr-architektur-v1.9.md).

Dies ist die serverseitige Absicherung für GoTo. Die Quest bekommt in dieser Stufe keinen Schalter und keinen STOP. Eine Mindesthöhe von 25° ist nicht eingebaut. Die Prüfung ist keine mechanische Kollisions-, Kabel- oder Stativsicherung.

## Koordinaten

Katalog, Overlay, Resolve und `POST /nina/mount/slew` verwenden RA in Grad. Auf diesem Weg wird nicht mit 15 multipliziert. Die NINA-Telemetrie `RightAscension` bleibt in Stunden. Die Umrechnung in Grad steht nur im Diagnosevergleich des GoTo-Logs.

Desktop-Aufrufe bleiben `ra` und `dec` als Grad. Ein Ziel unter dem Horizont oder hinter der Gartenmaske kommt jetzt mit einem Fehler zurück, statt still an NINA zu gehen.

Eine objektbezogene Auflösung für Mond und Planeten auf der Quest ist in dieser Stufe keine neue Route. Numerische RA/Dec-Aufträge bleiben der bestehende Vertrag.

## Bewegungszustand

Nach dem Start ist der Zustand `unklar`. `bereit` entsteht nur aus einer frischen Meldung: NINA erreichbar, Montierung verbunden, `slewing=false`, kein offener eigener Auftrag, Alter höchstens zwei Sekunden. `slewing=false` allein genügt nicht. Ein Timeout setzt nie `bereit`.

| Zustand | Neuer GoTo |
| --- | --- |
| `unklar` | nein |
| `bereit` | ja, wenn die übrigen Prüfungen gelten |
| `fährt` | nein |
| `stoppt` | nein |

Die Annahme eines GoTo oder einer Achsbewegung läuft unter einem kurzen Schloss. Der NINA-Aufruf liegt außerhalb davon. Eine laufende Generation macht eine verspätete Startantwort ungültig, wenn inzwischen STOP kam.

Stillstand nach einem gesehenen Slew oder nach STOP wird erst durch eine spätere frische Meldung mit `slewing=false` zu `bereit`. Solange der Start noch unbeantwortet ist, bleibt eine frühe Meldung ohne Slew bei `fährt`.

## Sperre

Desktop und eine spätere Quest teilen denselben Zustand. Zwei gleichzeitige GoTo-Anforderungen: eine wird angenommen, die andere erhält HTTP 409 `GoTo bereits aktiv`. Dieselbe Sperre gilt für `POST /nina/mount/move`.

`POST /nina/mount/slew/stop` und `POST /nina/mount/move/stop` warten nicht auf diesen Start. STOP erhöht die Generation und setzt `stoppt`.

SynScan, die NINA-Oberfläche und PHD2 können die Montierung an dieser Sperre vorbei bewegen. Unmittelbar vor dem GoTo zählt deshalb die frische Montierungsmeldung. Ein fremdes `slewing=true` blockiert den nächsten GoTo. Führt PHD2 oder kalibriert es, wird der GoTo abgelehnt. Ist PHD2 nicht lesbar, ebenfalls. `OFFLINE` gilt nicht als Führen.

Ein abgesetztes Quest-Headset oder ein WLAN-Abbruch stoppt einen laufenden GoTo nicht. Ein Totmann gehört zur späteren manuellen Feinsteuerung XR-10c, nicht zu diesem GoTo.

## STOP

STOP ist während eines GoTo erreichbar. HTTP 200 von NINA heißt nur, dass der Aufruf beantwortet wurde. Der Zustand bleibt `stoppt`, bis eine neue Meldung Stillstand zeigt. Schlägt der Aufruf fehl oder läuft er in einen Timeout, wird kein Erfolg gemeldet und der Zustand wird `unklar`.

Trifft STOP ein, während die Startantwort noch aussteht, und kommt danach ein verspätetes „Slew started“, bleibt der Zustand `stoppt`. Der Server sendet STOP erneut. Die verspätete Antwort wird nicht als normaler Start zurückgegeben.

## Prüfungen vor dem GoTo

Unmittelbar vor dem Auslösen: NINA erreichbar, Montierung verbunden, nicht geparkt, Zustand `bereit`, kein PHD2-Guiding, RA/Dec in Grad gültig, Ziel über dem geometrischen Horizont, und über der Gartenmaske, wenn die aktive Maske lesbar ist. Eine beschädigte Maske bei hinterlegtem Panorama wird abgelehnt. Ohne Maske gilt nur der geometrische Horizont.

## Zweite Instanz

`run_app` hält eine Byte-Sperre auf `data/horizon/mele-app.lock`. Eine zweite MeLE-App beendet sich, bevor sie eine eigene Bewegungsverwaltung aufmacht. Die Datei darf liegen bleiben. Blockierend ist die gehaltene Sperre. Windows gibt sie beim Prozessende frei, auch nach einem harten Abbruch. Das ist mit einem Unterprozess geprüft, der sich über `os._exit` beendet.

Das Schloss wird beim Start von `run_app` genommen. Es ersetzt nicht die Bewegungsprüfung.

## Schnittstelle

`GET /nina/mount` behält die bisherigen Felder. Daneben steht `motion` mit `state`, `label` und `detail`. Die Anzeige unterscheidet: NINA nicht erreichbar, Montierung nicht verbunden, Bereit, GoTo aktiv, STOP läuft, Achsbewegung aktiv, Zustand unklar.

Konflikte sind HTTP 409. Ein zeitlich unklarer Start oder STOP ist HTTP 502. Ungültige Koordinaten bleiben HTTP 400 und ändern den Zustand nicht.

## Tests

`tests/test_mount_motion.py`, ohne echte Montierung: gleichzeitige GoTo, zweiter Client, GoTo während Slew, GoTo während Achsbewegung, PHD2, STOP während Slew, STOP vor verspäteter Startantwort, STOP-Timeout, GoTo-Timeout, Verbindungsabbruch, Neustart im Zustand `unklar`, gültige und ungültige Koordinaten, RA in Grad ohne Faktor 15, Horizont und Gartenmaske, zweite Prozessinstanz einschließlich Freigabe nach hartem Ende. Zusätzlich zwei parallele HTTP-GoTo gegen eine Mock-NINA: einer wird angenommen, der zweite erhält 409, STOP wartet nicht auf den Start.

## Integration am MeLE, 2026-10-12

Die App wurde im Stillstand neu gestartet. `slewing=false`, Tracking aus, nicht geparkt. Danach eine Instanz, Schloss gehalten. Die erste Antwort von `GET /nina/mount` war bereits `bereit`: die Abfrage wendet die frische Meldung an, bevor sie antwortet. `unklar` bleibt der Zustand vor dieser Meldung. NINA war erreichbar, die Montierung verbunden. RA in der Telemetrie kam in Stunden, etwa 5,29.

Abgelehnt, ohne die Montierung zu bewegen: RA 400° mit HTTP 400, Ziel Dec −80° mit HTTP 409 `Ziel unter Horizont`. Der Zustand blieb `bereit`, `slewing` blieb falsch. PHD2 lief nicht und führte nicht. Die Ablehnung bei aktivem Guiding ist live nicht gelaufen.

Port 8443: `GET /nina/mount` liefert 200. `POST /nina/mount/slew` und `POST /nina/mount/slew/stop` antwortet Caddy mit 404 `Nicht freigegeben`. Eine zweite App beendet sich mit der Meldung, dass bereits eine Instanz läuft. Der Hörer auf 8082 bleibt derselbe Prozess.

Praktische Bewegungstests am 2026-10-12, über die Desktop-Oberfläche, an der angeschlossenen Montierung. XR-10b ist damit nicht abgenommen.

| Versuch | Ergebnis |
| --- | --- |
| GoTo, danach ein weiterer GoTo | Montierung gefahren. Die Quest zeigte `slewing` und der gelbe Telrad folgte. Anschließend wieder `bereit`. |
| STOP während eines Schwenks, danach erneuter GoTo | STOP unterbrochen, danach erneut angefahren und wieder `bereit`. |
| Kurzer GoTo zum benachbarten Objekt | Ziel angefahren. Abschlussmeldung: NINA online, Montierung verbunden, `slewing=false`, `motion.state=bereit`, siderische Nachführung an. |

Ob bei dem kurzen GoTo zwischendurch `slewing=true` ankam, steht in der Abschlussmeldung nicht. Eine dauerhafte Sperre ist bei diesem Versuch nicht hängen geblieben. Ein Timeout, der aus einem übersehenen Slew `bereit` macht, ist nicht eingebaut.

Der bisherige Desktop-STOP heißt `STOP` und liegt im zugeklappten Feld `NINA / GTi`. Der GoTo-Knopf der Objektkarte bleibt während `commanded` und `slewing` deaktiviert. Das ist die Oberfläche, nicht die serverseitige Sperre. Unten in der 360-Ansicht steht `STOP MONTIERUNG`. Er wird bei `fährt`, `stoppt`, `unklar` oder gemeldetem Slew bedienbar und ruft `POST /nina/mount/slew/stop`. HTTP 200 gilt dort nicht als Stillstand. Die Seite wird beim App-Start gelesen. Die Mehrclient-Sperre und die STOP-Rennbedingung sind über Mock-NINA geprüft, nicht durch zwei gleichzeitige reale Schwenks. PHD2-Guiding ist live nicht gelaufen.

## Stufe C

Die Bewegungssteuerung reicht aus, um die Vorbereitung von Stufe C zu beginnen. XR-10b bleibt nicht abgenommen. Vor einem Quest-GoTo steht die Zugriffskontrolle auf Port 8443. Der Port ist für die lesenden Pfade ohne Anmeldung erreichbar. Eine Freigabe von `POST /nina/mount/slew` und `POST /nina/mount/slew/stop` würde jedem Gerät, das den Dienst erreicht, dieselben Befehle geben. Ein Geheimnis in `vr.html` wäre keine zusätzliche Grenze, weil dieselbe Seite es ausliefern würde. Zuerst das Zugriffskonzept, danach zweistufige Bestätigung und ein immer erreichbarer STOP auf der Quest. XR-10c bleibt der Totmann für die manuelle Feinsteuerung.

## Verwandte Seiten

- [Astro-VR Architektur v1.7](astro-vr-architektur-v1.7.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
