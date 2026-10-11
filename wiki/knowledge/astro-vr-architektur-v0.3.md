# Astro-VR Architektur v0.3 — XR-6b Sternbilder und Beschriftungen

> Quelle: Abnahme von [v0.2](astro-vr-architektur-v0.2.md) plus die Prüfung vom 2026-10-11
> Stand: **Auf der Quest gesehen, 2026-10-11.** Sternbilder sind gut erkennbar, die Namen lesbar und drehen bei Kopfneigung mit. Die Linien sind nicht zu dominant. Deckkraft 0,85 und Schildhöhe 7 bleiben. Linien durch Baum oder Haus bleiben die bekannte Grenze.

[v0.1](astro-vr-architektur-v0.1.md) und [v0.2](astro-vr-architektur-v0.2.md) bleiben gültig. Python bleibt die astronomische Quelle. `GET /sky-overlay` bleibt die einzige Datenroute. Die [Quest-Roadmap](quest3-xr-roadmap.md) bleibt. Keine neue Bibliothek, keine zweite Rechnung, keine Änderung an GoTo, NINA oder der Mehrclient-Logik.

## 1. Ziel

Der immersive Himmel bekommt die Sternbildlinien und die deutschen Sternbildnamen. Die Sterne bis mag 5,5, der 15-Sekunden-Takt und die Nordkopplung an das Gartenfoto bleiben.

## 2. Daten

Dieselbe Anfrage wie in XR-6a, zusätzlich `const=1`. Sterne, Messier, NGC und Planeten bleiben bei `stars=1` und den übrigen Schaltern 0. Grenzhelligkeit der gezeichneten Sterne bleibt 5,5.

| Feld | Inhalt |
|---|---|
| `lines[]` | `iau`, `az1`, `alt1`, `az2`, `alt2` |
| `labels[]` | `iau`, `name`, `az`, `alt` |

Python benutzt für die Linienenden intern Sterne bis mag 6,5. Diese Sterne stehen nicht in `stars` und werden nicht gezeichnet. Ein Segment entfällt nur, wenn beide Enden unter dem Gartenprofil liegen. Der Name ist der Katalogname, ASCII, zum Beispiel `Baerenhueter`. Die Mittelposition rechnet Python. JavaScript bildet sie nicht nach.

## 3. Linien

Ein `THREE.LineSegments` in der Himmelsgruppe. Dieselbe `azAltToVec`-Formel wie die Sternpunkte, Radius 478 wie auf dem Desktop. Farbe und Deckkraft wie die Desktop-Linien (`0x7dd3fc`, Deckkraft etwa 0,85). Kein Großkreis, keine eigene Horizontschneidung, keine zweite Linienbibliothek.

## 4. Beschriftungen

Die HTML-Schilder aus `pano.html` gibt es im Headset nicht. Jeder Name ist ein Sprite in der Himmelsgruppe, an `az`/`alt` aus `labels`, Radius knapp innerhalb der Linien. Das Sprite dreht sich zur Kamera, auch bei Kopfneigung. Das ist dasselbe Verhalten wie die früheren Schilder von Polaris und Vega.

Die Schrift ist klein und kontrastreich. Der Text kommt unverändert aus `name`. Lange Namen wie `Haar der Berenike` müssen in die Textur passen. Unicode-Umschreibung ist nicht Teil dieser Phase. Kein Anklicken, kein Informationspanel.

## 5. Himmelsgruppe

Sterne, Linien und Schilder liegen in einer Gruppe. Diese Gruppe ist Kind der bestehenden Panoramakugel und übernimmt deren Drehung. Das Gartenfoto bleibt Geschwister in derselben Kugel. Kein neues Framework, keine Aufteilung in Dateien, keine leeren Interaktions- oder Dashboard-Gruppen.

## 6. Takt

Alle 15 Sekunden eine Antwort. Erst nach erfolgreichem JSON werden Punkte, Linien und Schilder gemeinsam ersetzt. Vorher aufgebaute Objekte, Geometrien, Materialien und Texturen werden freigegeben. Schlägt der Abruf fehl oder kommt `error`, bleibt der letzte Himmel stehen. Die Statuszeile nennt den Fehler. Der Renderloop läuft weiter. Kein Rechnen und kein Neubau im Animationsframe. Kein Abruf, solange die Seite verborgen ist oder kein Panorama geladen ist.

