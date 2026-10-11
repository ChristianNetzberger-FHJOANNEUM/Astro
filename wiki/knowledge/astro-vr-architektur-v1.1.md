# Astro-VR Architektur v1.1 — XR-8d Himmel

> Quelle: abgenommene Navigation in [v1.0](astro-vr-architektur-v1.0.md), Schalter aus dem [Panelkonzept v0.1](astro-vr-panelkonzept-v0.1.md)
> Stand: **Gebaut, Abnahme auf der Quest offen.** Nur `app_mele/vr.html`. Keine neue Route, kein Python, kein `pano.html`.

Das Himmel-Panel bleibt dieselbe Fläche. `ZURÜCK` führt zur Übersicht. Die Sechserliste unter OBJEKTE bleibt Gestirne und benannte Sterne.

Die Tafel ist standardmäßig 150 Prozent der bisherigen Größe, Schrift mit ihr. Unter EINSTELLUNGEN, Reiter BILD, steht `Tafel`. Der Bereich ist 100 bis 200 Prozent, Schritt 10. Der Wert liegt bei den übrigen Preferences.

## Anzeige

| Schalter | Standard | Wirkung |
|---|---|---|
| Sterne | EIN | `stars=1` oder `0` |
| Sternbilder | EIN | `const=1` oder `0`, Linien und Namen zusammen |
| Messier | AUS | `messier=1` oder `0` |
| Form | SCHEIBE | nur bei Messier EIN, kein neuer Abruf |
| Unruhe | AUS | nur bei Messier EIN, kein neuer Abruf |
| Grenzhelligkeit | 5,5 mag | `mag`, von 0 bis 9, Schritt 0,5 |

Die Grenzhelligkeit filtert Sterne. Messier bleibt unabhängig davon sichtbar. Der Server filtert Messier nicht nach Helligkeit, der Viewer auch nicht.

Weiterhin mitgeschickt: `lat`, `lon`, `planets=1`, `ngc=0`, und `stem`, wenn die Seite ihn hat.

## Zeit

Dieselbe Regel wie `btn-now` und das Live-Kästchen am Desktop.

| Bedienung | LIVE | Abruf |
|---|---|---|
| Start | EIN | ohne `when`, danach alle 15 Sekunden |
| LIVE AUS | AUS | kein neuer Abruf, der Takt stoppt, der letzte Zeitpunkt bleibt |
| JETZT | AUS | einmal mit dem aktuellen Zeitpunkt, der Takt bleibt aus |
| −1 h, +1 h, −1 d, +1 d | AUS | einmal mit dem verschobenen Zeitpunkt |
| LIVE EIN | EIN | sofort die aktuelle Zeit, der 15-Sekunden-Takt läuft wieder |

JETZT stellt den Himmel auf jetzt und lässt ihn dort stehen. LIVE EIN stellt ihn ebenfalls auf jetzt und schiebt ihn danach weiter. Ein laufender Abruf, der noch ohne festes `when` unterwegs war, wird nach LIVE AUS verworfen. Er darf die Uhr nicht zurückholen.

Oben im Panel steht der dargestellte Zeitpunkt und `Live` oder `fest`.

## Messier

`dso` aus `/sky-overlay` wird gelesen. Nur Einträge mit `kind=messier`. Sie liegen auf derselben Kugel wie die Sterne, mit demselben Azimut, derselben Höhe und derselben Norddrehung. Dazu die Katalognummer, zum Beispiel `M31`, etwas kleiner als ein Sternbildname. MESSIER AUS nimmt Zeichen und Nummern sofort weg. Steht im Panel `0 Messier`, hat die Antwort keine Objekte über dem Horizont geliefert.

`Form SCHEIBE` ist der Anfang: eine bernsteinfarbene Scheibe. `Form TYPEN` zeichnet dieselbe Liste neu, ohne `/sky-overlay`. Das Feld `type` wählt Silhouette und einen hellen Farbton. Fehlt der Typ, bleibt die bernsteinfarbene Scheibe. `Unruhe` steht daneben und ist zu Beginn aus. Eingeschaltet werden die Zeichen abwechselnd etwas kleiner und dunkler, jedes in eigenem Takt, etwa zweimal pro Sekunde. Sie wachsen nicht über die ruhige Größe hinaus. Die M-Nummern bleiben still. Ausgeschaltet ist das Bild wieder fest. Beides ohne neuen Abruf.

| Silhouette | Ton | Typen |
|---|---|---|
| Ellipse | blassblau | `G`, `GPair`, `GTrpl`, `GGroup` |
| Kern mit Hof | warmgelb | `GCl` |
| fünf Punkte | hellgelb | `OCl`, `*Ass`, `Cl+N` |
| Ring | blaugrün | `PN` |
| Wolke | rosa | `Neb`, `HII`, `EmN`, `RfN`, `DrkN`, `SNR` |
| Raute | hellgrau | jeder andere gelieferte Typ |

