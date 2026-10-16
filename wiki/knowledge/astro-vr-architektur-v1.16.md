# Astro-VR Architektur v1.16 — Kamera und Rezept

> Quelle: Sessionansicht in [v1.15](astro-vr-architektur-v1.15.md)
> Stand: **16. Oktober 2026.** Umgesetzt und geprüft. Quest: Auswahl, Belichtung, ISO, Vorschaubild. Desktop: Session, Rezept, Lights, Darks, Wetter, Vorschau und WORK-Transfer nach gespeicherter Windows-Anmeldung. Eine geänderte Belichtung gilt für die weiteren Aufnahmen. Die Sessionzeile zeigt den letzten gespeicherten Wert, jede Datei behält ihre eigene Belichtung, das Rezept bleibt. Langfristiges Ziel: [v1.17](astro-vr-architektur-v1.17.md).

Ein Profil gehört heute zu einem Katalogobjekt. Kamera und Belichtungsrezept liegen in demselben Datensatz. Wiederverwendbar werden eine Kamerakonfiguration und ein Aufnahmerezept. Die Session kopiert deren Ausgangswerte und gehört weiter zu einem Objekt.

## Auswertung der neun Profile

Alle neun Zeilen in `imaging_profiles` nennen die Ausrüstung `Lumix S5IIX`. ISO ist überall 640. Binning ist überall `1x1`. Der Filter ist leer. Offset ist 0 oder leer. Eine ASI585 kommt nicht vor.

Unterscheidend ist die Belichtung: 2 s, 5 s, 6 s, 10 s und 20 s. Die Bildanzahl ist achtmal 1 und einmal 10, bei M33. Gain ist 1, 2, 22 oder leer und folgt nicht der Belichtung. Bei der Lumix ist die Empfindlichkeit der ISO-Wert. Gain eignet sich nicht als eigene Konfiguration.

| Belichtung | Profile | Bildanzahl |
| --- | --- | --- |
| 2 s | M2 | 1 |
| 5 s | HIP97649, Saturn, M57 | 1 |
| 6 s | HIP108612 | 1 |
| 10 s | HIP11767, M33 | 1 und 10 |
| 20 s | M31, M13 | 1 |

Daraus werden keine neun Kamerakonfigurationen. Es reicht eine Kamera Lumix S5IIX und eine Konfiguration mit ISO 640 und Binning 1×1. Die Namen bezeichnen die Belichtungsgruppe. Sie sind keine Aussage über die astronomische Eignung.

Jedes Rezept hat genau eine Belichtung. 5 s und 6 s sind zwei Rezepte.

| Rezept | Belichtung | Bisherige Profile |
| --- | --- | --- |
| Kurz – 2 s | 2 s | M2 |
| Mittel – 5 s | 5 s | HIP97649, Saturn, M57 |
| Mittel – 6 s | 6 s | HIP108612 |
| Standard – 10 s | 10 s | HIP11767, M33 |
| Lang – 20 s | 20 s | M31, M13 |

Die Bildanzahl der neun Profile geht nicht in diese Rezepte. Acht Profile haben 1 Bild, M33 hat 10. Die Bildanzahl setzt die Session oder der Auftrag. Die neun Zeilen bleiben bestehen, bis die Vorlagen angelegt und geprüft sind. Sessions, die auf sie zeigen, werden nicht umgeschrieben. 55 Sessions verweisen auf eines der neun Profile, 11 auf keines.

## Tabellen

`astro_manager.sqlite` bleibt die einzige Datenbank. `imaging_profiles` und `sessions.profile_id` bleiben. `sessions.equipment_profile_id` ist ein leeres Textfeld aus einer älteren Vorbereitung und wird nicht zur Fremdschlüsselspalte umgedeutet.

Neu, erst bei einer späteren Migration:

| Tabelle | Inhalt | Verbindung |
| --- | --- | --- |
| `cameras` | Name, Treiberhinweis, Aufnahmeart `still` oder `video`, Fähigkeiten ISO, Gain, Offset, ROI, Kühlung | keine Objektbindung |
| `camera_configs` | ISO oder Gain, Offset, Binning, ROI, Kühlung, Auslesemodus | gehört zu einer Kamera |
| `capture_recipes` | Name, Belichtung, Bildanzahl, Bildtyp, Aufnahmeart | keine Kamera und kein Objekt |

