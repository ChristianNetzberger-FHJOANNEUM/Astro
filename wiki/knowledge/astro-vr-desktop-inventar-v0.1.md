# Astro-VR Desktop-Inventar v0.1 — XR-8a

> Quelle: `app_mele/pano.html`, das daraus geöffnete Imaging-Fenster, die dazu gehörenden Routen in `app_mele/main_app.py`
> Stand: **Bestandsaufnahme, kein Code.** XR-3c ist auf der Quest abgenommen ([v0.9](astro-vr-architektur-v0.9.md)).

Dieses Inventar beschreibt, was der Desktop heute tut. Es legt keine VR-Menüstruktur fest. `OBJEKTE` und `EINSTELLUNGEN` im Quest-Dashboard bleiben der Ausgang.

## Grenze

Aufgenommen ist, was `pano.html` bedienbar macht, plus das Imaging-Fenster, das der Knopf `Imaging` öffnet (`app_mele/imaging.html`, Route `/imaging-view`).

Nicht aufgenommen, weil es nicht in `pano.html` liegt:

- Die App-Leiste in `app_mele/layout.py`: NINA starten, SynScan starten, PHD2 starten, Guiding, Wetter, Hilfe, Einstellungen, Tools, Horizont erkennen, PNG-Export, Standortliste, Beenden.
- Guiding und die PHD2-Routen. `pano.html` ruft sie nicht auf.
- SynScan. Die Montierung im 360°-Viewer spricht NINA an, nicht SynScan direkt.
- Die Almanach-Seite selbst. `pano.html` öffnet sie nur.

`pano.html` enthält noch Imaging-Funktionen (`renderImaging`, `captureImagingSession`, Profil- und Session-Formulare). Deren DOM steht nicht mehr in `pano.html`. Bedienbar ist diese Fassung nicht. Die lebende Fassung ist `imaging.html`. Sie ist unten als IMG geführt, nicht als zweite verfügbare Kopie.

## Quest heute

Bereits vorhanden, deshalb keine neue Aufgabe: Panorama am Kopf, Sterne bis mag 5,5, Sternbilder, Sonne, Mond, Planeten, 15-Sekunden-Takt, Objektliste aus benannten Sternen und Gestirnen (höchstens sechs), Detail mit RA, Dec, Azimut und Höhe, Telrad mit einem Ringsystem, Hysterese, Dashboard, Preferences in `localStorage`.

Über `https://vr.netzberger.at:8443` ist von den Datenrouten nur `/sky-overlay` freigegeben. `/catalog`, `/sky-track`, `/nina` und `/astro` sind dort nicht erreichbar. Sie laufen auf der App, Port 8082.

## Legende

Wirkung: `Anzeige`, `Daten`, `Gerät`.

VR-Eignung verbindet den Abgleich mit der Quest und die Einschätzung: `vorhanden`, `teilweise`, `fehlt` und dazu `direkt`, `Anpassung` oder `ungeeignet`.

Panelnamen sind Vorschläge.

