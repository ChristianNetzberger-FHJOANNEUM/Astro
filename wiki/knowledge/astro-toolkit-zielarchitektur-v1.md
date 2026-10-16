# Astro-Toolkit Zielarchitektur v1

> Stand: **15. Oktober 2026**, Abschnitt 11 ergänzt am **16. Oktober 2026, später Abend.** Langfristige Referenz. Nur Dokumentation. Der operative Stand steht in der [Roadmap v1](astro-toolkit-roadmap-v1.md).
> Dieses Dokument beschreibt, wohin sich das Gesamtsystem entwickeln soll. Es ersetzt weder den Code-Audit [v1.17](astro-vr-architektur-v1.17.md) noch die operative [Roadmap v1](astro-toolkit-roadmap-v1.md) noch den Kameramodell-Entwurf [v1.16](astro-vr-architektur-v1.16.md).

| Dokument | Zweck |
| --- | --- |
| [astro-vr-architektur-v1.17.md](astro-vr-architektur-v1.17.md) | Was der Code tatsächlich macht |
| [astro-toolkit-roadmap-v1.md](astro-toolkit-roadmap-v1.md) | Was als Nächstes entwickelt wird |
| astro-toolkit-zielarchitektur-v1.md | Wohin sich das Gesamtsystem langfristig entwickeln soll |

Der technische Name bleibt `app_mele`. AstroBridge, AstroDeck und weitere Arbeitstitel sind keine festgelegten Produktnamen.

## 1. Vision und Anwendungsbereich

Aus der heutigen `app_mele` entsteht schrittweise eine wiederverwendbare Plattform für astronomische Beobachtungsstationen. Eine Anwendung, ein zentraler Steuerungsserver, mehrere Bedienoberflächen, frei kombinierbare Hardwarezusammenstellungen.

Die Plattform soll auf geeigneten Windows-Mini-PCs und Notebooks laufen und verschiedene Teleskope, Montierungen, Kameras, Guider und Zubehör aufnehmen. Vollständige Zusammenstellungen werden als Observatory Profiles geführt. Geräte werden möglichst über bewährte Programme angesprochen, vor allem NINA und PHD2. Die Workflows für Beobachtung und Aufnahme bleiben vereinfacht und wiederholbar.

Desktop, Tablet und unterschiedliche WebXR-Headsets sind Clients desselben Servers. Mehrere Clients sehen denselben Status. Gerätebefehle laufen ausschließlich über den Server. Später können dreidimensionale Instrumente und ein virtueller Kontrollraum dazukommen. Die bisherige Quest-Tafel bleibt dabei erhalten.

Der Server bleibt zunächst Windows. Plattformübergreifend sind die Browser-Clients. Ein eigener universeller Kameratreiber und ein Ersatz für NINA oder PHD2 sind kein Entwicklungsziel.

Die Gestaltung der immersiven Station orientiert sich allgemein an der Bedienphilosophie einer Science-Fiction-Kommandobrücke. Sie ist eine eigenständige astronomische Oberfläche und keine Nachbildung einer bekannten Film- oder Fernsehkulisse. Eine spätere Veröffentlichung im Starfinder des Astronomieclubs Auersbach vermittelt dieselbe eigenständige Softwareentwicklung.

## 2. Bestehende Architektur als Ausgangsbasis

Grundlage ist der in v1.17 geprüfte Stand. NINA ist der Weg für GOTO, STOP, Achsbewegung und Einzelbilder. SynScan Pro wird nur gestartet. PHD2 wird über den Event-Server angesprochen. Desktop und Quest nutzen denselben Prozess und dieselben Routen. Die immersive Seite ist `/vr-view` auf Three.js und WebXR. Diese Implementierung bleibt die Grundlage. Ein iPad ist ein Browser auf demselben Port.

`configs/mele.yaml` ist die Rechnerkonfiguration: Port, Datenbank, Pfade, NINA-Adresse, Programmdateien, PHD2, Wetterserver und Standortkoordinaten. Die einzige Session-Datenbank ist `astro_manager.sqlite`.

Drei Bestände bleiben getrennt:

