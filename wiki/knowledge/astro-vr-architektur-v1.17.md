# Astro-VR Architektur v1.17 — Toolkit-Audit

> Quelle: Kamera und Rezept in [v1.16](astro-vr-architektur-v1.16.md)
> Stand: **15. Oktober 2026.** Prüfung des vorhandenen Codes. Keine Änderung an Diensten, Datenbank oder Oberfläche. Leitdokument: [Astro-Toolkit Roadmap v1](astro-toolkit-roadmap-v1.md).
> Fortschreibung: v1.16 ist seit dem 16. Oktober 2026 umgesetzt. Der aktuelle Stand steht in der Roadmap, später Abend desselben Tages. Diese Audit-Seite bleibt unverändert.

Ein generisches Toolkit für eine Windows-Beobachtungsstation kann aus `app_mele` entstehen. Ein Neubau ist nicht nötig. Die Anwendung spricht die Hardware schon über NINA, PHD2 und den Start von SynScan Pro. Was fehlt, ist die Trennung von Rechner, Gerätezusammenstellung, Aufnahmeverfahren und Session. Diese Trennung ist teilweise schon da und darf nicht durch ein zweites Profilmodell verdoppelt werden.

## Urteil

Die vorhandene Architektur wird inkrementell erweitert. Desktop und Quest benutzen denselben Prozess und dieselben Routen. Eine eigene Kameratreiberschicht entsteht nicht. Windows bleibt die Serverplattform. Der Beweis der Übertragbarkeit ist eine zweite Installation ohne Quellcodeänderung. Dieser Beweis liegt nicht vor.

## Ist-Zustand

| Bereich | Befund im Code |
| --- | --- |
| Desktop | Eine NiceGUI-App, Port aus `configs/mele.yaml`, Vorgabe 8082 |
| WebXR | Dieselbe App, Seite `/vr-view`. Quest 3 ist die geprüfte Oberfläche. Ein iPad ist ein Browser auf demselben Port, keine eigene App |
| NINA | Einzige Steuerung für GOTO, STOP, Achse und Einzelbild. `mele/nina.py` kennt die Advanced API, nicht ein Kameramodell |
| SynScan | Nur Prozessstart und Laufstatus. Kein eigener Montierungsbefehl |
| PHD2 | Event-Server, Host und Port aus der Konfiguration. Kein ZWO-Treiber in der App |
| Aufnahme | Ein Weg: `nina.capture` für Einzelbilder. Kein Videoadapter |
| Profile | Drei getrennte Bestände, siehe unten |
| Auftragssperre | Ein Aufnahmeauftrag je Prozess. Ein zweiter Start liefert 409 |
| Montierungssperre | Kopplung für die Quest. Der lokale Desktop darf ohne diese Kopplung steuern. Mehrere gekoppelte Clients können gleichzeitig befehlen |
| Installation | Skripte unter `deployment/windows` für diesen Rechner: Pfade `C:\Astro`, `C:\Caddy`, Konto, DNS-Adresse, Technitium |

`configs/mele.yaml` ist bereits die Rechnerkonfiguration. Sie enthält Port, Datenbank, Aufnahme- und Archivpfade, NINA-Adresse, Programmdateien, PHD2, Wetterserver und die Standortkoordinaten. Die Vorgaben in `mele/config.py` zeigen auf dieselben Windows-Pfade, falls die Datei einen Wert auslässt.

## Drei Bestände, die nicht verschmolzen werden

1. `imaging_profiles` in `astro_manager.sqlite`: objektgebundene Aufnahmewerte. v1.16 löst sie in Kamera, Kamerakonfiguration und Aufnahmerezept auf. Belichtung und ISO gehören dorthin, nicht in ein Stationsprofil.
2. `data/horizon/equipment-profiles.json` über `mele/equipment_profiles.py`: Montierung, Aufnahmeoptik, Guiding-Kamera, Guidescope, PHD2-Profil und ein Maßstab aus Brennweite und Pixelgröße. Das ist der Kern eines Observatory Profile, noch ohne Hauptkamera, ohne Fähigkeiten und ohne Standort.
3. `wiki/inventar/components.yaml`: Okulare, Flattener und das Lacerta 80/500. Das ist ein Inventar, keine laufende Konfiguration.

`sessions.equipment_profile_id` ist ein leeres Textfeld und wird nicht zum Schlüssel eines neuen Profils.