## 1. Objekte und Katalog

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| P-30 | Suche und Zentrieren. Umgesetzt. | Feld `Suche`, Knopf ⌕, Enter, Trefferliste, Escape schließt | `runSkySearch`, `resolveCatalogQuery`, `activateCatalogQuery` | `GET /catalog/search`, `GET /catalog/resolve` | Anzeige | Katalog, lat/lon | Trefferliste, sonst Status im Himmel | fehlt · Anpassung | Objekte und Katalog |
| P-31 | Favoriten einblenden, wählen, merken. Umgesetzt. | Schalter Favoriten, Liste `★ Favoriten…`, Stern im Infokasten | `loadFavoritesList`, `loadFavoriteMarkers`, `toggleSelectedFavorite` | `GET/POST/DELETE /catalog/favorites`, `GET /catalog/favorites/markers` | Daten | gewähltes Objekt mit Schlüssel | Stern gefüllt oder leer, Marker am Himmel | fehlt · Anpassung | Objekte und Katalog |
| P-32 | Tonight-Marker. Umgesetzt. | Schalter Tonight | `loadTonightMarkers` | `GET /observe/tonight/markers` | Anzeige | aktive Beobachtungsliste, lat/lon | Marker, sonst leerer Himmel | fehlt · Anpassung | Beobachtungsplanung |
| P-33 | Objektinfo per Klick. Umgesetzt. | Klick ohne Ziehen auf Stern, DSO, Mond, Planet, Sonne | `pickAt`, `showInfo` | Daten aus dem letzten `/sky-overlay` | Anzeige | Overlay geladen | Kasten: Art, mag, Sternbild, Typ, HIP, Katalog, RA, Dec, Az, Höhe, Mondphase | teilweise · Anpassung. Quest: nur benannte Sterne und Gestirne, höchstens sechs, über Telrad | Objekte und Katalog |
| P-34 | Infokasten schließen. Umgesetzt. | `x`. Bahn kann angeheftet bleiben | `hideInfo` | keine | Anzeige | — | Kasten zu | teilweise · direkt. Quest schließt das Panel mit dem Abzug | Objekte und Katalog |
| P-35 | Tagesbahn und Stundenmarken. Umgesetzt. | Schalter `Bahn an diesem Tag`, `Stunden`. Nach Schließen des Kastens Panel `Bahn aktiv` mit Objektinfo und `Bahn aus` | `loadTrack`, `drawTrackPoints`, `updateTrackPin`, `clearPinnedTrack` | `GET /sky-track` | Anzeige | RA/Dec, lat/lon, Horizontprofil zum `stem` | Text: Sonne, beobachtbare Fenster, Nacht/Dämmerung/Tag als Linienart | fehlt · Anpassung | Beobachtungsplanung |
| P-60 | Imaging-Fenster zum gewählten Objekt öffnen. Umgesetzt. | Knopf `Imaging` im Infokasten | `openImagingWindow`, `loadImaging` | Seite `/imaging-view`. Wechsel per `BroadcastChannel` `mele-imaging` | Anzeige | Popup erlaubt. Ohne Objekt öffnet das Fenster leer | Statuszeile: geöffnet, blockiert oder kein Objekt | fehlt · Anpassung. Das Fenster selbst ist eine eigene Fläche | Kamera, NINA und Aufnahmen |