1. Kamera, Kamerakonfiguration und Aufnahmerezept liegen seit v1.16 in `astro_manager.sqlite`. Die fünf Rezepte heißen Kurz 2 s, Mittel 5 s, Mittel 6 s, Standard 10 s und Lang 20 s. Die Bildanzahl gehört nicht zum Rezept. Die früheren objektgebundenen Profile sind aus dieser Datei entfernt. Die Aufnahmeordner auf der Platte bleiben.
2. `mele/equipment_profiles.py` definiert ein Stationsprofil mit Montierung, Aufnahmeoptik, Guiding-Kamera, Guidescope, PHD2-Profil sowie Brennweite und Pixelgröße des Guiders. Der Maßstab in Bogensekunden je Pixel wird daraus berechnet. Die Datei liegt vorgesehen unter `{horizon_dir}/equipment-profiles.json`, mit `horizon_dir` aus `configs/mele.yaml` also unter `data/horizon/equipment-profiles.json`. Diese JSON-Datei war am 15. Oktober 2026 im Arbeitsbaum nicht vorhanden. Der Code liefert dann einen leeren Speicher. Konkrete gespeicherte Setups werden hier nicht behauptet.
3. `wiki/inventar/components.yaml` ist das optische Inventar, darunter das Lacerta 80/500 ED-APO mit 500 mm Brennweite und 80 mm Öffnung. Es ist keine laufende Konfiguration.

`sessions.equipment_profile_id` ist ein leeres Textfeld und wird nicht zum Schlüssel eines zweiten Profilmodells.

## 3. Langfristige Zielarchitektur

```
Desktop · Tablet · Quest · weitere WebXR-Clients
        ↓ Status und Befehle
Zentraler Workflow-Server
  Katalog und GOTO
  Sessions und Aufnahmeaufträge
  Kamerakonfigurationen und Rezepte
  Stationsprofile
  Bildanalyse und Vorschau
  Steuerungsrechte
        ↓
NINA          PHD2          weitere Adapter
Montierung    Guiding       Video, Sensoren
Kamera
        ↓
Teleskope · Montierungen · Kameras · Guider · Zubehör
```

Die Oberfläche vereinfacht den Zugang zu NINA und PHD2. Sie baut diese Programme nicht nach.

### Prinzipien 1 bis 4

Diese vier Regeln gelten schon für die nächsten Schritte und bleiben hier verbindlich.

1. Die Oberfläche fragt Gerätefähigkeiten beim Server ab. Sie setzt nicht voraus, dass jede Kamera ISO oder ROI besitzt.
2. Jede Information hat genau eine maßgebliche Quelle.
3. Sämtliche Gerätesteuerung läuft über den zentralen Server.
4. Jede Erweiterung bleibt mit der funktionierenden MeLE-Station verträglich. Migrationen bleiben rückwärtsverträglich. Ein Quest-Test ist die Abnahme für eine relevante Änderung.

### Prinzipien 5 bis 10

5. Desktop und WebXR verwenden dieselben serverseitigen Geräte- und Workflow-Funktionen.
6. Visuelle Instrumente sind austauschbare Darstellungen. Sie enthalten keine eigene Hardwaresteuerung.
7. Geräteprofile, Aufnahmeverfahren, Rezepte, Sessions und Aufnahmeaufträge bleiben logisch getrennt.
8. Neue Hardware und neue Bedienoberflächen erzeugen keine zweite Kopie des Auftragsmanagers.
9. Die Architektur bleibt für spätere autonome Beobachtungsabläufe und eine NINA-Sequencer-Integration erweiterbar. Beides wird jetzt nicht umgesetzt.
10. Die bestehende Three.js- und WebXR-Implementierung bleibt die Grundlage der immersiven Bedienung.

## 4. Hardware- und Stationsprofile

Ein Observatory Profile ist die aktive Zusammenstellung einer Station. Es referenziert vorhandene Komponenten. Es legt keinen zweiten Bestand für dieselben Angaben an.