Ein Observatory Profile verweist auf diese Bestände. Es speichert nicht noch einmal ISO, Gain oder Belichtung. Eine Zeile nennt die aktive Zusammenstellung: Montierung, Optik, Hauptkamera aus v1.16, Guider, PHD2-Profil, Standort und welche Aufnahmeart die Hauptkamera gerade fährt. Beziehungen sind Verweise, keine freien Textfelder. Bildfeld entsteht aus Brennweite der Optik und der Sensordaten der gewählten Kamera.

## Fähigkeiten

ISO-Stufen kommen heute aus der Gain-Liste, die NINA für die verbundene Kamera meldet. Eine Liste mit mindestens zwei Werten wird als ISO angeboten. Das passt zur Lumix S5IIX, weil deren Treiber die ISO-Werte unter Gains ablegt. Eine ASI585 mit einer echten Gain-Liste würde in derselben Oberfläche als ISO erscheinen. Kühlung, ROI, Binning als Fähigkeit und Video sind nicht beschrieben. Plate Solving ist in `nina.py` ausgeschaltet: `center` und `rotate` bleiben falsch.

Die Fähigkeit gehört zur Kamerazeile aus v1.16: `iso`, `gain`, `offset`, `cooling`, `roi`, `binning`, `still`, `video`. Die Oberfläche fragt diese Fähigkeiten. Sie fragt nicht den Kameranamen.

Einzelbild und Planetenvideo bleiben zwei Aufnahmeverfahren hinter derselben Session. `NinaStillCapture` ist der heutige Aufruf `nina.capture`. `PlanetaryVideoCapture` kommt erst, wenn die ASI585 diesen Weg wirklich braucht. Bis dahin bleibt der Einzelbildweg unverändert.

## Mehrbenutzer

Lesen dürfen Desktop und Quest parallel. Schreiben einer Aufnahme ist auf einen Auftrag begrenzt. Die Montierung hat diese Grenze nicht. Jede erfolgreiche Kopplung legt eine weitere Sitzung an. Der Browser auf dem Rechner selbst gilt als Desktop und braucht keinen Code. Zwei Quests und der Desktop können sich bei GOTO und Achse widersprechen. Eine Quest 2 als zweite Bedienstelle braucht vor dem ersten gemeinsamen Betrieb eine serverseitige Verriegelung: ein Halter für Montierung und Kamera, weitere Clients lesen. Rollen und eine Benutzerverwaltung sind dafür nicht der erste Schritt.

## Deployment und Portabilität

Übertragbar ohne Quellcodeänderung sind der Python-Prozess, `mele.yaml`, die NINA-Adresse und der PHD2-Port, sobald NINA, PHD2 und die Treiber auf dem Zielrechner stehen. Nicht übertragbar ohne Anpassung sind die Windows-Aufgaben, Caddy, das Zertifikat, Technitium, die festen Programmverzeichnisse und die Notebook-Freigabe in der YAML. Ein Installer, der Treiber oder NINA still verändert, entsteht nicht. Ein Diagnoselauf prüft später Erreichbarkeit von NINA, PHD2, Datenbank, Aufnahmeordner und HTTPS und ändert dabei nichts.

Der Server bleibt Windows. Die Clients sind Browser. Einzelne Sperren kennen schon eine nicht-Windows-Variante. Programmstart, Aufgabenplanung und Caddy sind Windows.

`app_astro` auf Port 8081 ist der ältere Katalog- und Importweg. Er ist nicht der Beobachtungsserver und wird nicht in dieses Toolkit gezogen.

## Reihenfolge

Die Tabelle ist die Reihenfolge des Audits vom 15. Oktober 2026. v1.16 ist seit dem 16. Oktober umgesetzt. Der aktuelle Stand steht in der Roadmap.

| Schritt | Inhalt | Eingriff |
| --- | --- | --- |
| Erledigt | Dieses Audit | Keiner |
| v1.16 | Kamera, Konfiguration, Rezept. Fähigkeiten an der Kamera, nicht am Namen | Mittel, erst nach Freigabe des Entwurfs |
| Danach | Observatory Profile als Verweis auf Optik, Montierung, Guider und die v1.16-Kamera. `equipment-profiles.json` wird erweitert, nicht ersetzt | Mittel |
| Vor einer zweiten Quest als Steuerung | Ein Halter für Montierung und Kamera | Mittel |
| Mit der ASI585-Videoaufnahme | Zweites Aufnahmeverfahren neben `nina.capture` | Mittel |
| Beweis | Zweiter Windows-Rechner, andere YAML, dasselbe Frontend, eine Aufnahme | Mittel bis größer. Kein Installer vorher |

Ein Redesign ist nicht erforderlich.
