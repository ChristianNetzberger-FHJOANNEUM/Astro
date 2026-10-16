# Astro-Toolkit Roadmap v1

> Quelle: [Architektur v1.17](astro-vr-architektur-v1.17.md), Kameramodell in [v1.16](astro-vr-architektur-v1.16.md)
> Stand: **16. Oktober 2026, später Abend.** Leitdokument für den externen Agenten. v1.16 ist auf Quest und Desktop geprüft, einschließlich des WORK-Transfers. Das PHD2-Kamerabild, der Leitstern und die Guiding-Steuerung sind auf der Quest bestätigt. Das Kamerabild schreibt höchstens alle 4 s; dabei blieb PHD2 bedienbar. Alert-Zeile und Kalibrierstatus liegen im Code und sind wegen geschlossener Wolkendecke nicht geprüft. Der laufende Name bleibt `app_mele`.

Eine Anwendung, ein Steuerungsserver, mehrere Bedienoberflächen, frei kombinierbare Hardwareprofile. NINA und PHD2 bleiben die Geräteschicht. Die MeLE-Station mit Lumix, Quest und den abgenommenen Abläufen bleibt die Referenz. Dieselbe Software soll später auf einem anderen Windows-Rechner mit anderem Setup laufen, ohne Quellcodeänderung. Dieser Beweis steht noch aus.

## Vier Regeln

1. Die Oberfläche fragt Gerätefähigkeiten beim Server ab. Sie setzt nicht voraus, dass jede Kamera ISO oder ROI hat.
2. Rechnerkonfiguration, Stationsprofil, Kamerakonfiguration, Rezept, Session und Aufnahmeauftrag haben getrennte Aufgaben. Dieselbe Angabe liegt nur an einer Stelle.
3. Aufnahme und Montierung laufen nur über den zentralen Server. Ein weiterer Aufnahmeadapter lässt `nina.capture` unverändert.
4. Jede Erweiterung läuft auf der bestehenden MeLE-Installation weiter. Migrationen bleiben rückwärtsverträglich. Ein Quest-Test ist die Abnahme für eine relevante Änderung.

Neue Pfade und Dienste kommen in `configs/mele.yaml`. Vorhandene Vorgaben werden dafür nicht vorgezogen umgebaut. Der Test auf einem zweiten Rechner folgt später.

## Bereits implementiert

Phase 0 ist die stabile Referenz. NINA steuert GOTO, STOP, Achse und Einzelbild. SynScan Pro wird nur gestartet. PHD2 spricht über den Event-Server. Desktop und Quest nutzen denselben Server. Sessions, Lights, Darks, STOP, Zurück und Wetterexport sind auf der Quest erprobt. Ein Aufnahmeauftrag je Prozess. Ein zweiter Start liefert 409.

Der virtuelle Monitor hat zwei Hauptquellen. Nach einem einzelnen Light und beim Schließen der Session mit ZURÜCK entstehen JPEG und RAW-Statistik mit Histogramm. Die Quest zeigt Bild, Kennzahlen und logarithmische Skala, sobald die Dateien fertig sind. Am 16. Oktober 2026 war das nach dem Schließen und später an der gespeicherten Session sichtbar. Quelle `light_preview` bleibt dafür. Dieselbe Fläche zeigt das vorhandene PHD2-Kamerabild, wenn die Quelle GUIDING ist. Die Abfrage läuft nur, solange diese Quelle sichtbar ist. Am 16. Oktober 2026 hat die Quest dieses Bild bestätigt. Eine Serie analysiert während des Laufs nichts. FWHM, Sternzahl und Plate Solving sind nicht Teil dieser Scheibe.

Der Leitstern ist eine zweite Fläche rechts neben dem GUIDING-Bild, Quelle `phd2_star`, über denselben PHD2-Client und `get_star_image`. Sie wird nur abgefragt, solange GUIDING sichtbar ist. Am 16. Oktober 2026 hat die Quest diese Fläche bestätigt, einschließlich HFD und SNR aus dem letzten PHD2-GuideStep, wenn der Schritt jünger als 30 s ist. Diesen Schritt gibt es nur während des Guidings. Beim Looping sendet PHD2 die Zahlen der eigenen Statuszeile nicht mit. Ein fehlender Wert bleibt ein Strich und wird nicht als Null angezeigt. Eine eigene FWHM-Rechnung aus dem Sternbild gibt es nicht.

