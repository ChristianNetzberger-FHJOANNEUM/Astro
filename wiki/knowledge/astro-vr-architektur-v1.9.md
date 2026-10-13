# Astro-VR Architektur v1.9 — XR-10b Quest-GoTo

> Quelle: Bewegungstests in [v1.8](astro-vr-architektur-v1.8.md)
> Stand: **Abgenommen am 2026-10-13.** Quest-Feldtest 2026-10-12, Polaris-Auflösung HIP 11767 am 2026-10-13. Fortschreibung: [v1.10](astro-vr-architektur-v1.10.md).

Die lesenden Quest-Pfade bleiben ohne Anmeldung. GoTo, STOP und die Achsbewegung brauchen eine Berechtigung. Die Prüfung sitzt in der App. Ein direkter Aufruf von Port 8082 umgeht sie nicht. Eine Caddy-Pfadliste allein ist keine Anmeldung.

## Kopplung

Der MeLE-Browser holt `GET /mount-session/code`. Der Code hat sechs Ziffern, bleibt derselbe und läuft nicht ab. Diesen Pfad gibt Port 8443 nicht frei. Eine Verbindung über Caddy oder aus dem übrigen Netz erhält ihn nicht. Ohne diesen Code könnte jedes Gerät, das die Quest-Adresse erreicht, eine Sitzung starten und die Montierung fahren. Ein wechselnder Code ist dafür nicht nötig.

Auf der Quest steht `KOPPELN`. `POST /mount-session/pair` setzt das Cookie `astro_mount` mit `HttpOnly`, `Secure` und `SameSite=Strict`. Das CSRF-Token steht nur in der Antwort und im Speicher der Seite, nicht in `vr.html`. Die Sitzung gilt zwölf Stunden und endet mit dem Prozess.

Steuerbefehle senden das Token im Kopf `X-Astro-Csrf`. Ohne Sitzung und ohne dieses Token antwortet die App mit HTTP 401, bevor eine Bewegung beginnt.

Der Browser auf dem MeLE bleibt die Desktop-Bedienung, wenn die Verbindung von einer Adresse dieses Rechners kommt und nicht über Caddy läuft. Caddy setzt bei den Steuerpfaden `X-Astro-Edge: caddy`. Dadurch sieht die weitergeleitete Quest-Verbindung nicht wie der lokale Desktop aus.

## Quest

`GOTO` in der Objektdetailansicht öffnet nur die Bestätigung: Name, RA, Dec, Montierungsstatus und der Hinweis, dass das Teleskop sich bewegt. `ABBRECHEN` sendet nichts. `GOTO BESTÄTIGEN` ist die zweite Controller-Aktion und sendet `POST /nina/mount/slew?target=`.

`target` ist der bestehende Auflösungstext, bei Mond und Planeten der Name. Der Server löst die Koordinaten unmittelbar vorher neu auf. RA bleibt Grad. Schlägt die Auflösung fehl, fährt die Montierung nicht. Eine Positionsrechnung im Browser kommt nicht hinzu.

`STOP` liegt oben auf der Tafel, sobald der Zustand `fährt`, `stoppt` oder `unklar` ist oder die Telemetrie einen Slew meldet. Nach dem Schließen der Tafel öffnet die bisherige Controller-Aktion sie wieder. STOP ist dann ohne weiteren Weg erreichbar. Er nutzt `POST /nina/mount/slew/stop`. HTTP 200 ist kein Stillstand. Ein Browser-Timer gibt den Zustand nicht frei.

Während der Fahrt zeigt die Tafel `Montierung fährt` und das Ziel. Der gelbe Telrad bleibt die Montierung, der grüne das Ziel, der Winkel bleibt der bestehende Abstand.

## Caddy

Erst nach der Prüfung auf Port 8082:

- `GET /mount-session`
- `POST /mount-session/pair`
- `POST /nina/mount/slew`
- `POST /nina/mount/slew/stop`

`/mount-session/code`, `/nina/mount/move` und die übrigen NINA-Pfade bleiben zu. Die Achsbewegung auf Port 8082 unterliegt derselben Berechtigung. Eine Quest-Feinsteuerung ist das nicht.

## Tests

`tests/test_mount_access.py` prüft ohne Montierung: Ablehnung ohne Sitzung, lokaler Desktop, Caddy-Kennzeichnung, festen Kopplungscode, Fehlversuche ohne Codewechsel, Ablauf der Sitzung, CSRF, direkter Zugriff, STOP während eines offenen Starts, Verbindungsabbruch ohne automatischen STOP. Der erste Quest-Druck enthält keinen Slew-Aufruf.

Feldtest auf der Quest, 2026-10-12: Kopplung, mehrere GoTo mit beobachteter Fahrt und STOP haben funktioniert. Polaris allein meldete „Ziel unter Horizont“. Die Auflösung nahm den Namen als Teilwort und traf NGC 2573 Polarissima Australis (Deklination etwa −89°). Ein exakter Sternname geht jetzt vor dieser Teilwortsuche.

Die Objektdetailansicht und die GoTo-Bestätigung zeigen RA und Dec des bereits gewählten Himmelskörpers. Beim Stern im Himmel kamen diese Werte schon vor der Korrektur aus der Sterntabelle. Die Prüfung ohne Fahrt ist die Katalogsuche. Am 2026-10-13 hat diese Suche auf der Quest funktioniert: Polaris wird als HIP 11767 aufgelöst, Deklination etwa +89,3°. Ein weiterer Schwenk war dafür nicht nötig.

## Festlegungen 2026-10-13

Der Kopplungscode bleibt fest, ohne Ablauf und ohne Wechsel. Das gilt für die private Nutzung. Code-Rotation, eine Ablaufzeit des Codes oder eine weitere Anmeldung sind keine Voraussetzung für XR-10b oder XR-10c. Wird das System später außerhalb des privaten Netzes betrieben, wird der Zugang neu bewertet.

Parken über NINA ist ASCOM `Park()` und ist nicht SynScan-Hibernate. Hibernate gibt die NINA-API nicht her. Ein späterer Knopf heißt PARKEN, bewegt zur gespeicherten Parkposition und sichert das Alignment nicht. Ob STOP eine Parkfahrt abbricht, ist offen. Parken gehört nicht zu XR-10b und nicht zu XR-10c.

XR-10b ist am 2026-10-13 abgenommen. XR-10c Stufe A steht in [v1.10](astro-vr-architektur-v1.10.md). Eine gehaltene Achse stoppt bei Loslassen und bei Verbindungsverlust. Ein laufendes GoTo läuft nach dem Verlust der Quest weiter.

## Verwandte Seiten

- [Astro-VR Architektur v1.8](astro-vr-architektur-v1.8.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