## 2. Himmel, Panorama und Overlays

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| P-03 | Textur wechseln. Umgesetzt. | Knöpfe `1 Vorschau`, `2 Transparentes PNG`, `3 Original`. Tasten 1, 2, 3 | `switchTo`, `load` | Bild-URL aus der Seitenadresse, kein API-Aufruf | Anzeige | Datei vorhanden, sonst Knopf aus | Hinweiszeile, bei Original oft „zu groß für die Grafikkarte“ | fehlt · Anpassung. Die Quest lädt eine Textur aus der URL, ohne Umschalter | Himmel, Panorama und Overlays |
| P-04 | Umsehen und Zoom. Umgesetzt. | Ziehen, Mausrad, Tasten `+` und `-` | `applyLook`, `setFov` | keine | Anzeige | — | Hinweiszeile | vorhanden als Kopfbewegung. Maus und Tasten ungeeignet | — |
| P-10 | Sterne. Umgesetzt. | Schalter Sterne, Vorgabe an | `loadSky`, `drawOverlay` | `GET /sky-overlay` `stars` | Anzeige | lat/lon | `sky-status` | vorhanden bis mag 5,5, ohne Schalter | Himmel, Panorama und Overlays |
| P-11 | Sternbilder. Umgesetzt. | Schalter Sternbilder, Vorgabe an | `loadSky` | `GET /sky-overlay` `const` | Anzeige | lat/lon | `sky-status` | vorhanden, ohne Schalter | Himmel, Panorama und Overlays |
| P-12 | Messier. Umgesetzt. | Schalter Messier, Vorgabe an | `loadSky` | `GET /sky-overlay` `messier` | Anzeige | lat/lon | `sky-status` | fehlt · Anpassung. Dieselbe Route, Parameter heute 0 | Himmel, Panorama und Overlays |
| P-13 | NGC. Umgesetzt. | Schalter NGC, Vorgabe aus | `loadSky` | `GET /sky-overlay` `ngc` | Anzeige | lat/lon. Kann die Antwort schwer machen | `sky-status` | fehlt · Anpassung | Himmel, Panorama und Overlays |
| P-14 | Mond und Planeten. Umgesetzt. | Schalter Mond/Planeten, Vorgabe an | `loadSky`, `addSunDisc`, `addMoonDisc` | `GET /sky-overlay` `planets` | Anzeige | lat/lon | `sky-status` | vorhanden, ohne Schalter | Himmel, Panorama und Overlays |
| P-15 | Grenzhelligkeit. Umgesetzt. | Schieber mag 0 bis 9, Schritt 0,5, Vorgabe 5,5 | `loadSky`, `persistPrefs` | `GET /sky-overlay` `mag`. Speichern `POST /ui-prefs` | Anzeige und Daten | lat/lon | Zahl neben dem Schieber | fehlt · Anpassung. Quest fest 5,5 | Himmel, Panorama und Overlays |
| P-16 | DSO-Typen. Umgesetzt. | Sechs Schalter im Panel Anzeige: Galaxien, Kugelhaufen, offene Haufen, planetarische Nebel, Nebel, Sonstiges | `selectedDsoTypes` | `GET /sky-overlay` `dso_types`. Speichern `POST /ui-prefs` | Anzeige und Daten | Messier oder NGC an | keine eigene Zeile | fehlt · Anpassung | Himmel, Panorama und Overlays |
| P-17 | Live-Himmel, 15 s. Umgesetzt. | Schalter Live, Vorgabe an. Startet bei jedem Laden an, auch wenn andere Anzeigen gespeichert sind | `startLivePolling` | `GET /sky-overlay` mit aktueller Zeit | Anzeige | lat/lon | Uhrzeit im Feld `when` | vorhanden. Quest fest 15 s, ohne Schalter | Himmel, Panorama und Overlays |
| P-18 | Zeitpunkt setzen. Umgesetzt. | Feld Datum/Uhrzeit, `Jetzt`, `Fotozeit`, `-1d`, `-1h`, `+1h`, `+1d`. Jede dieser Aktionen schaltet Live aus | `currentWhen`, `loadSky` | `GET /sky-overlay` `when` | Anzeige | `Fotozeit` nur, wenn die Seite `photo` in der Adresse hat, sonst Knopf aus | `sky-status` | fehlt · Anpassung | Himmel, Panorama und Overlays |
| P-19 | Standort. Umgesetzt. | Felder lat und lon | `persistSite`, `restoreSite` | `GET/POST /site-coords`. Sonst `configs/mele.yaml` | Daten | `stem` des Panoramas | `sky-status`, wenn leer | fehlt · ungeeignet als freies Zahlenfeld. Der Ort gehört zur Aufnahme, nicht in jede Sitzung | Einstellungen und Systemstatus |
| P-20 | Sterngröße. Umgesetzt. | Schieber 0,5 bis 3 im Panel Anzeige | `applyStarScale` | `POST /ui-prefs` `star_scale` | Anzeige und Daten | Overlay schon gezeichnet | Zahl neben dem Schieber | fehlt · Anpassung. Quest stellt die Schildhöhe ein, nicht die Scheibengröße | Einstellungen und Systemstatus |
| P-21 | Gitter. Umgesetzt, nur im Browser. | Schalter Az/h-Gitter, Äquatorraster, Ekliptik. Schritt 10° oder 5° | `drawGrid`, `drawHorizontalGrid`, `drawEquatorialGrid`, `drawEcliptic` | keine Rechnung. Speichern `POST /ui-prefs` | Anzeige und Daten | lat/lon für Äquator und Ekliptik | Linien und Beschriftung im Bild | fehlt · Anpassung | Himmel, Panorama und Overlays |
| P-50 | Panorama-Azimut über die Schattenlinie. Umgesetzt. | Panel `Panorama-Azimut kalibrieren`: markieren, zwei Klicks, berechnen, übernehmen, abbrechen. Escape bricht ab | `addCalibPoint`, `postCalib` | `POST /shadow-calibration`. Übernehmen schreibt den Nordversatz, nicht das Bild | Daten | lat, lon, Uhrzeit, zwei Punkte | `calib-result`, Hilfslinien N, S, Sonne | fehlt · ungeeignet. Zwei Pixelklicks im equirektangularen Bild. Auf der Quest ist der Nordversatz schon in der Kugel | Einstellungen und Systemstatus |
| P-51 | Horizont-Punktwolke. Umgesetzt. | Panel: anzeigen, starten/stoppen, Klick setzt, Ziehen verschiebt, letzten Punkt, Speichern, Horizontlinie generieren | `drawHorizon`, `postHorizon`, `loadHorizonControls` | `GET/POST /horizon-controls`. Generieren ersetzt das transparente PNG | Daten | `stem`, Bildmaße `srcw`/`srch` | `horizon-result`, Punktzahl, neues PNG | fehlt · ungeeignet am Controller. Einmalige Vorbereitung am Desktop | Einstellungen und Systemstatus |
| P-05 | Abbrechen von Kalibrierung, Hilfslinien und Punktwolke. Umgesetzt. | Taste Escape, außer in einem Eingabefeld | `keydown` | keine | Anzeige | — | Hinweiszeile zurück auf Umsehen | fehlt · ungeeignet. Die Quest hat diese Modi nicht | — |