## 7. Bekannte Einschränkung

Schneidet ein Segment den Gartenhorizont, kann die Linie durch Baum oder Gebäude sichtbar bleiben. Dasselbe gilt auf dem Desktop. XR-6b übernimmt das. Eine genauere Begrenzung oder Maske ist eine spätere Verbesserung und wird jetzt nicht gebaut.

## 8. Grenzen

Nur `app_mele/vr.html`. Unverändert bleiben `mele/sky.py`, `mele/catalog.py`, `mele/ephemeris.py`, `pano.html`, die Datenbank, Caddy, die Aufgabenplanung, NINA, SynScan und die Mehrclient-Koordination. `/sky-overlay` ist auf Port 8443 schon freigegeben. `const=1` ist ein Query-Parameter derselben Route.

Die laufende App liest `vr.html` beim Prozessstart. Eine spätere Umsetzung ist erst nach Neustart von `mele_app` sichtbar.

## 9. Prüfung, ob die Umsetzung klein bleibt

Ja. `loadSky` holt heute `const=0` und `showStars` ersetzt nur die Punktwolke als Kind von `sphere`. Die Norddrehung sitzt schon auf dieser Gruppe. Für XR-6b kommen dazu eine Himmelsgruppe, `const=1`, ein Linienobjekt und die Sprites. Die Abfrage, der Fehlerpfad und der 15-Sekunden-Takt bleiben.

Risiken, keine Gründe für eine größere Architektur:

- WebGL zeichnet Linien einen Pixel breit. Auf der Quest können sie dünn wirken. Keine neue Linienbibliothek. Die Abnahme prüft, ob sie neben den Sternen noch erkennbar sind.
- Etwa ein Schild pro sichtbarem Sternbild, höchstens die 88 IAU-Felder. Der Neubau passiert alle 15 Sekunden, nicht pro Frame. Three.js richtet das Sprite pro Auge aus. `projectLabels` aus dem Desktop wird nicht übernommen.
- Der Austausch darf die alte Wolke erst entfernen, wenn die neue steht. Ein Fehler mittendrin lässt sonst den Himmel leer, obwohl der Abruf schon Daten hatte.
- `const=1` macht die Python-Antwort schwerer, weil die Linienenden bis mag 6,5 mitgerechnet werden. Dieselbe Route, derselbe Schutz gegen überlappende Abrufe.
- Schilder und Linien mit `depthTest: false` bleiben vor dem dunklen Himmel sichtbar und damit auch vor einem angeschnittenen Baum. Das ist die Einschränkung aus Abschnitt 7, kein zweiter Filter.

## 10. Abnahme

1. Die Sterne bleiben sichtbar.
2. Die Linien verbinden die zugehörigen Sterne.
3. Die Namen sitzen auf den gelieferten Positionen.
4. Die Namen bleiben bei Kopfdrehung und Kopfneigung lesbar.
5. Sterne, Linien und Namen gehen mit dem Gartenpanorama mit.
6. Desktop und Quest zeigen dieselben Sternbilder zur selben Zeit.
7. Der 15-Sekunden-Takt erneuert alle drei Teile.
8. Ein fehlgeschlagener Abruf löscht den Himmel nicht und stoppt den Renderloop nicht.
9. Die Ansicht auf der Quest bleibt flüssig.
10. Ohne Linien und Namen bleiben die Sterne sichtbar.

## Danach

Sonne, Mond und Planeten stehen in [v0.4](astro-vr-architektur-v0.4.md). Das lesende Dashboard bleibt XR-7. Controller und ein Informationspanel am Sternbild sind nicht Teil von XR-6b. Die Sprite-Schilder sind nur die Darstellung, keine Bedienelemente.

## Verwandte Seiten

- [Astro-VR Architektur v0.2](astro-vr-architektur-v0.2.md)
- [Astro-VR Architektur v0.1](astro-vr-architektur-v0.1.md)
- [Astro-VR Architektur v0.4](astro-vr-architektur-v0.4.md) — XR-6c auf der Quest abgenommen
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
