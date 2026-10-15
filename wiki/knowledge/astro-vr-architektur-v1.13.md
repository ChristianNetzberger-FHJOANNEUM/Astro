# Astro-VR Architektur v1.13 — Kamerasteuerung und Sessionmonitor

> Quelle: Himmelspunkt in [v1.12](astro-vr-architektur-v1.12.md)
> Stand: **Abgenommen am 14. Oktober 2026.** ISO und Belichtungszeit der RW2 stimmen, STOP in der Quest-Session hat gehalten. Nächster Vorschlag: [v1.14](astro-vr-architektur-v1.14.md).

Die Quest soll eine laufende Fotosession fernbedienen und beobachten. Der Desktop bleibt für Objekt, Profil und Session zuständig. Es gibt keine zweite Profil- oder Sessiondatenbank.

Guiding, Dithering, Autofokus, Parken, Hibernate, komplexe Sequenzen und ein Profileditor auf der Quest gehören nicht hierher. Telrad, Panorama, Tagesbahn, Himmelspunkt und die Controllerbelegung bleiben unverändert.

## Befund

Einzelbild und Dateiablage sind im MeLE-Backend vorhanden. Die Serie ist es nicht: sie läuft als Schleife im Desktop-Browser (`imaging.html`). Bricht der Browser ab, endet die Serie nach dem gerade laufenden Bild. Ein Abbruch der laufenden Belichtung selbst ist im Code nicht vorhanden.

ISO, Belichtung und Bildanzahl sind im Backend nicht dieselbe Sache. Die Kamera-API liefert Gain und Belichtungsgrenzen, kein ISO und keine Werteliste. Profile und Sessions speichern ISO und Gain nebeneinander. Fehlt Gain, wird die ISO-Zahl als Gain an NINA geschickt.

Eine „aktive Session“ kennt der Server nicht. Die Auswahl lebt im Desktop-Browser. Ohne `session_id` legt `POST /astro/nina/capture` eine neue Session an. Die Quest darf diesen Weg nicht benutzen.

Die JPEG-Vorschau existiert (`mele/preview_service.py`, RW2 über rawpy). Sie entsteht in derselben Capture-Antwort und blockiert diese, bis das JPEG fertig ist. In einer Serie erzeugt der Desktop die Vorschau nur beim letzten Bild.

Live-Abfrage `GET /nina/camera` am 2026-10-13: NINA erreichbar, Kamera nicht verbunden. Die Antwort enthält kein ISO-Feld. Gain- und Belichtungsgrenzen waren deshalb leer. Eine Liste unterstützter ISO- oder Belichtungswerte lässt sich daraus nicht ableiten.

## Wiederverwendung

| Funktion | Desktop | Quest | Änderung |
| --- | --- | --- | --- |
| Kamerastatus `GET /nina/camera` | vorhanden | lesbar | kleine Status-Route, Caddy nur dieser Pfad |
| Einzelbild `NinaClient.capture` | vorhanden | intern | nicht 1:1 an die Quest geben |
| Serie | Browser-Schleife | nein | Server-Auftrag nötig |
| Abbruch mitten in der Belichtung | nicht vorhanden | nein | ungeklärt, ob NINA das kann |
| Stopp zwischen Bildern | Browser-Flag | nein | Flag am Server-Auftrag |
| Doppelstart | nicht gesperrt | nein | zweiter Start 409 |
| Profile, Sessions | `astro_manager.sqlite` | nur lesen | keine neue Datenbank |
| Aktive Session | nur im Desktop-Browser | nein | letzte offene Session des Objekts, sonst Hinweis, kein Anlegen |
| Belichtung | freie Zahl, Min/Max von der Kamera | ± nur aus Serverliste | Liste neu, nicht im Frontend |
| ISO | Profilfeld; bei der Lumix die NINA-Gain-Liste | ± nur aus `iso_steps` | ohne Liste nur der gespeicherte Wert, nicht veränderbar |
| Gain | Capture-Parameter | intern | Quest zeigt ISO, der Auftrag hält beide Werte fest |
| Bildanzahl | `lights_planned` | ± am Entwurf | ändert das Profil nicht |
| Dateiablage | Sessionordner, RW2 bleibt auf dem MeLE | Dateiname im Status | keine RAW-Übertragung |
| Vorschau | letztes Bild, blockiert die Antwort | später | Stufe B, eigener Lauf, nicht in der Capture-Antwort |
| Quest-Sitzung und CSRF | vorhanden | für POST | Kopplungscode unverändert |
| Caddy | keine Kamera-Pfade | — | erst die konkreten neuen Pfade |

