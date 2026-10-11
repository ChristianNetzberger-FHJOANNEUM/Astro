# Astro-VR Architektur v0.6 — XR-3 Strahl und eine Testschaltfläche

> Quelle: Abnahme von XR-7b am 2026-10-11 plus die Prüfung der Abzug-Regel
> Stand: **Auf der Quest abgenommen, 2026-10-11.** Der Strahl ist einige Meter lang und reicht nicht bis zum Sternenhimmel. `TEST` erhöht den Zähler beim Abzug.

[v0.5](astro-vr-architektur-v0.5.md) bleibt gültig. Keine neuen Himmelsdaten, keine Gerätebefehle, kein Framework. Nur `app_mele/vr.html`, wenn die Umsetzung freigegeben wird.

## Stand

| Phase | Funktion | Status |
|---|---|---|
| XR-6a | Sterne, 15-Sekunden-Takt | Abgenommen |
| XR-6b | Sternbilder und Namen | Abgenommen |
| XR-6c | Sonne, Mond, Planeten | Abgenommen |
| XR-7a | Schwebendes Lesepanel | Abgenommen |
| XR-7b | Abzug blendet ein und aus | Abgenommen |
| XR-3 | Strahl, zeigen, auswählen | Diese Spezifikation |

## Vereinbarkeit mit XR-7b

Die Regel ist mit dem heutigen `select`-Listener vereinbar, unter einer Bedingung.

`toggleDashboard` läuft bei jedem Abzug und kennt keine Schaltfläche. Das Panel ist eine einzige Ebene. Ein Treffer auf diese Ebene darf den Abzug nicht schlucken, sonst ließe sich das Panel nicht mehr ausblenden, sobald der Strahl es streift.

Nur eigene Schaltflächen-Netze zählen. Trifft der Strahl der Hand, die den Abzug drückt, so eine Fläche, führt der Abzug deren Aktion aus und blendet nicht um. Sonst bleibt das Verhalten von XR-7b: sichtbar aus, unsichtbar vor den aktuellen Blick.

Die Pose im `select`-Listener ist dafür zu spät und ohne XR-Frame. Three.js schreibt die Controller-Matrix in jedem XR-Frame, bevor die Seite zeichnet. Der Treffer wird in diesem Frame gemerkt und beim Abzug nur gelesen. Die 400 ms bleiben, damit ein Druck nicht zweimal zählt. Die andere Hand innerhalb dieser Zeit wird mit verworfen.

Ist das Panel unsichtbar, gibt es keinen Treffer. Der Abzug legt es wie bisher vor den Blick.

## Darstellung

Pro Controller mit `targetRayMode` `tracked-pointer` eine kurze Linie in dessen Zielstrahl, nur während der Sitzung. Kein Blickstrahl, keine Meta-Taste, keine Gamepad-Nummer. Der Griff bleibt frei.

Eine Testschaltfläche sitzt auf dem Panel, Kind der Dashboard-Gruppe, und wandert mit, wenn das Panel neu steht. Zeigen färbt sie um. Der Abzug erhöht einen Zähler im Paneltext. Die Textur wird nur bei dieser Änderung neu gezeichnet, nicht pro Frame. Der Zähler ist die ganze Aktion. Kein NINA, kein SynScan, kein GoTo.

Der Strahl prüft nur diese Schaltflächen, nicht Sterne, Linien oder das Gartenfoto.

## Grenzen

Keine zweite Eingabeschicht, keine Objektwahl am Himmel, keine Controllerarchitektur über diese eine Regel hinaus. Wetter, Guiding und Teleskopstatus kommen später als weitere Flächen derselben Art.

## Umsetzung

Der Zeigefingerabzug bleibt `select`. Meta-Taste und Griff bleiben unbenutzt. Nur Controller mit `targetRayMode` `tracked-pointer` bekommen eine zwei Meter lange Linie entlang der Zielachse.

In jedem XR-Frame wird nur die Testfläche geprüft, nicht die Panel-Ebene und nicht der Himmel. Der Treffer liegt unter der `inputSource` dieser Hand. `select` liest genau diesen Eintrag. Gehört er nicht mehr zum sichtbaren Dashboard oder zur Testaktion, wird er verworfen und der Abzug schaltet das Panel wie bisher. Schließen, Sitzungsende und `disconnected` leeren die Treffer. Die 400 ms bleiben davor, damit ein Druck nicht zweimal zählt.

Die Fläche zeigt `TEST` und den Zähler. Zeigen färbt sie gelb. Der Abzug darauf erhöht den Zähler und lässt das Panel offen.

## Abnahme

1. Ohne Treffer auf die Testfläche schaltet der Abzug das Panel wie in XR-7b.
2. Der Strahl ist sichtbar und folgt dem Controller.
3. Über der Testfläche wechselt die Farbe.
4. Der Abzug auf der Fläche erhöht den Zähler und lässt das Panel offen.
5. Ein Druck löst nicht zusätzlich das Ein- oder Ausblenden aus.
6. Nach dem Neu-Positionieren trifft der Strahl die Fläche an der neuen Stelle.
7. Sternenhimmel und Overlay bleiben unverändert.
8. Die Quest bleibt flüssig.

## Verwandte Seiten

- [Astro-VR Architektur v0.5](astro-vr-architektur-v0.5.md)
- [Astro-VR Architektur v0.7](astro-vr-architektur-v0.7.md) — Objektinfo umgesetzt, Quest-Abnahme offen
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
