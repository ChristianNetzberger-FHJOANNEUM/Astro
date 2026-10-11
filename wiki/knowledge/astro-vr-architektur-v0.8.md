# Astro-VR Architektur v0.8 — XR-3b Telrad und Himmelsauswahl

> Quelle: Quest-Befund zum 2-m-Strahl, nach der Abnahme von [v0.7](astro-vr-architektur-v0.7.md)
> Stand: **Auf der Quest abgenommen am 2026-10-11.** Die Ringe in der Tangentialebene sind eine bewusste Näherung. Sichtbar ist nur ein Telrad, an der zuletzt bewegten Hand. Einstellungen dazu stehen in [v0.9](astro-vr-architektur-v0.9.md).

Das Dashboard, `OBJEKTE` und der kurze Strahl bleiben. Die Himmelsauswahl ist eine zweite, getrennte Rechnung im selben Frame. Nur `app_mele/vr.html`, sobald freigegeben. Kein GoTo, keine neue Route, kein Python.

## Was die Seite heute tut

Der Controller hängt in der Szene, nicht an der Panoramakugel. Seine Linie läuft 2 m entlang der lokalen Achse −Z. Die Kugel steht im Ursprung, Radius 500 für das Foto, 480 für die Sterne, 476 für die Gestirne. `sphere.rotation.y` ist `northOffset + 90°`. `azAltToVec` legt die Objekte lokal in diese Gruppe. Weltlage ist damit `sphere.localToWorld`. Der Kopf sitzt nahe dem Ursprung, der Controller daneben, typisch einige Dezimeter.

Zwei Meter sind gegen 480 m Himmel kurz. Aus dem Auge liegt das Strahlende um den Winkel `atan(Abstand Controller–Auge / 2 m)` neben der Achse. Bei 0,4 m seitlichem Versatz sind das etwa 11°. Deshalb taugt der kurze Strahl zum Panel und nicht zum Stern.

## Schnitt mit der Kugel

Strahl `P + t D` in Weltkoordinaten. `P` ist die Controllerposition, `D` die Welt-Richtung von −Z, Länge 1. Die Sternschale ist eine Kugel um den Ursprung mit Radius 480. Die Norddrehung ändert den Mittelpunkt nicht.

Innen gibt es genau einen Schnitt mit `t > 0`:

`t = -(P·D) + sqrt( (P·D)² - |P|² + 480² )`

`Q = P + t D` ist der Zielpunkt auf der Sternschale. Die Zielrichtung vom Mittelpunkt ist `normalize(Q)`, nicht `D`. Der Unterschied ist die Parallaxe des Controllers und liegt bei 480 m unter einem Zehntelgrad. Die Ringe und die Vorauswahl sitzen auf `Q`, nicht auf einer Verlängerung der 2-m-Linie.

Der cyanfarbene 2-m-Strahl bleibt für das Panel. Eine Linie über die ganzen 480 m würde das Gesichtsfeld zerschneiden und kommt nicht. Das Telrad am Zielpunkt ist das ferne Ende.

## Telrad

Drei rote `LineLoop`s, ohne Füllung, Farbe etwa `0xef4444`, Deckkraft etwa 0,8. Eine Gruppe in der Szene, nicht in der Panoramakugel, jedes Frame auf `Q` gesetzt und mit `lookAt` zum Ursprung gedreht. Die Ringe liegen in der Tangentialebene. Ihr Radius ist `480 * tan(halber Winkel)`.

| Ring | Durchmesser | Radius in der Ebene |
|---|---|---|
| innen | 0,5° | etwa 2,1 |
| mitte | 2° | etwa 8,4 |
| außen | 4° | etwa 16,8 |

Die Mitte bleibt leer, der Stern dahinter sichtbar. `depthTest` aus, wie bei den Sternpunkten, damit das Foto die Ringe nicht schluckt. WebGL zeichnet die Linie einen Pixel breit. Auf der Quest können die Ringe dünn wirken. Das wird praktisch geprüft, bevor eine Linienbibliothek dazukommt.

Die Tangentialebene ist nicht die Kugeloberfläche. Der äußere Ring liegt radial etwa 0,29 Einheiten außerhalb der Schale. Die Winkel vom Kugelmittelpunkt stimmen. Die Ebene bleibt.

Sichtbar ist ein Telrad. Es gehört der Hand, die sich zuletzt merklich bewegt hat. Beide Hände bedienen das Panel weiter. Zeigt die aktive Hand auf eine Schaltfläche, ist das Telrad in diesem Frame aus. Die andere Hand bekommt es erst, wenn sie sich bewegt.