## 3. Montierung und Positionierung

SynScan kommt in `pano.html` nicht vor. Lesen und Schwenken laufen über die NINA-Advanced-API, Proxy in der App.

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| P-40 | NINA- und Mount-Status. Umgesetzt. | Panel `NINA / GTi`, Polling jede Sekunde, Timeout 1,5 s | `pollNinaMount`, `renderNinaStatus` | `GET /nina/mount` | Anzeige | NINA-REST auf dem MeLE. Die Montierung wird nicht direkt gefragt | LED rot / gelb / grün. RA, Dec, Az, Alt, Tracking, Slew, Pier | fehlt · Anpassung als reine Anzeige | Montierung und Positionierung |
| P-41 | GoTo. Umgesetzt. | Knopf `GoTo` im Infokasten, dann noch einmal `GoTo` oder `Abbrechen` | `showGotoConfirm`, `executeGoto` | `POST /nina/mount/slew?ra&dec` | Gerät | Objekt mit RA/Dec. NINA online, Mount connected, nicht parked. Knopf bleibt aus, solange ein Slew läuft | Bestätigungstext mit RA/Dec. Danach Status. Marker am Ziel | fehlt · Anpassung. Bestätigung behalten. Nicht auf einen einzelnen Abzug legen | Montierung und Positionierung |
| P-42 | Slew abbrechen. Umgesetzt. | Knopf `STOP`, rot | `executeStop` | `POST /nina/mount/slew/stop` | Gerät | aktiv, sobald ein Slew gemeldet wird oder ein GoTo läuft | `nina-goto-status` | fehlt · Anpassung. Muss ohne Suche erreichbar bleiben | Montierung und Positionierung |
| P-43 | Mount-Spur. Umgesetzt, als Debug gekennzeichnet. | Schalter `Mount-Spur (Debug)`, `Spur loeschen` | `drawMountTrailLine`, `clearMountTrail` | keine eigene Route. Punkte aus `GET /nina/mount` | Anzeige | NINA online | Linie und Punkte im Panorama | fehlt · ungeeignet im Normalbetrieb | Montierung und Positionierung |
| P-44 | GoTo-Diagnose speichern. Umgesetzt, ohne eigenen Knopf. | läuft bei Start, Ende, Fehler und STOP mit | `beginGotoDiag`, `finalizeGotoDiag` | `POST /nina/goto-log` | Daten | ein GoTo oder STOP | Zeiten und Fehler im Statustext, Datei auf dem MeLE | fehlt · ungeeignet als eigene VR-Fläche. Darf an einem späteren GoTo hängen bleiben | Montierung und Positionierung |
| P-45 | Achsbewegung. Nicht in `pano.html`. | — | Routen existieren in `main_app.py` | `POST /nina/mount/move`, `POST /nina/mount/move/stop`, `GET /nina/mount/move/status` | Gerät | Guiding-Seite, nicht der 360°-Viewer | — | fehlt · nicht als Pano-Funktion zählen | Montierung und Positionierung |

