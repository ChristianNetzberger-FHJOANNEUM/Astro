# Astro-VR Panelkonzept v0.1 — XR-8b

> Quelle: [Desktop-Inventar v0.1](astro-vr-desktop-inventar-v0.1.md), abgenommenes Dashboard aus [v0.9](astro-vr-architektur-v0.9.md)
> Stand: **Für XR-8c freigegeben, XR-8c abgenommen.** Die Himmel-Schalter sind in [v1.1](astro-vr-architektur-v1.1.md) gebaut und auf der Quest bestätigt. Die persönliche NGC-Auswahl ist [v1.2](astro-vr-architektur-v1.2.md).

Die Quest bleibt der astronomische Viewer. Geräteverwaltung, Guiding, SynScan und die Session-Formulare bleiben in der MeLE-App. `pano.html` wird nicht nachgebaut.

Ein Dashboard, eine Gruppe zur Zeit. Kein zweites schwebendes Fenster. Breite 0,68 m, 1,75 m vor dem Blick beim Einblenden, danach weltfest. Die Höhe ist 0,44 m, der Zusatz liegt unten, damit ZURÜCK die NGC-Bewertung nicht überdeckt. Strahl, `select`, `squeeze`, Ein- und Ausblenden und die Preferences bleiben.

## Sechs Bereiche, zwei Ebenen

Sechs Reiter in einer Zeile sind zu schmal. Die vier Reiter der Preferences sind auf der Quest getroffen worden, bei etwa 0,13 m Breite. Sechs Beschriftungen dieser Art unterschreiten das.

Die Übersicht ist deshalb ein Menü aus großen Flächen, nicht aus Reitern. Zwei Spalten, drei Zeilen, jede Fläche etwa 0,30 m × 0,05 m. Das ist gröber als die Objektzeilen, die schon funktioniert haben.

| | |
|---|---|
| OBJEKTE | HIMMEL |
| BEOBACHTUNG | MONTIERUNG |
| AUFNAHME | EINSTELLUNGEN |

Eine Gruppe füllt dasselbe Panel. Oben steht ihr Name, unten `ZURÜCK` zur Übersicht. `EINSTELLUNGEN` ist das vorhandene Preferences-Panel mit seinen vier Reitern. `OBJEKTE` ist die vorhandene Liste und das Detail.

Die drei späteren Gruppen bekommen keinen toten Knopf, solange sie nichts tun. Jede sichtbare Fläche muss eine Wirkung haben. Die Plätze sind reserviert und erscheinen erst in ihrer Phase. Das ist die Empfehlung. Offen bleibt, ob die Übersicht die drei Namen schon zeigt und nur „später“ sagt.

## Navigation

- Der Abzug auf leere Fläche blendet das Panel aus und wieder ein, wie bisher. Ausblenden vergisst die Gruppe. Einblenden zeigt die Übersicht, nicht die zuletzt offene Gruppe. Das ist das schon abgenommene Verhalten und bleibt.
- `ZURÜCK` geht eine Stufe: vom Detail zur Objektliste, von der Liste zur Übersicht, vom Himmel zur Übersicht, von einem Preferences-Reiter nicht erst durch alle Reiter, sondern mit `FERTIG` zur Übersicht.
- Solange das Panel offen bleibt, merkt es sich die Gruppe. Wählt das Telrad ein Objekt, öffnet sich dessen Detail. `ZURÜCK` kehrt in die Gruppe davor, nicht pauschal in die Objektliste. War das Panel zu, stellt das Telrad es vor den Blick und zeigt das Detail. Der nächste Abzug daneben schließt. Danach kommt die Übersicht.
- `OBJEKTE` bleibt erreichbar. Die Liste hat weiter höchstens sechs Zeilen. Längere Treffer, später bei der Suche, blättern mit `Weiter` und `Zurück`. Es gibt keine Scrollfläche.
- Status, LED und ein späterer Lauftext ersetzen den Inhalt der Gruppe. Sie erzeugen kein zweiten Panel.
- Läuft später ein Slew, liegt `STOP` in jeder Gruppe an derselben Stelle, nicht nur unter MONTIERUNG. Sonst ist er unsichtbar, während man den Himmel ansieht. Dasselbe gilt später für den Abbruch eines Capture-Laufs. Beides ist noch nicht zu bauen.

## Was wohin gehört

Nur Inventar-IDs, die es wirklich gibt. P-61, die tote Imaging-Kopie, Guiding, SynScan und die App-Leiste kommen nicht ins Menü.