Für ein späteres NGC bleibt der Farbton billig, er ist nur ein Wert pro Punkt. Die Unruhe bleibt vertretbar, solange sie dieser eine Schalter im selben Shader ist und ausgeschaltet nichts kostet. Eine große NGC-Menge würde man auf der Quest mit eingeschalteter Unruhe noch einmal ansehen.

Die Kennung ist `messier` plus `id`. Im Katalog ist das `M` und die Nummer, zum Beispiel `M31`. Der Name kann einen Zusatz tragen, wenn der Katalog einen hat.

Das Telrad nimmt Messier nur auf, solange MESSIER EIN ist und das Objekt in der letzten gültigen Antwort steht. Der Server hat den Horizont schon angewendet. Winkel, Halten und Wechsel bleiben die Preferences: 0,25°, 0,40° und 0,08°. Liegen mehrere Objekte nah beieinander, gilt dieselbe Hysterese wie bei Sternen und Gestirnen. Das Schild am Telrad zeigt die gelieferte Bezeichnung.

Die Detailansicht zeigt nur, was die Antwort hat:

- Bezeichnung, das Feld `name` oder sonst `id`
- die Zeile Messier
- den Objekttyp, wenn `type` gefüllt ist
- RA, Dec, Azimut, Höhe
- die Helligkeit, wenn `mag` gefüllt ist, mit Band, wenn `mag_band` mitkommt

Die Sechserliste bekommt keine Messier-Zeile.

## Wenn ein Objekt verschwindet

Die gewählte Kennung bleibt. Ein neuer Abruf sucht dieselbe Kennung. Findet er sie, aktualisiert er die Zahlen. Findet er sie nicht, bleiben die letzten Zahlen und die Zeile „nicht mehr in der Liste“. Er wählt nicht das Nachbarobjekt.

Das gilt, wenn Messier ausgeschaltet wird, wenn ein Zeitsprung das Objekt unter den Horizont setzt, und wenn ein Abruf fehlschlägt. Ein Fehlschlag behält den letzten gezeichneten Himmel. Die Grenzhelligkeit nimmt ein Messier-Objekt nicht aus der Liste.

Eine Antwort, die zu älteren Schaltern oder zu einem älteren Zeitpunkt gehört, wird verworfen. Der 15-Sekunden-Takt startet keinen zweiten Abruf, solange einer läuft. Bei LIVE AUS gibt es keinen Takt und keine fortlaufende Uhr.

## Abnahme

1. HIMMEL öffnet sich aus der Übersicht.
2. Sterne ein und aus.
3. Sternbilder ein und aus, Linien und Namen zusammen.
4. MESSIER EIN zeigt bernsteinfarbene Scheiben und die M-Nummern. Die Zeile nennt die Anzahl. `Form TYPEN` wechselt auf Silhouetten und Farbtöne ohne neuen Abruf, `Form SCHEIBE` kehrt zu den bernsteinfarbenen Scheiben zurück. `Unruhe EIN` lässt die Zeichen leicht zittern, `Unruhe AUS` hält sie still. Beide Schalter erscheinen nur bei Messier EIN.
5. Das Telrad wählt ein Messier-Objekt.
6. Das Detail zeigt Bezeichnung, Typ soweit vorhanden, RA/Dec, Azimut/Höhe und Helligkeit soweit vorhanden.
7. Die Sechserliste bleibt ohne Messier.
8. Die Grenzhelligkeit ändert die Sterne.
9. Dieselbe Grenzhelligkeit lässt die Messier-Punkte und Nummern stehen.
10. Ein Zeitsprung ändert den Himmel.
11. Ein Zeitsprung schaltet LIVE aus.
12. Bei LIVE AUS bleibt der Zeitpunkt über mehr als 15 Sekunden.
13. JETZT zeigt den aktuellen Himmel und lässt LIVE aus. LIVE EIN zeigt ihn ebenfalls und lässt den Takt weiterlaufen.
14. ZURÜCK und das Ein- und Ausblenden bleiben.
15. Preferences und die Tastenbelegung bleiben.
16. Der Himmel bleibt flüssig. Ein fehlgeschlagener Abruf löscht ihn nicht.

Nicht in diesem Schritt: NGC, Gitter, Suche, Favoriten, Bahn, Montierung, GoTo, Aufnahme.

## Verwandte Seiten

- [Astro-VR Architektur v1.0](astro-vr-architektur-v1.0.md)
- [Astro-VR Panelkonzept v0.1](astro-vr-panelkonzept-v0.1.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