Kennzeichnung: Kamerastatus, Einzelbild, Profile, Sessions, Dateiablage, Vorschau-Code, der Server-Auftrag, die Quest-Sessiontafel und die ISO-Stufen aus der Kamera-Gain-Liste sind **implementiert und auf der Quest abgenommen**. Abbruch mitten in der Belichtung und die JPEG-Vorschau bleiben **zurückgestellt**.

## Gemeinsame Datenführung

Ein Prozess auf dem MeLE hält höchstens einen Capture-Auftrag. Desktop und Quest starten ihn über dieselbe Funktion. Der Auftrag speichert zu Beginn Belichtung, Gain, ISO, Bildanzahl, Session und Objekt. Diese Werte ändern sich nicht mehr, auch wenn Desktop oder Quest danach die Felder anfassen.

Die Quest übernimmt das Profil des gewählten Objekts in einen Entwurf für den nächsten Start. Sie schreibt das gespeicherte Profil nicht zurück. Eine offene Session wird nur übernommen, wenn es genau eine gibt. Fehlt sie oder gibt es mehrere, kommt ein erklärender Status zurück. Es wird kein Ordner angelegt. Die Auswahl unter mehreren Sessions bleibt am Desktop. Beim Start prüft der Server die Session noch einmal: sie muss existieren, offen sein und zum Objekt gehören.

Ein zweiter Start, solange der Auftrag läuft oder ein Einzelbild noch in der bestehenden Route steckt, antwortet mit 409. Stopp setzt nur ein Flag: das laufende Bild wird zu Ende geschrieben, weitere Bilder starten nicht. Fällt die Quest aus, läuft der Auftrag weiter. Beim Wiederverbinden liest die Quest den Auftrag und die Session erneut.

Die Vorschau bleibt Stufe B. Sie darf den Auftrag nicht aufhalten. RAW bleibt im Sessionverzeichnis.

## Quest-Tafel

Eigener Bereich Kamera auf der bestehenden Tafel. Abzug, Griff und Ziehen bleiben wie in v1.12.

Anzeige: Kamera verbunden, Objekt, Session, übernommene Belichtung, ISO und Bildanzahl, Zustand, Fortschritt, letzter Fehler. Bedienung mit Minus und Plus, Profil neu laden, Start und Stopp. Kein Slider. Kein Start beim Öffnen. Während der Auftrag läuft, sind die Parameter gesperrt.

Die Wertelisten kommen vom Server. Solange die Kamera keine ISO-Liste liefert, zeigt die Tafel den Profilwert und lässt ISO nicht frei erfinden.

## API und Caddy

Die Quest ruft NINA nicht direkt auf. Die Serie läuft über die lokalen Auftragsrouten. `POST /astro/nina/capture` ist nur noch ein Einzelbild unter derselben Sperre. Ohne `session_id` kann dieser alte Aufruf weiterhin eine Session anlegen. Die Desktop-Oberflächen rufen ihn nicht mehr in einer Schleife auf. Auf 8443 liegt er nicht.

Für die Quest vorgesehen, noch ohne Caddy-Freigabe:

| Route | Zweck |
| --- | --- |
| `GET /api/camera/status` | Kamera, Auftrag, Fortschritt, letzter Dateiname |
| `GET /api/camera/context` | offene Session und Profil des Objekts, nur lesen |
| `POST /api/camera/capture/start` | Auftrag mit festem Parametersatz |
| `POST /api/camera/capture/stop` | Flag, kein Abbruch der laufenden Belichtung |
| `GET /api/camera/preview/latest` | Stufe B |

Schreibende Aufrufe nutzen die vorhandene Quest-Sitzung und `X-Astro-Csrf`. Der Kopplungscode bleibt auf dem MeLE. Caddy gibt nur diese Pfade frei, mit dem bestehenden Edge-Header bei POST. Keine WebSocket-Verbindung. Status etwa einmal pro Sekunde. Ein neues JPEG nur, wenn sich der Dateiname ändert.

## Reihenfolge

Der Server-Auftrag ist der erste Schritt. Danach die Tafel mit Status, Profilübernahme, Plus/Minus, Start und Stopp. Die große Bildtafel folgt, wenn die Vorschau den Auftrag nicht blockiert. Profile bearbeiten, Sequenzen und Bildanalyse bleiben zurückgestellt.

Am 14. Oktober 2026 ist eine Fotosession über den Desktop auf der Terrasse gelaufen. Die Aufnahme hat funktioniert, ebenso STOP während der Session. Die Quest war daran nicht beteiligt.

## Server-Auftrag

Desktop und Quest sind Clients. Die Serie lebt im MeLE-Prozess, im Speicher, nicht in einer Tabelle. `saved/planned` zählt nur Bilder, deren Datei gespeichert wurde.