| Gruppe | Jetzt | Später, nachgewiesen | Nicht hier |
|---|---|---|---|
| OBJEKTE | P-33 und P-34, schon auf der Quest, eingeschränkt auf benannte Sterne und Gestirne | P-30 Suche, P-31 Favoriten. Messier aus dem Telrad, sobald er gezeichnet wird | Formulare |
| HIMMEL | P-10, P-11, P-14, P-17, fest verdrahtet | P-12 Messier, P-15 Grenzhelligkeit, P-18 Zeitpunkt. Danach P-13 NGC, P-16 DSO-Typen, P-21 Gitter, P-03 Textur, P-20 Sterngröße | P-50 Schattenlinie, P-51 Punktwolke |
| BEOBACHTUNG | — | P-35 Tagesbahn, P-32 Tonight. P-02 Almanach erst, wenn diese Seite selbst zerlegt ist | Listen speichern |
| MONTIERUNG | — | P-40 Status, nur lesend. Danach P-41 GoTo zweistufig, P-42 STOP, P-44 Log hängt am GoTo | P-43 Spur, P-45 Achsen |
| AUFNAHME | — | eine Statuszeile zu NINA und zum Lauf. IMG-04 Capture zuletzt | IMG-02, IMG-03, IMG-05 bis IMG-10, P-60 als zweites Fenster |
| EINSTELLUNGEN | die Preferences aus v0.9 | P-71 WLAN als eine Zeile, wenn die Route einzeln freigegeben ist | P-19 als freies Zahlenfeld, P-70 auf dem MeLE, P-01 |

## HIMMEL, erster Ausbau

Die Quest ruft `/sky-overlay` ohne `when`, mit `stars=1`, `const=1`, `messier=0`, `ngc=0`, `planets=1`, `mag=5.5`. Fehlt `when`, setzt die App die aktuelle Uhrzeit. `dso` kommt in der Antwort vor. `vr.html` liest das Feld nicht.

| Schalter | Route heute | Was der Viewer noch nicht tut | Erster Schritt |
|---|---|---|---|
| Sterne | `stars` | immer an | ja |
| Sternbilder | `const` | immer an. Linienenden laden intern bis mag 6,5, auch wenn die gezeichneten Sterne bei 5,5 bleiben | ja |
| Messier | `messier` | immer 0. Die Objekte liegen in `dso`, nicht bei den Sternen. Die Grenzhelligkeit filtert sie nicht. Über dem Horizont sind es höchstens die 110 Messier-Objekte | ja, zeichnen |
| Grenzhelligkeit | `mag` | fest 5,5. Wirkt auf Sterne, nicht auf Messier | ja, Schritte wie am Desktop, 0 bis 9, Schritt 0,5 |
| Mond und Planeten | `planets` | immer an | an lassen. Ein Schalter ist keine neue Route, aber nicht die erste Reihe |
| Live und Zeitpunkt | `when` | der 15-Sekunden-Takt lässt `when` weg und springt damit immer auf jetzt | ja |
| NGC, DSO-Typen, Gitter | `ngc`, `dso_types`, Browser | NGC kann die Antwort schwer machen. Gitter sind lokal | nicht im ersten Schritt |

Zeitregel, dieselbe wie am Desktop:

- Live ist zu Beginn an. Alle 15 Sekunden ein Abruf ohne festes `when`.
- `+1h`, `-1h`, `+1d`, `-1d` schalten Live aus, merken den neuen Zeitpunkt und laden einmal mit diesem `when`.
- Solange Live aus ist, läuft der Takt nicht. Er darf den gemerkten Zeitpunkt nicht durch die Uhr ersetzen.
- `JETZT` setzt den Zeitpunkt auf jetzt, schaltet Live aus und lädt einmal. Der Takt bleibt aus. Das ist `btn-now` am Desktop. LIVE EIN setzt den Zeitpunkt auf jetzt, lädt sofort und startet den Takt.
- Live aus ohne Sprung friert den letzten geladenen Stand ein.
- Eine ältere Antwort, die nach einem Sprung noch eintrifft, wird verworfen.

Messier wird gezeichnet, sonst ist der Schalter blind. Das Telrad darf sie in demselben Schritt wählen, mit der vorhandenen Hysterese und dem vorhandenen Detail. Sonst zeigt der Himmel Objekte, die der Strahl nicht trifft. Die Sechserliste unter OBJEKTE bleibt benannte Sterne und Gestirne. Ein Messier-Objekt kommt über das Telrad, nicht indem es einen Stern aus der Liste verdrängt.

Sterne aus und Sternbilder an ist erlaubt. Die Linien bleiben. Beide aus macht die Antwort leichter. Ein fehlgeschlagener Abruf behält den letzten Himmel.

Die letzte kalte Katalogantwort mit Sternen und Linien lag bei etwa zehn Sekunden. Messier ist dagegen klein. Der erste Quest-Test soll trotzdem prüfen, ob der Takt sich überlappt. `skyLoading` lässt einen zweiten Abruf aus, das bleibt.

## Schnitt und Sicherheit

Keine pauschale Freigabe von `/nina`, `/astro` oder `/catalog`. Jede Zeile ist ein einzelner Pfad, später und einzeln entschieden.