| Bestandteil | Maßgebliche Quelle | Im Profil |
| --- | --- | --- |
| Montierung, Aufnahmeoptik, Guiding-Kamera, Guidescope, PHD2-Profil | `equipment-profiles.json` über `mele/equipment_profiles.py` | Verweis und aktive Auswahl |
| Hauptkamera, Fähigkeiten, ISO oder Gain, Offset, Binning, ROI, Kühlung | Kameramodell aus v1.16, sobald es angelegt ist | Verweis auf Kamera und Kamerakonfiguration |
| Belichtung, Bildanzahl, Bildtyp | Aufnahmerezept aus v1.16 | kein Bestandteil des Stationsprofils |
| Session und ihre kopierten Ausgangswerte | `sessions` | gehört zum Objekt, nicht zum Stationsprofil |
| Tatsächlich verwendete Aufnahmewerte | Aufnahmeauftrag | unveränderlich je Serie |
| Standortkoordinaten | `configs/mele.yaml` | Verweis auf den Standort, keine zweite Koordinatenkopie als Aufnahmeparameter |
| Horizont | `horizon_dir` | Verweis auf das Panorama und die Horizontmaske der Station |
| Okulare, Flattener, Reducer, Teleskopstamm | `wiki/inventar/components.yaml` | optionale Verweise auf Inventar-IDs |
| Aufnahmeverfahren | Adapter am Server, heute `nina.capture` | Verweis auf das verfügbare Verfahren, etwa Einzelbild oder später Video |

ISO, Gain, Belichtungsdauer und Bildanzahl stehen in Kamerakonfiguration, Rezept, Session oder Auftrag. Das Stationsprofil wiederholt sie nicht. Beziehungen sind Verweise: welche Kamera an welcher Optik, welche Optik auf welcher Montierung, welches Guidescope zu welcher Aufnahmeoptik, welcher Treiber oder welches Programm welches Gerät steuert. Das Bildfeld entsteht aus der Brennweite der Aufnahmeoptik und den Sensordaten der gewählten Kamera.

Fähigkeiten werden vom Server normalisiert und an jede Oberfläche gegeben. Eine Kamera nennt, was sie kann: ISO, Gain, Offset, Kühlung, ROI, Binning, Einzelbild, Video. Eine Montierung nennt, was sie kann: GOTO, Achsbewegung, Tracking, später Plate Solving. Die Oberfläche blendet Bedienelemente nach dieser Liste ein. Ein Kameraname im Client entscheidet das nicht.

Heute meldet NINA eine Gain-Liste. Eine Liste mit mindestens zwei Werten wird als ISO angeboten. Das entspricht der Lumix S5IIX. Dieselbe Regel würde eine echte Gain-Liste einer anderen Kamera fälschlich als ISO zeigen. Die Zielarchitektur ersetzt diese Annahme durch die Fähigkeitsliste der Kamera. Kühlung, ROI und Video sind im heutigen Stand nicht als Fähigkeiten beschrieben. Plate Solving ist im NINA-Aufruf ausgeschaltet.

## 5. Immersive Bedienphilosophie

Die virtuelle Station ist eine eigenständige astronomische Kommandobrücke. Die folgenden Bereiche sind ein Gestaltungskonzept. Sie sind keine Verpflichtung, dafür getrennte virtuelle Räume zu bauen. Sie können Seiten, Tafeln oder spätere Instrumente derselben Three.js-Szene sein.

### Kommandobrücke

Die zentrale Beobachtungsfläche trägt das reale 360-Grad-Panorama des Platzes, den eingeblendeten Sternenhimmel, die Objektwahl, GOTO, die Beobachtungsplanung und den gemeinsamen Status der Station. Die heutige Quest-Tafel mit Objekt, Session und Kamera ist die vorhandene Form dieser Fläche.

### Maschinenraum

Die technische Darstellung der Montierung zeigt ein dreidimensionales Modell, die RA- und DEC-Achsen, Tracking und Slewing, den Guiding-Status sowie Position und Abweichung. Eine Live-Animation aus Telemetrie ist ein späterer Schritt. Jede Anzeige unterscheidet drei Herkunftsarten: gemessen, berechnet, nicht verfügbar. Eine fehlende Größe bleibt als nicht verfügbar sichtbar.

### Wissenschaftslabor

Hier liegen der virtuelle Bildmonitor, RAW-Histogramm und Bildstatistik, die Belichtungsparameter, später FWHM und Sternzahl, eine Fokusbewertung, Plate Solving, der Vergleich mehrerer Probeaufnahmen und noch später Planetenvideo. Plate Solving zeigt ein Ergebnis. Es erteilt der Montierung keinen eigenen Befehl. Ein Befehl ginge durch die bestehende Server-API.