`POST /nina/mount/slew` prüft RA/Dec, NINA erreichbar, Mount connected und nicht parked. Eine zusätzliche Mehrclient-Sperre steht in dieser Route nicht. Die Roadmap verlangt sie trotzdem, bevor ein VR-Befehl hinzukommt. Das ist eine offene Lücke, kein schon gebautes Schloss.

## 4. und 5. Kamera, NINA, Sessions, Bilder

Nur der Einstieg liegt in `pano.html` (P-60). Die folgenden Funktionen sind umgesetzt in `imaging.html`. Sie gelten erst, wenn ein Objekt gewählt ist. Capture spricht NINA. Die übrigen Zeilen ändern Sessions, Dateien oder die Vorschau.

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| IMG-01 | Objekt laden. Umgesetzt. | kommt vom 360°-Viewer oder von der Adresse `key` | `loadImaging` in `imaging.html` | `GET /astro/object/{catalog_key}` | Anzeige | Katalogschlüssel | Titel und Übersicht: Profile, Sessions, Pfade, Integration | fehlt · Anpassung | Kamera, NINA und Aufnahmen |
| IMG-02 | Aufnahmeprofil anlegen, ändern, löschen. Umgesetzt. | Formular, Speichern, Neu, Bearbeiten, Löschen mit `confirm` | `imaging.html` | `GET/POST /astro/profiles`, `DELETE /astro/profiles/{id}` | Daten | Objekt | Statuszeile, Liste | fehlt · ungeeignet als VR-Formular | Kamera, NINA und Aufnahmen |
| IMG-03 | Session anlegen, wählen, ändern. Umgesetzt. | Liste, `＋`, Formular, Speichern, Abbrechen | `imaging.html` | `GET/POST /astro/sessions`, `PUT /astro/sessions/{id}` | Daten | Objekt, optional ein Profil | Sessionzeile mit Lights, Darks, Archiv, Wetterstatus | fehlt · Anpassung nur für eine kurze Statuszeile, nicht für das Formular | Sessions und Bildverwaltung |
| IMG-04 | Capture-Lauf. Umgesetzt. | `▶ Capture` oder `⏹ Stop` nach dem laufenden Frame. Darks fragen vorher, ob der Tubus abgedeckt ist | `captureImagingSession` | `POST /astro/nina/capture`. Phase über `GET /nina/camera` | Gerät | Session offen, NINA, Kamera. Geschlossene Session sperrt den Knopf | Lauftext, Sekunden pro Frame, am Ende Preview | fehlt · Anpassung. Langer Lauf, Stop muss sichtbar bleiben, Bestätigung für den Start | Kamera, NINA und Aufnahmen |
| IMG-05 | Letztes Bild. Umgesetzt. | Farbe, `Neu stretchen`, Klick und Ziehen setzen einen Ausschnitt | `loadSessionPreview`, `wirePreviewRoi` | `GET/POST /astro/sessions/{id}/preview`, `POST .../preview/roi`, Datei `.../preview/file` | Anzeige und Daten | FITS im Session-Ordner | Bild oder „Kein FITS“ | fehlt · ungeeignet. Fläche und Mauszeiger, nicht der Himmel | Sessions und Bildverwaltung |
| IMG-06 | Capture-Timing. Umgesetzt. | Knopf am Session-Detail, Dialog, Schließen | `showSessionTimingLog` | `GET /astro/sessions/{id}/timing` | Anzeige | Session | Dialog mit Zeiten | fehlt · ungeeignet | Sessions und Bildverwaltung |
| IMG-07 | Session schließen. Umgesetzt. | Knopf am Detail | `closeImagingSessionUi` | `POST /astro/sessions/{id}/close` | Daten | Session offen | Status, Capture danach aus | fehlt · Anpassung mit Bestätigung | Sessions und Bildverwaltung |
| IMG-08 | Wetter der Session exportieren. Umgesetzt. | Knopf am Detail | `exportSessionWeatherUi` | `POST /astro/sessions/{id}/weather/export` | Daten | Session, Wetterdaten | Status `ok`, `partial` oder `fehlt` | fehlt · ungeeignet | Sessions und Bildverwaltung |
| IMG-09 | Dateien schieben. Umgesetzt. | WORK, Archiv, WORK nach Archiv | `pushSessionToWorkUi`, `pushSessionToArchiveUi`, `pushSessionWorkToArchiveUi` | `POST /astro/sessions/{id}/push/work`, `.../push/archive`, `.../push/work-archive` | Daten | Pfade, Netzfreigaben | Statuszeile, Archivstatus | fehlt · ungeeignet | Sessions und Bildverwaltung |
| IMG-10 | Session entfernen. Umgesetzt. | Dialog: CAPTURE, WORK, DB-Eintrag, optional Erzwingen. NAS/ARCHIVE wird nicht gelöscht | `confirmRemoveSession` | `POST /astro/sessions/{id}/remove` | Daten | bewusste Häkchen | Dialog, danach Liste | fehlt · ungeeignet | Sessions und Bildverwaltung |
| P-61 | Alte Imaging-Funktionen in `pano.html`. Vorbereitet, nicht bedienbar. | kein Knopf, DOM fehlt | `renderImaging`, `captureImagingSession` und die Formularhelfer in `pano.html` | dieselben Routen wie IMG, werden von dieser Seite nicht erreicht | — | — | — | nicht zählen | — |