| Gruppe | Art | Erreichbar auf 8443 | Freigabe | Lesen | Daten | Gerät |
|---|---|---|---|---|---|---|
| Übersicht, Navigation, Telrad, Preferences | Browser | ja, die Seite selbst | nein | — | `localStorage` im Headset | nein |
| HIMMEL, OBJEKTE aus dem Overlay | `/sky-overlay` | ja | nein | ja | nein | nein |
| Suche | `GET /catalog/search`, `GET /catalog/resolve` | nein | nur diese zwei Pfade, später | ja | nein | nein |
| Favoriten | `/catalog/favorites` | nein | eigener Beschluss | ja | ja | nein |
| Tonight | `GET /observe/tonight/markers` | nein | ein Pfad | ja | nein | nein |
| Tagesbahn | `GET /sky-track` | nein | ein Pfad | ja | nein | nein |
| Almanach-Seite | `/observe-view` und weitere Observe-Routen | nein | nicht im Viewer | — | — | nein |
| Mount-Status | `GET /nina/mount` | nein | nur dieser Pfad | ja | nein | nein |
| WLAN | `GET /network/wifi` | nein | ein Pfad | ja | nein | nein |
| GoTo | `POST /nina/mount/slew` | nein | erst nach der Sperre | — | Log `POST /nina/goto-log` | ja |
| STOP | `POST /nina/mount/slew/stop` | nein | zusammen mit GoTo | — | — | ja |
| Capture | `POST /astro/nina/capture`, `GET /nina/camera` | nein | zuletzt, einzeln | Phase | Session | ja |

GoTo bleibt zweistufig: wählen, dann ausdrücklich bestätigen. `STOP` ist kein Eintrag in einem Untermenü, sobald ein Slew läuft.

`POST /nina/mount/slew` prüft RA/Dec, ob NINA da ist, ob die Montierung connected und nicht parked ist. Eine Sperre gegen einen zweiten Client steht in der Route nicht. Sie ist Voraussetzung, bevor ein GoTo aus der Quest gebaut wird. Bis dahin kein Schwenk aus dem Viewer.

## Phasen

Jede Phase ist ein eigener Quest-Test. Die spätere ersetzt die frühere nicht.

1. **Navigation.** Übersicht mit OBJEKTE, HIMMEL und EINSTELLUNGEN. HIMMEL zeigt erst nur den festen Stand, ohne neue Schalter, oder die Schalter kommen in Phase 2. `ZURÜCK` und `FERTIG` landen auf der Übersicht. Telrad öffnet das Detail und kehrt zurück. Abzug daneben schließt. Neu eingeblendet ist die Übersicht. Liste und Preferences tun dasselbe wie nach v0.9.
2. **HIMMEL.** Sterne, Sternbilder, Messier, Grenzhelligkeit, Live, Zeitsprung, `Jetzt`. Live aus hält den Zeitpunkt über mehr als eine Minute. Messier ist sichtbar und mit dem Telrad wählbar. NGC bleibt aus. Der Himmel bleibt flüssig, ein fehlgeschlagener Abruf löscht ihn nicht.
3. **Objekte, soweit die Daten schon da sind.** Messier-Detail bleibt. Die Sechserliste bleibt. Suche und Favoriten warten auf eine einzelne Pfadfreigabe und sind nicht Teil dieses Tests.
4. **Suche**, erst nach Freigabe von `/catalog/search` und `/catalog/resolve`. Blättern statt Scrollen. Kein Schreibzugriff.
5. **Beobachtung**, erst nach Freigabe von `/sky-track` und, getrennt, `/observe/tonight/markers`. Bahn und Fenster als Text in der Gruppe. Kein Almanach-Fenster.
6. **Mount-Status**, erst nach Freigabe von `GET /nina/mount`. LED und die bekannten Zeilen. Kein GoTo, kein STOP, der nichts zu stoppen hat.
7. **GoTo und STOP**, erst wenn die Mehrclient-Sperre existiert und ausdrücklich freigegeben ist. Zwei Stufen. `STOP` in jeder Gruppe, solange der Slew läuft.
8. **Aufnahme**, zuletzt. Zuerst eine Statuszeile, Capture erst nach eigenem Beschluss. Kein Session-Formular, kein zweites Fenster, kein Schieben von Dateien.

Phase 3 steht vor der Suche, weil sie keine neue Route braucht. Das ist die Korrektur an der gewünschten Reihenfolge. Suche, Bahn und Mount-Status tauschen sich nicht untereinander vor: sie hängen an verschiedenen Freigaben und können warten, ohne sich zu blockieren.

## Offene Entscheidungen

1. Entschieden: die drei späteren Gruppen erscheinen erst mit ihrer Phase. XR-8c zeigt sie nicht.
2. Entschieden: Navigation ist XR-8c, die Himmel-Schalter sind XR-8d.
3. Entschieden und in v1.1 gebaut: das Telrad wählt Messier im selben Schritt. Die Sechserliste bleibt.
4. Entschieden und in v1.1 gebaut: Live aus schaltet den Takt ab. Er lädt den eingefrorenen Zeitpunkt nicht erneut.
5. Die Mehrclient-Sperre ist nicht entworfen. Ohne sie gibt es kein GoTo aus der Quest.

## Verwandte Seiten

- [Astro-VR Desktop-Inventar v0.1](astro-vr-desktop-inventar-v0.1.md)
- [Astro-VR Architektur v0.9](astro-vr-architektur-v0.9.md)
- [Astro-VR Architektur v1.1](astro-vr-architektur-v1.1.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