### Navigation

Eine räumliche Himmelskarte, der Objektkatalog, die Sichtbarkeit und später geplante Beobachtungssequenzen. Der Katalog und die Objektwahl auf der heutigen Tafel sind der vorhandene Kern.

## 6. Professionelle 3D-Instrumente

Ein späterer Ausbau bleibt auf der vorhandenen Three.js- und WebXR-Seite. Denkbare Werkzeuge sind Blender für die Modellierung, glTF oder GLB als Modellformat, Three.js für Darstellung und Animation, WebXR für die räumliche Interaktion und die vorhandenen `app_mele`-APIs für Status und Steuerbefehle. Diese Werkzeuge sind nicht beauftragt.

Ein virtuelles Instrument folgt zwei Wegen.

Status:

**Gerätedaten → Server → normalisierter Gerätestatus → Three.js-Instrument**

Befehl:

**VR-Interaktion → bestehende Server-API → Validierung und Steuerungsberechtigung → Hardwareadapter**

Ein 3D-Instrument spricht nicht mit NINA, PHD2 oder einem Hardwaretreiber. Die einfache Quest-Tafel bleibt. Professionelle Instrumente kommen optional und schrittweise dazu. Modelle und Animationen bleiben so leicht, dass ein mobiles XR-Headset eine stabile Bildrate hält. Ein Instrument, das die Tafel oder den Himmel ausbremst, gehört nicht in die Szene.

## 7. Server- und Mehrbenutzerkonzept

Dieselbe Station kann langfristig vom Desktop, vom Tablet und von mehreren Headsets gleichzeitig betrachtet werden.

| Art | Bedeutung |
| --- | --- |
| Paralleles Lesen | Mehrere Clients sehen Status, Himmel, Session und Vorschau |
| Koordinierte Steuerung | Montierung und Kamera haben einen Halter. Weitere Clients lesen, bis der Halter frei ist oder die Steuerung ausdrücklich übergeben wird |
| Aufnahmeauftrag | Ein Auftrag je Prozess. Ein zweiter Start bleibt abgelehnt. Es gibt keine zweite Capture-Engine je Client |
| Zustand | Der Server ist die einzige Darstellung von Auftrag, Montierung und Session. Clients halten keine abweichende Steuerungswahrheit |

Der heutige Auftrag ist diese Grundlage. Die Montierung hat den Halter noch nicht. Der lokale Desktop steuert ohne Kopplung. Jede Quest-Kopplung kann eine weitere Sitzung anlegen. Zwei steuernde Headsets sind deshalb Vision, bis der Halter existiert. Rollen und eine Benutzerverwaltung sind nicht der erste Schritt dorthin.

## 8. Aufnahmeverfahren und Automatisierung

Der Einzelbildweg über `nina.capture` bleibt. Weitere Verfahren sind Erweiterungspunkte und werden jetzt nicht gebaut.

| Erweiterungspunkt | Rolle |
| --- | --- |
| NINA-Einzelbild | vorhandener Weg für Lights und Darks |
| Planetenvideo mit ROI | zweiter Adapter für eine Kamera, die Video kann. Er benutzt den Einzelbildweg nicht |
| Weitere Kamerafunktionen | nur über die Fähigkeitsliste, etwa Kühlung und Auslesemodus |
| Beobachtungssequenzen | spätere Aufträge aus mehreren Rezepten und Objekten |
| NINA Advanced Sequencer oder Target Scheduler | spätere Anbindung an NINA, ohne den Sequencer nachzubauen |
| Nächtliche Warteschlange | spätere Folge von Aufträgen auf demselben Server |

Ein neues Verfahren registriert sich am zentralen Auftragsmanager. Es erzeugt keinen eigenen Manager und keinen zweiten Auftragsspeicher. Session-Vorgaben und die Werte eines Auftrags bleiben getrennt, damit eine Probe und eine folgende Serie in derselben Session vergleichbar bleiben.

## 9. Portabilität und Deployment