Beide Augen sehen dasselbe Welt-Objekt. Der Augenabstand von etwa 6 cm gegen 480 m ist etwa 0,008°. Eine eigene Form pro Auge ist nicht nötig. Die Ringe hängen nicht am Kopf. Eine Kopfbewegung ändert ihre Lage am Himmel nicht. Ein Versatz des Kopfes um einen halben Meter gegen den Ursprung ändert den gesehenen Winkel um etwa 0,06°. Das liegt unter der Treffertoleranz.

`reticleKind` ist fest `"telrad"`. Ein späteres Fadenkreuz ist eine zweite Form in derselben Funktion, keine Umschaltung und kein Menü in diesem Schritt.

## Vorauswahl

Kandidaten sind die benannten Sterne und die Einträge in `bodies` aus der letzten Overlay-Antwort. Unbenannte Sterne zählen nicht. Dieselbe Kennung wie in v0.7: `kind` plus `hip`, sonst `kind` plus `id`, sonst `kind` plus `name`.

Der Winkel ist der zwischen `normalize(Q)` und `normalize(Weltposition des Objekts)`. Weltposition über `localToWorld`, keine neue Azimutrechnung.

Erste Schwelle 0,25°. Gewonnen hat der kleinste Winkel innerhalb der Schwelle. Liegt der Nächste darüber, gibt es keinen Kandidaten. Kein Auffüllen mit einem fernen Objekt.

Hysterese, für das eine Telrad: ist ein Kandidat gesetzt und sein Winkel noch höchstens 0,40°, bleibt er, außer ein anderer ist um mindestens 0,08° näher. Darüber wird er gelöscht. Ein Handwechsel setzt den Kandidaten zurück. Controller weg, Sitzung zu oder leeres Overlay: Kandidat weg. Ein fehlgeschlagenes Overlay behält die letzte Liste, wie bei der Objektinfo. Die drei Zahlen bleiben für die erste Abnahme. Dabei wird besonders der Wechsel auf einen Nachbarstern geprüft.

Der Kandidat bekommt einen kleinen Ring an seiner Weltposition und einen Namens-Sprite daneben, dieselbe Schildart wie die Sternbildnamen. Telrad-Mitte und Kandidat dürfen auseinanderliegen.

Der Abzug auf einen Kandidaten ruft `showObjectDetail` auf. Ist das Panel zu, wird es vorher wie beim Einblenden vor den Blick gestellt. Keine zweite Detailfunktion.

## Abzug

Unverändert zuerst die registrierte Schaltfläche der Hand, die den Abzug drückt. Die Panelfläche zählt nicht. Trifft keine Fläche und die Hand hat einen Kandidaten, öffnet sich dessen Detail. Sonst bleibt das Ein- und Ausblenden. Die 400 ms bleiben. Dashboard vor Himmel.

Zeigt die aktive Hand auf eine Schaltfläche, wird das Telrad in diesem Frame nicht gezeichnet. Ein zweites Telrad gibt es in dieser Version nicht.

## Späterer Umfang

In `vr.html`: Schnitt, drei Ringe, Kandidat mit Name, Hysterese, ein Zweig in `onSelect`. Der 2-m-Strahl, `OBJEKTE` und die Nordkugel bleiben. Keine Messier-Zeichnung, kein Caddy, kein Python.

## Abnahme, sobald gebaut

1. Die Ringe folgen dem Controller, nicht dem Kopf.
2. Außen etwa 4°, mitte 2°, innen 0,5°, geschätzt an bekannten Sternabständen.
3. Seitlich gehaltener Controller zielt auf den Stern, den die Ringe umschließen, nicht auf das Ende der 2-m-Linie.
4. Der Kandidat ist vor dem Abzug markiert, der Name lesbar.
5. Leichtes Zittern wechselt den Kandidaten nicht bei jedem Frame. Ein bewusstes Umzielen auf einen Nachbarstern wird erkannt, auch wenn die Hysterese den alten Kandidaten noch hält.
6. Ohne Objekt in der Schwelle passiert beim Abzug das bisherige Panel.
7. `OBJEKTE` hat Vorrang.
8. Himmel und Planeten bleiben. Die Ansicht bleibt flüssig.

## Verwandte Seiten

- [Astro-VR Architektur v0.7](astro-vr-architektur-v0.7.md)
- [Astro-VR Architektur v0.6](astro-vr-architektur-v0.6.md)
- [Astro-VR Architektur v0.9](astro-vr-architektur-v0.9.md) — XR-3c Preferences
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