| Zustand | Bedeutung |
| --- | --- |
| `idle` | Kein Auftrag in diesem Prozess |
| `running` | Serie läuft |
| `stop_requested` | Aktuelles Bild läuft fertig, danach Ende |
| `completed` | Alle geplanten Bilder gespeichert |
| `stopped` | Serie vor dem Plan beendet |
| `failed` | Auftrag durch einen Fehler beendet |

Stopp wirkt zwischen zwei Bildern. Die laufende Belichtung wird nicht abgebrochen. Ein zweiter Start antwortet mit 409. Nach einem Neustart des MeLE ist der Status `idle`, `resumable` ist falsch, und die `process_epoch` ist neu. Das ist eine Unterbrechung, keine erfolgreiche Fortsetzung.

Lokale Routen, nicht über Caddy freigegeben:

| Route | Antwort |
| --- | --- |
| `POST /astro/capture/start` | 200 mit festgehaltenem Auftrag, sonst 400, 404 oder 409 |
| `POST /astro/capture/stop` | 200 solange der Auftrag läuft, sonst 409 |
| `GET /astro/capture/status` | Zustand, `saved`, `planned`, Dateiname, Fehler |

`start` verlangt eine bestehende offene Session. Genau eine offene Session eines Objekts darf ohne `session_id` übernommen werden. Mehrere offene Sessions liefern `session_ambiguous` und die Liste. Eine geschlossene Session liefert `session_closed`. Ein laufender Auftrag liefert `busy`.

Jedes Bild geht durch `capture_one_frame` und damit durch `NinaClient.capture`. Die Vorschau hängt nicht an diesem Weg. Darks fragt der Desktop nach den Lights ab und startet dafür einen zweiten Auftrag. Schließt der Browser vorher, laufen die Lights weiter, die Darks starten nicht von selbst.

Geändert: `mele/capture_job.py`, `mele/capture_frame.py`, `app_mele/main_app.py`, `app_mele/imaging.html`, `app_mele/pano.html`, `tests/test_capture_job.py`.

Tests: `tests/test_capture_job.py`, 12 bestanden, ohne Kamera. Einzelbild, Serie, Doppelstart, Stopp während der Belichtung, Status nach dem Startaufruf, zwei Leser, Neustart, NINA-Fehler, fehlende, geschlossene und mehrdeutige Session, eingefrorene Belichtung, keine doppelte Zählung.

## Quest-Tafel

Die Quest bedient denselben Auftrag. Ein laufender Auftrag ist die Anzeige: Objekt, Belichtung, ISO, Gain, Bildanzahl und Fortschritt kommen von ihm. Profil neu laden und Plus/Minus sind dann gesperrt. Stopp beendet die Serie nach dem aktuellen Bild. Ohne Auftrag übernimmt die Quest nur eine eindeutige offene Session des gewählten Objekts und legt keine an. „PROFIL“ kopiert das Desktop-Profil in den Entwurf und speichert es nicht.

ISO springt nur durch `iso_steps`. Belichtung springt durch Bedienstufen aus `exposure_steps_s`, beschnitten mit den Kamera-Grenzen, wenn die Kamera sie meldet. Die Bildanzahl zählt in Einserschritten.

Caddy gibt nur `GET /astro/capture/status`, `GET /astro/capture/context`, `POST /astro/capture/start` und `POST /astro/capture/stop` frei. Start und Stopp verlangen die bestehende Quest-Sitzung und `X-Astro-Csrf`. Der Kopplungscode bleibt auf dem MeLE.

Zwei gleichzeitige Aufrufe von `POST /astro/nina/capture` sperren einander jetzt ebenfalls. Der alte Endpunkt kann ohne `session_id` weiterhin eine Session anlegen.

Abbruch mitten in der Belichtung und die JPEG-Vorschau bleiben zurückgestellt.

## Spätere Quest-Sessionverwaltung

Die Quest übernimmt in v1.13 vorhandene Sessions und Profile. Das begrenzt nur diesen Funktionsumfang. Es ist keine dauerhafte Vorgabe, dass Sessionverwaltung dem Desktop vorbehalten bleibt.

Desktop, Quest und ein späterer Nachtplaner sollen dieselben Sessions verwalten. `astro_manager.sqlite` bleibt die einzige Session- und Profildatenbasis. Sessionoperationen laufen über wiederverwendbare Funktionen auf dem MeLE. Neue Oberflächen erweitern diese API. Eine zweite Sessionverwaltung entsteht nicht.

Ein Capture-Auftrag speichert eine feste Session-ID und die Parameter vom Start. Die Sessionauswahl einer Oberfläche ändert diesen Auftrag nicht. Die Quest kann während einer laufenden Serie einen Entwurf für den nächsten Auftrag vorbereiten. Es gibt keine globale „aktive Session“, die alle Clients teilen müssen.