Dieselbe Anwendung soll auf einer zweiten Windows-Maschine mit anderer Hardware laufen. `configs/mele.yaml` bleibt die maßgebliche Rechnerkonfiguration: Port, Dienste, Pfade, Programmdateien, Datenbank, Aufnahmeordner, Archiv, Wetter und Standort. Programmcode und Datenverzeichnisse bleiben getrennt. Externe Programme und Treiber, darunter NINA, PHD2, SynScan Pro und Kameratreiber, werden geprüft und ihre Einrichtung angeleitet. Der Server verändert sie nicht still.

Ein Diagnoselauf prüft später die Erreichbarkeit von NINA, PHD2, der Datenbank, des Aufnahmeordners und von HTTPS und ändert dabei nichts. Datenbankmigrationen bleiben rückwärtsverträglich. Backup und Wiederherstellung gelten für `astro_manager.sqlite`, die Konfiguration und die Aufnahmeordner, ohne eine zweite Datenbank einzuführen. HTTPS und Netzwerk, heute Caddy und der lokale DNS-Name, gehören zur Rechnerkonfiguration und nicht in den Anwendungscode.

Der Nachweis ist eine Aufnahme auf einem zweiten Windows-Rechner mit anderer YAML und unverändertem Anwendungscode. Ein vollständiger Installer ist dafür nicht der erste Schritt. Die Skripte unter `deployment/windows` beschreiben die heutige Maschine.

## 10. Abgrenzung zu bestehenden Projekten

Das Toolkit dupliziert nicht den Funktionsumfang dieser Systeme. Es bietet eine vereinfachte, hardwareunabhängige Workflow- und Bedienebene über vorhandenen Steuerungen. Die immersive WebXR-Oberfläche ist der besondere Schwerpunkt.

| System | Was die Zielarchitektur daraus behält | Was sie nicht nachbaut |
| --- | --- | --- |
| NINA | Gerätesteuerung, Einzelbild, später Sequencer und Target Scheduler als externe Dienste | Eigene Kameratreiber und einen zweiten Capture-Stack |
| KStars/Ekos | Equipment-Profile, Zuordnung der Geräte, die Idee eines Setup-Assistenten | Eine eigene INDI-Steuerung |
| StellarMate | Installationsdiagnose, Web-Verwaltung, Rechnerkonfiguration | Ein eigenes Betriebssystem-Image. Profile werden hier nicht an zwei Stellen gepflegt |
| INDIGO | Trennung von Gerät, vermittelndem Dienst und Client | Eine neue universelle Treiberschicht |
| NINA.Polaris | Mehrere Rigs, Status vom Server, getrennte Aufnahmeverfahren, die Idee eines Simulationsbetriebs als spätere Referenz | Deren Capture-, Guiding- und Processing-Stack |

## 11. Ist-Zustand, Planung und Vision

Geplante Funktionen stehen hier nicht als implementiert.

### A — Implementiert und auf der Station gesehen

NINA-GOTO, STOP, Achsbewegung und Einzelbild. Sessions, Lights, Darks, Abdecken, Zurück und Wetterexport auf der Quest. Desktop und Quest am selben Server. Ein Aufnahmeauftrag, zweiter Start abgelehnt. SynScan nur als Prozessstart. PHD2 über den Event-Server. Rechnerwerte in `configs/mele.yaml`.

Die erste eigene Monitorfläche zeigt JPEG, RAW-Statistik und Histogramm. Das wurde auf der Quest gesehen, für ein einzelnes Light und beim Schließen der Session. Quelle ist `light_preview`. Eine Serie analysiert während des Laufs nichts.

v1.16 ist umgesetzt und geprüft: Kamera, Konfiguration, fünf Rezepte, Sessionzeile mit der zuletzt gespeicherten Belichtung, WORK-Transfer der MeLE-Station. Das PHD2-Kamerabild und der Leitstern auf der zweiten Monitorfläche sind auf der Quest bestätigt. LICHT und GUIDING schalten die Quelle um. Das Kamerabild schreibt höchstens alle 4 s. Mit diesem Abstand blieb PHD2 auf der Quest bedienbar. HFD und SNR unter dem Leitstern stammen aus dem letzten GuideStep und wurden während des Guidings gesehen.