## 6. Beobachtungsplanung

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| P-02 | Almanach öffnen. Umgesetzt als Absprung. | Link `Almanach` | `link-almanach` | Seite `/observe-view` mit lat, lon, `stem` | Anzeige | Popup | neues Fenster | fehlt · Anpassung. Die Seite selbst ist hier nicht zerlegt | Beobachtungsplanung |
| P-32 | Tonight-Marker | siehe Abschnitt 1 | | | | | | | |
| P-35 | Tagesbahn und Fenster | siehe Abschnitt 1 | | | | | | | |

Die Knöpfe der Almanach-Seite (`Almanach laden`, `Liste speichern`, Listen unter `/observe/lists` und `/observe/almanac`) gehören nicht zu `pano.html`. Sie bleiben der nächste Blick, falls Beobachtungsplanung in die Quest soll.

## 7. Einstellungen und Systemstatus

| ID | Funktion | Desktop-Bedienung | Implementierung | Backend | Wirkung | Voraussetzungen | Rückmeldung | VR-Eignung | Panelvorschlag |
|---|---|---|---|---|---|---|---|---|---|
| P-01 | Zurück zur App. Umgesetzt. | Link `Zurueck` | `href="/"` | keine | Anzeige | — | App-Seite | fehlt · ungeeignet. Die Quest bleibt im Viewer | — |
| P-70 | Anzeige speichern. Umgesetzt, ohne Knopf. | Änderung an Mag, Sterngröße, Gittern, Katalogen, DSO-Typen, Tonight, Favoriten, Horizontpunkten | `persistPrefs`, `restorePrefs` | `GET/POST /ui-prefs`, Datei `data/horizon/ui-prefs.json` | Daten | Schreibrecht auf dem MeLE | keine eigene Meldung. Live wird nicht gespeichert und startet immer an | fehlt · Anpassung. Die Quest speichert ihre eigenen Werte lokal, nicht diese Datei | Einstellungen und Systemstatus |
| P-71 | WLAN. Umgesetzt. | Text `WLAN …` in der Leiste, Details im Tooltip | `pollWifiStatus` | `GET /network/wifi` | Anzeige | Windows-WLAN auf dem MeLE | Kurztext und Empfangsklasse | fehlt · direkt als eine Statuszeile, ungeeignet als Tooltip | Einstellungen und Systemstatus |