Am späteren Abend desselben Tages sind vier weitere Punkte auf der Quest bestätigt. Ausdehnung und Abstand stehen in einer zweiten Spalte der Objektdetailseite, sofern der Katalog sie hergibt. Galaxien bekommen keine Entfernung aus der Parallaxe; M31 bleibt ohne Abstand. Die Monitorgröße ist in den Einstellungen von der Tafel getrennt, 100 bis 200 Prozent, Vorgabe 100 Prozent. Nach einem Katalog-GoTo bleibt die Objektdetailseite offen, einschließlich KAMERA und GUIDING.

Die Guiding-Tafel gehört zur Montierung und nicht zu einer Foto-Session. Neben KAMERA steht GUIDING. Die Tafel bedient den vorhandenen PHD2-Client: Belichtung, LOOP, AUTO STAR, GUIDE, PAUSE und STOP. Die Bilder bleiben auf dem vorhandenen Monitor. Steuerung, Leitstern, HFD und SNR sind am selben Abend bestätigt. ZURÜCK, SCHLIESSEN und eine abgerissene Quest senden keinen PHD2-Stopp. Diese Regel ist im Code und an diesem Abend nicht eigens geprüft.

Der letzte PHD2-Alert erscheint in einer gelben Zeile und verschwindet, wenn der Stern zurück ist, Guiding startet oder eine Kalibrierung beginnt. GUIDE nutzt eine vorhandene Kalibrierung. NEU erzwingt eine neue, am aktuellen Himmelspunkt und ohne Katalogkoordinate. Während der Kalibrierung zeigt die Statuszeile den Schritt. Liegt eine Kalibrierung vor, steht „Kalibrierung vorhanden“, sonst „keine Kalibrierung“. Ein sinnvolles Ziel nahe dem Himmelsäquator bleibt Sache des Beobachters. Alert und Kalibrierung sind wegen geschlossener Wolkendecke am späteren Abend nicht geprüft.

`configs/mele.yaml` ist die Rechnerkonfiguration. Kamera, Konfiguration und die fünf Rezepte liegen in `astro_manager.sqlite`. Die früheren objektgebundenen Profile und die Testsessions sind aus dieser Datei entfernt. Die Aufnahmeordner auf der Platte bleiben. `equipment-profiles.json` war im Arbeitsbaum nicht vorhanden. Das Modul dafür bleibt. Das optische Inventar liegt in `wiki/inventar/components.yaml`.

## Verbindlich geplant

Die Reihenfolge folgt dem Audit. Die Phasen sind keine Versionsgrenzen. Der Monitor ist schon vor den Stationsprofilen entstanden.

**Phase 1, v1.16.** Umgesetzt und auf Quest und Desktop geprüft. Am Desktop: Session anlegen, Rezept wählen, Parameter setzen, Lights und Darks, Wetterexport, Vorschau und WORK-Transfer. Session 72, Polaris, 6 Lights und 2 Darks, Belichtung 1 s, ISO 100, Wetter `ok`. Der Transfer nach `\\100.97.226.18\Astro\Work\Mele` ist nach gespeicherter Windows-Anmeldung angekommen. Eine geänderte Belichtung gilt für die weiteren Aufnahmen dieser Session. Die Sessionzeile zeigt den zuletzt gespeicherten Wert. Jede Datei behält die Belichtung ihres eigenen Namens. Das Rezept bleibt unverändert. An diesem Paket ist nichts mehr offen.

**Phase 2, Rest des Monitors.** Das PHD2-Kamerabild liegt auf derselben Monitorfläche. LICHT und GUIDING schalten die Quelle um. Das Kamerabild und der Leitstern sind auf der Quest bestätigt.

PHD2 gibt das Vollbild nur über `save_image` heraus. PHD2 schreibt eine temporäre FITS-Datei, die App wandelt sie in ein JPEG im Arbeitsspeicher und löscht die Datei. Einen reinen Speicherpfad für das Vollbild gibt es an dieser Schnittstelle nicht. `get_star_image` bleibt der Ausschnitt um den Leitstern. Desktop und Quest teilen einen `Phd2Client` und eine TCP-Verbindung. Beim Öffnen des GUIDING-Monitors blieb PHD2 zweimal auf „Not Responding“, im gesehenen Fall bei 0,2 s Looping, weil überlappende `save_image`-Aufrufe den Fensterthread belegt haben.