Ausdehnung und Abstand stehen in der zweiten Spalte der Objektdetailseite. M31 bleibt ohne Abstand. Die Monitorgröße ist von der Tafel getrennt. Nach einem Katalog-GoTo bleibt die Objektseite offen. Die Guiding-Tafel neben KAMERA bedient PHD2 ohne Foto-Session. Belichtung, LOOP, AUTO STAR, GUIDE, PAUSE und STOP sind auf der Quest bestätigt.

### B — Konkret geplant

Das steht in der Roadmap und wird hier nicht erneut beauftragt. Das PHD2-Vollbild bleibt `save_image` auf eine temporäre FITS-Datei. Ein reines RAM-Vollbild gibt die PHD2-Schnittstelle nicht her. Der Mindestabstand ist 4 s, nur ein Bildbefehl gleichzeitig, die Uhr ab dem Schreibende, eigene Bildsperre neben der Socket-Sperre. Eine FWHM aus dem Sternprofil, eine Trennung von Seeing und Nachführfehler und Plate Solving ohne eigenen Montierungsbefehl kommen danach.

Alert-Zeile, Kalibrierschritt und der Button NEU liegen im Code. GUIDE kalibriert nur, wenn keine Kalibrierung vorliegt. NEU erzwingt eine neue am aktuellen Himmelspunkt, ohne Katalogkoordinate. Ein geeignetes Ziel nahe dem Himmelsäquator wählt der Beobachter. Diese Anzeige ist am späteren Abend des 16. Oktober 2026 wegen geschlossener Wolkendecke nicht geprüft.

Stationsprofil als Erweiterung der vorhandenen Equipment-Datei, mit Verweis auf die v1.16-Kamera. Steuerungshalter für Montierung und Kamera, bevor eine zweite Quest mitsteuert. Danach Planetenvideo als zweiter Adapter. Nachweis auf einem zweiten Windows-Rechner. Die bestehenden Sessions bleiben erhalten.

### C — Langfristige Vision

Virtuelle Kommandobrücke als Gestaltung der vorhandenen Szene. Maschinenraum mit dreidimensionaler Montierung und der Unterscheidung gemessen, berechnet, nicht verfügbar. Animierte Achsen aus Telemetrie. Professionelle GLB-Instrumente neben der bisherigen Tafel. Vollständige Mehr-Client-Steuerung mit Halter. Autonome Beobachtungsabläufe, NINA-Sequencer-Anbindung und eine nächtliche Warteschlange. Diagnoselauf, Backup und eine verallgemeinerte Installation.

## 12. Architektur-Checkliste

Vor einer größeren Erweiterung, etwa ASI585-Video, einer weiteren Montierung oder einer virtuellen 3D-Konsole, wird der Eingriff gegen diese Liste geprüft.

1. Entsteht eine neue Hardwareabhängigkeit?
2. Liegt diese Abhängigkeit in der Rechnerkonfiguration oder im Stationsprofil, statt im Quellcode?
3. Wird eine bereits vorhandene Datenquelle dupliziert?
4. Bleibt die Geräte-API unabhängig vom Frontend?
5. Bleiben Desktop und Quest mit denselben Serverfunktionen verträglich?
6. Werden mehrere Clients über denselben Auftrag und denselben Halter koordiniert?
7. Bleiben laufende Sessions und Aufnahmeaufträge konsistent, einschließlich der Trennung von Vorgaben und tatsächlichen Werten?
8. Ist die Funktion auf andere Hardware übertragbar, ohne den Anwendungscode zu ändern?
9. Kann ein späteres 3D-Instrument sie über den normalisierten Serverstatus und die bestehende API nutzen, ohne NINA oder PHD2 direkt anzusprechen?
10. Bleibt der bisherige, auf der Quest gesehene Funktionsumfang erhalten?

## Projektname

`app_mele` bleibt der technische Name. AstroBridge und AstroDeck sind Arbeitstitel für Plattform und Bedienoberfläche. Ein öffentlicher Produktname ist nicht festgelegt. Marke, Domain und Repositories sind nicht geprüft. Die Projektbeschreibung nennt eine eigenständige astronomische Software und keine offizielle Verbindung zu einem Science-Fiction-Franchise.