## Abhängigkeiten

| Arbeitet wo | Funktionen |
|---|---|
| Nur im Browser | Umsehen, Zoom, Gitter, Texturwechsel, Escape, Infokasten aufklappen, Mount-Spur zeichnen |
| `/sky-overlay` | Sterne, Sternbilder, Messier, NGC, Mond/Planeten, Mag, DSO-Typen, Live, Zeitpunkt. Das ist die einzige dieser Routen, die die Quest heute erreicht |
| Katalog und Ephemeride | Suche, Favoriten, Tonight, Objektinfo, Bahn. Python rechnet, der Browser zeichnet |
| NINA | Status, GoTo, STOP, GoTo-Log, Capture, Kamera-Phase während der Aufnahme |
| SynScan | keine Funktion in `pano.html` |
| Sessions und Dateien | IMG-02 bis IMG-10 |
| Schon auf der Quest | P-04 als Kopf, P-10, P-11, P-14, P-17, ein Teil von P-33 und P-34 |

## Offene Architekturfragen

1. Die Quest darf `/sky-overlay` mit anderen Parametern rufen, ohne eine neue Route. Messier, Mag und Zeitpunkt wären damit erreichbar. Katalog, Bahn, NINA und Sessions brauchen entweder eine bewusste Caddy-Freigabe oder sie bleiben auf dem Desktop.
2. GoTo hat auf dem Desktop schon eine zweite Bestätigung. STOP ist ein eigener, immer sichtbarer Knopf. Beides sollte so bleiben. Die Slew-Route selbst sperrt keine zweiten Clients.
3. Capture dauert viele Belichtungen. Abbruch wirkt erst nach dem laufenden Frame. Eine VR-Fläche müsste den Lauf zeigen, auch wenn man den Himmel ansieht.
4. Kalibrierung und Horizont-Punktwolke sind Mausarbeit am equirektangularen Bild. Sie gehören nicht an den Controller.
5. Profil-, Session- und Pfadformulare sind Desktop-Verwaltung. In die Quest passt höchstens eine kurze Statuszeile, nicht das Formular.
6. Die Anzeigen des Desktops liegen in `ui-prefs.json` auf dem MeLE. Die Quest-Preferences liegen in `localStorage` des Headsets. Das sind zwei Speicher.
7. `pano.html` trägt toten Imaging-Code. Er ist keine zweite Funktion und sollte nicht nachgebaut werden.
8. Guiding, PHD2, SynScan-Start und der PNG-Export liegen außerhalb dieses Viewers. Sie fehlen hier absichtlich.

## Vorschlag für eine spätere Migration

Noch keine Panelarchitektur. Reihenfolge, sobald sie festgelegt wird, an der Erreichbarkeit und am Risiko entlang:

1. Nur Anzeige, und nur über `/sky-overlay`: Messier, Grenzhelligkeit, Zeitpunkt. Das Dashboard mit `OBJEKTE` und `EINSTELLUNGEN` bleibt.
2. Lesende Erweiterungen, die heute an Port 8443 scheitern: Suche, Favoriten, Tonight, Tagesbahn, NINA-Status, WLAN. Zuerst die Freigabe des Pfads entscheiden, nicht die Fläche.
3. Gerätebefehle zuletzt und einzeln: GoTo mit der bestehenden Doppelbestätigung, STOP immer erreichbar, Capture mit sichtbarem Lauf. Kein Befehl aus einer Zeigebewegung.
4. Nicht übernehmen: Horizont-Punktwolke, Schattenkalibrierung, Session-Formulare, Dateischieben, Mount-Spur, die tote Imaging-Kopie in `pano.html`.

## Verwandte Seiten

- [Astro-VR Architektur v0.9](astro-vr-architektur-v0.9.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