Der Mindestabstand für das Kamerabild ist 4 s und lässt sich nicht kürzer stellen. Es läuft nur ein PHD2-Bildbefehl gleichzeitig. Die 4 s zählen ab dem Ende des Schreibens. Die Bildsperre ist eine eigene Sperre und nicht die Socket-Sperre des Event-Servers. Die Quest fragt weiter jede Sekunde; innerhalb der 4 s kommt das JPEG aus dem Speicher. Der Leitstern bleibt bei etwa 1 s und reiht sich hinter ein laufendes Kamerabild. Am späteren Abend des 16. Oktober 2026 blieb PHD2 mit diesem Abstand auf der Quest bedienbar. Unter dem Leitstern stehen HFD und SNR aus dem letzten GuideStep. Das sind PHD2-Werte, keine neu gerechnete Sternanalyse, und die Quest hat sie während des Guidings bestätigt. FWHM aus einem Helligkeitsprofil, eine Seeing-Trennung von der Nachführung und Plate Solving kommen danach. Plate Solving befiehlt der Montierung nichts. Die Sessionzeile bleibt beim zuletzt gespeicherten Wert. Verschiedene Belichtungen derselben Session stehen in den Dateinamen.

Die Guiding-Tafel ist umgesetzt. Alert-Zeile, Kalibrierschritt und der Button NEU warten auf klare Sicht. Eine geschlossene Wolkendecke hat diese Prüfung am späteren Abend verhindert.

**Phase 3, Stationsprofil.** `equipment-profiles.json` wird erweitert und verweist auf die Kamerakonfiguration aus v1.16. Montierung, Optik, Guider, Hauptkamera, Standort und Fähigkeiten bilden ein wählbares Setup. ISO und Belichtung bleiben in Konfiguration und Rezept.

**Phase 4, gemeinsame Steuerung.** Ein serverseitiger Halter für Kamera und Montierung, bevor eine zweite Quest mitsteuert. Weitere Clients lesen. Danach ein zweiter Aufnahmeadapter für ASI585-Planetenvideo, neben `nina.capture`.

## Langfristige Vision

**Phase 5.** Die Windows-Skripte unter `deployment/windows` gelten für diesen Rechner. Ein Diagnoselauf prüft NINA, PHD2, Datenbank, Aufnahmeordner und HTTPS und ändert nichts. Ein Installer, der Treiber oder NINA still verändert, entsteht nicht. Der Beweis ist eine Aufnahme auf einem zweiten Windows-Rechner mit anderer YAML und demselben Frontend.

Danach können autonome Abläufe, ein Sequencer, Plate Solving und weitere Geräteklassen folgen. Eine eigene Treiberschicht, ein eigenes Betriebssystem-Image und ein zweiter Capture-Stack entstehen nicht. Windows bleibt die Serverplattform. Die Clients sind Browser.

KStars und Ekos liefern das Vorbild für Equipment-Profile und einen Setup-Assistenten. StellarMate zeigt, dass ein Profil nicht an zwei Stellen gepflegt werden darf. NINA.Polaris bleibt eine technische Referenz für mehrere Rigs und getrennte Aufnahmeverfahren. INDIGO bleibt das Vorbild für die Trennung von Gerät, Agent und Client.

## Name und Veröffentlichung

Ein öffentlicher Name ist nicht gewählt. `app_mele` bleibt der technische Name, solange keiner festgelegt ist. In der engeren Auswahl stehen AstroBridge für die Plattform und AstroDeck für die Bedienoberfläche. OpenObservatory, AstroVista XR und SkyPilot sind unverbindliche Vorschläge. Marke, Domain und Repositories sind nicht geprüft.

Ein erster Starfinder-Artikel beschreibt die laufende Station: Mini-PC, NINA, PHD2, 360-Grad-Bedienung, Lights, Darks, Session und Wetter. Die erste Monitorscheibe und das PHD2-Bild darauf sind auf der Quest gesehen und werden nicht als reine Planung bezeichnet. FWHM und Plate Solving bleiben geplant. Ein zweiter Artikel kann später den Schritt zum Toolkit zeigen. Der Artikel wird nicht mit diesem Leitdokument geschrieben.