Session anlegen und Aufnahme starten bleiben getrennte Aktionen. Profilbearbeitung und der Nachtplaner sind weiterhin nicht Teil dieses Schritts.

## Quest-Sessiontafel

Die Quest folgt dem Desktop-Weg. Ein Objekt bietet GOTO und KAMERA. KAMERA öffnet die Sessions dieses Objekts. Eine Zeile wählt eine offene Session und öffnet danach die Aufnahmetafel. ＋ legt eine Session an. Die Rückmeldung lautet „Session erstellt“, erst dann erscheint die Aufnahmetafel.

Objekt, Profil und Ordner bestimmt der Server. Die Quest schickt den Katalognamen und optional eine Profilnummer. Ein Profil eines anderen Objekts wird abgelehnt. Gibt es mehrere Profile, wählt die Quest eines aus der Rückgabe, der Server prüft die Zugehörigkeit. Pfade aus dem Client werden auf diesem Weg nicht übernommen.

Eine neue Auswahl schreibt nicht die `session_id` eines laufenden Auftrags um. Ein zweiter Start mit einer anderen Session erhält 409, der laufende Auftrag behält seine Session. Läuft bereits ein Auftrag, öffnet KAMERA die Aufnahmetafel dieses Auftrags.

Caddy gibt `GET /astro/sessions` und `POST /astro/sessions` frei. Anlegen verlangt die bestehende Kopplung und `X-Astro-Csrf`. Die Sessiontafel bleibt wie abgenommen.

## Quest-Feldtest 14. Oktober 2026

Auf der Quest geprüft:

| Schritt | Ergebnis |
| --- | --- |
| Objekt mit der Montierung anvisieren | gelungen |
| Session auf der Quest anlegen | gelungen |
| Kamera löst aus | gelungen |
| Dateien im MeLE-Verzeichnis | gelungen |
| ISO wählen | gelungen |
| ISO und Belichtungszeit in der RW2 | gelungen, später am selben Abend |
| STOP während der Quest-Session | gelungen, später am selben Abend |

Der erste Lauf am Abend konnte ISO noch nicht wählen. Der spätere Lauf hat ISO und Belichtungszeit an der RW2 bestätigt und STOP in der Session geprüft.

## ISO der Lumix

Der Lumix-Treiber in NINA hat kein eigenes ISO-Feld an der Capture-Schnittstelle. Die Empfindlichkeit liegt auf der Eigenschaft Gain. `GET /equipment/camera/info` der verbundenen DC-S5M2X lieferte am 14. Oktober 2026 abends `CanSetGain` und die Liste `Gains`: 100, 125, 160, 200, 250, 320, 400, 500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000, 10000, 12800, 16000, 20000, 25600, 32000, 40000, 51200. Der gerade gesetzte Gain war 125. Diese Liste ist die ISO-Stufenliste des verwendeten Aufnahmemodus, nicht eine aus GainMin und GainMax abgeleitete Reihe.

`GET /astro/capture/context` gibt sie als `iso_steps` aus und setzt `iso_adjustable` auf wahr. Die vorhandenen Plus- und Minus-Tasten der Quest springen nur innerhalb dieser Liste. Es gibt keine freie Zahleneingabe. Fehlt die Liste, weil die Kamera getrennt ist oder `Gains` leer bleibt, enthält `iso_steps` nur den in der Session oder im Profil gespeicherten ISO-Wert, `iso_adjustable` ist falsch, und die Tafel meldet „ISO fest vom Profil.“

Beim Start ersetzt ein ISO-Wert aus dieser Liste einen davon abweichenden gespeicherten Gain. Der Auftrag speichert beide Zahlen gleich und übergibt sie unverändert als `gain` an `sync_snapshot_controls` (`SnapShotControlSettings-Gain`) und an `NinaClient.capture`. Ohne bestätigte Liste bleibt die bisherige Regel: ein gesetzter Gain hat Vorrang, fehlt er, wird die ISO-Zahl als Gain geschickt. Eine bei NINA angekommene Zahl belegt noch nicht, dass die Kamera mit dieser Empfindlichkeit belichtet hat.

### Quest-Prüfung

Am späteren Abend des 14. Oktober 2026 sind ISO und Belichtungszeit der geschriebenen RW2 korrekt. STOP innerhalb der Session hat funktioniert. Damit ist die Empfindlichkeit an der Datei belegt, nicht nur an der nach NINA gesendeten Zahl.

Abbruch mitten in einer Belichtung bleibt ungeklärt. Die JPEG-Vorschau bleibt zurückgestellt.