`sessions` hat die Kopierfelder bereits: Belichtung, Gain, ISO, Offset, Binning, Filter, Ausrüstung, Bildzahlen. Später kommen zwei leere Verweise dazu, `camera_config_id` und `recipe_id`. `profile_id` bleibt für die alten Zeilen.

Ein Aufnahmeauftrag lebt heute nur im Prozess. Dauerhaft liegen Belichtung und Dateiname schon je Bild in `capture-timing.json`. ISO steht in der RW2. Eine Tabelle `capture_runs` wird erst nötig, wenn die Oberfläche mehrere Aufträge einer Session zeigen soll, ohne diese Dateien zu lesen. Sie würde Session, Belichtung, Gain, ISO, Bildtyp, Bildanzahl und Zeitpunkt festhalten und die Session danach nicht überschreiben.

## Beziehungen

Eine Kamera hat mehrere Konfigurationen. Ein Rezept steht für sich. Eine neue Session kopiert die Ausgangswerte. Danach kann die Belichtung dieser Session geändert werden. Die Sessionzeile und das Formular zeigen den zuletzt gespeicherten Wert. Weitere Aufnahmen verwenden ihn. Jede Datei behält die Belichtung in ihrem Namen. Das Rezept bleibt unverändert.

Planetenvideo und Deep-Sky-Einzelbild sind zwei Aufnahmearten. Der bestehende NINA-Weg schreibt Einzelbilder. Ein Videorezept darf diesen Weg nicht benutzen, auch wenn die Tabelle es schon benennen kann.

## API, Desktop, Quest

Lesen, später: Kameras, Konfigurationen und Rezepte aus derselben Datenbank. Anlegen einer Session akzeptiert weiterhin `profile_id`. Zusätzlich können Konfiguration und Rezept angegeben werden. Der Server kopiert dann die Ausgangswerte. Pfade schickt die Quest nicht.

Vor dem Start vergleicht der Server die verbundene NINA-Kamera mit der gewählten Konfiguration. Sie muss passen. Ein stiller Wechsel der Kamera in NINA findet nicht statt. Ohne ausdrückliche Bestätigung wird der Start abgelehnt.

Die Quest wählt bei einer neuen Session Konfiguration und Rezept, in zwei Listen auf der vorhandenen Tafel. Sie legt keine Vorlagen an. Die abgenommenen Abläufe für GOTO, Lights, Darks, STOP, Zurück und Wetter bleiben, solange die neuen Felder leer sein dürfen. `PROFIL` bleibt bis zur Migration der Knopf für das alte objektgebundene Profil.

Der Desktop bearbeitet Konfigurationen und Rezepte. Die Sessionzeile zeigt den zuletzt gespeicherten Wert. Die Dateinamen der Aufnahmen behalten die jeweils verwendete Belichtung.

## Migration, später

1. Die drei Tabellen leer anlegen. Bestehende Zeilen nicht ändern.
2. Eine Kamera Lumix S5IIX und eine Konfiguration ISO 640, Binning 1×1 einsetzen.
3. Die fünf Rezepte anlegen: Kurz – 2 s, Mittel – 5 s, Mittel – 6 s, Standard – 10 s, Lang – 20 s. Jedes mit seiner einen Belichtung. Die Bildanzahl der alten Profile nicht übernehmen. Nur neue Sessions verweisen darauf.
4. `imaging_profiles` als bisherig stehen lassen. Nichts löschen und nichts als veraltet markieren, bevor eine neue Session mit Konfiguration und Rezept auf Quest und Desktop geprüft ist.
5. Alte Sessions behalten `profile_id` und ihre kopierten Zahlen, auch wo Belichtung und ISO leer sind.

Die leeren Quest-Sessions bekommen ihre Zahlen nicht durch Überschreiben mit einem späteren Auftrag. Die Session speichert die gewählte Vorlage. Jeder Auftrag speichert seine eigenen Werte.
