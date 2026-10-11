# Astro-VR Architektur v0.9 — XR-3c Preferences

> Quelle: Quest-Abnahme von [v0.8](astro-vr-architektur-v0.8.md), Auftrag XR-3c
> Stand: **Auf der Quest abgenommen am 2026-10-11.**

Das Dashboard behält Größe und Abstand. Unten links bleibt `OBJEKTE`, unten rechts kommt `EINSTELLUNGEN`. Die Objektliste, die Detailansicht und die Himmelsauswahl bleiben. Kein Python, keine neue Route, keine Gerätebefehle.

## Bedienung

Vier Reiter, jeweils wenige Zeilen. `+` und `-` wirken sofort. Die Zahlenzeile selbst schluckt den Strahl, damit ein Treffer daneben das Panel nicht schließt. `FERTIG` kehrt zur Übersicht. `STANDARD` setzt die Ausgangswerte und löscht den gespeicherten Stand.

| Reiter | Zeile | Wirkung |
|---|---|---|
| ZIEL | Treffer | Aufnahme eines Kandidaten |
| ZIEL | Halten | Hysterese, wie lange der Kandidat bleibt |
| ZIEL | Wechsel | Vorteil, den ein anderer Kandidat braucht |
| ZIEL | Strahl | Länge der sichtbaren cyanen Linie |
| RINGE | Innen, Mitte, Außen | Durchmesser der drei Telrad-Ringe |
| BILD | Namen | Höhe der Namensschilder, auch der Sternbildnamen |
| BILD | Markierung Telrad | fest, kein zweites Fadenkreuz |
| TASTE | Öffnen | Abzug oder Griff |
| TASTE | Zielhilfe | Keine oder die Taste, die Öffnen nicht belegt |

Halten bleibt mindestens so groß wie Treffer. Hebt man Treffer darüber, rückt Halten mit. Senkt man Halten darunter, rückt Treffer mit.

## Ausgangswerte und Bereiche

Die Ausgangswerte sind die bisher bewährten. Gespeichert wird nur, was das Panel ändert. Schalenradius, Farben, die kleine Bewegung zum Handwechsel und die 400 ms zwischen zwei Abzügen bleiben im Code.

| Wert | Ausgang | Bereich | Schritt | Gespeichert als |
|---|---|---|---|---|
| Treffer | 0,25° | 0,05° bis 1,50° | 0,05° | `pickAcquireDeg` |
| Halten | 0,40° | 0,10° bis 2,00° | 0,05° | `pickHoldDeg` |
| Wechsel | 0,08° | 0,02° bis 0,50° | 0,02° | `pickSwitchDeg` |
| Strahl | 2,0 m | 0,5 m bis 6,0 m | 0,5 m | `rayMeters` |
| Ring innen | 0,5° | 0,2° bis 10° | 0,1° | halber Winkel, 0,25° |
| Ring mitte | 2° | 0,2° bis 10° | 0,1° | halber Winkel, 1° |
| Ring außen | 4° | 0,2° bis 10° | 0,1° | halber Winkel, 2° |
| Namen | 7 | 4 bis 12 | 1 | `labelHeight` |
| Öffnen | Abzug | Abzug oder Griff | Umschalten | `select` oder `squeeze` |
| Zielhilfe | Keine | Keine oder die freie Taste | Umschalten | `""`, `select` oder `squeeze` |

Die Ringe sind unabhängig. Die klassische Kombination 0,5° / 2° / 4° ist nur der Ausgang, keine erzwungene Ordnung. Im Speicher stehen die halben Winkel, weil die Zeichnung `tan` davon nimmt. Die Fläche zeigt den Durchmesser.

Der sichtbare Strahl ist nur die Linie. Der Treffer auf eine Schaltfläche reicht weiter als die Linie. Ein kurzer Strahl sperrt das Panel deshalb nicht aus.

## Tasten

`select` ist der Zeigefingerabzug, `squeeze` der Griff unter dem Mittelfinger. Gamepad-Nummern werden nicht verwendet.

Öffnen kann nicht auf Keine stehen. Sonst ließe sich das Dashboard nicht mehr einblenden. Zielhilfe darf Keine sein. Sie darf nicht dieselbe Taste wie Öffnen belegen. Wechselt Öffnen auf die Taste der Zielhilfe, fällt die Zielhilfe auf Keine zurück. Danach kann man sie auf die nun freie Taste setzen.

Ist die Zielhilfe belegt, schaltet diese Taste Strahl und Telrad zusammen aus und wieder ein. Die Panelflächen bleiben treffbar, auch wenn die Linie fehlt. Eine neue Sitzung beginnt mit eingeschalteter Zielhilfe. Die Belegung bleibt, der Aus-Zustand nicht.

## Speicherung

Schlüssel `astro-vr-prefs-v1` in `localStorage` des Browsers, der die Seite offen hat. Das ist auf der Quest der Browser von `https://vr.netzberger.at:8443`, nicht der Desktop und nicht die App-Datenbank.

Der Eintrag ist JSON mit `v: 1`, den sechs Zahlen und den beiden Rollen. Fehlt er, ist er kein JSON, hat er eine andere Version oder ein Feld keine Zahl, gilt für dieses Feld der Ausgangswert. Zahlen außerhalb des Bereichs werden in den Bereich gezogen. Eine Rolle außer `select`, `squeeze` und, nur bei der Zielhilfe, leer wird verworfen. `STANDARD` löscht den Eintrag.

## XR-8

Nicht in diesem Schritt. Als Nächstes eine Inventarliste der Werkzeuge in `pano.html`, noch ohne neue VR-Funktion. Die Gruppen zur Prüfung stehen in der [Quest-Roadmap](quest3-xr-roadmap.md).

## Abnahme

1. Übersicht zeigt `OBJEKTE` und `EINSTELLUNGEN`. Liste, Detail und Telrad tun dasselbe wie nach v0.8.
2. Die vier Reiter öffnen sich. Ohne früheren Speicher stehen die Ausgangswerte.
3. Treffer, Halten und Wechsel ändern die Zahlen sofort. Ein größerer Treffer nimmt einen ferneren Stern, ein kleinerer verlangt mehr Ruhe.
4. Die drei Ringe ändern sich sofort. `STANDARD` stellt 0,5° / 2° / 4° wieder her.
5. Der cyanfarbene Strahl wird kürzer und länger. Die Schaltflächen bleiben treffbar.
6. Namen ändert die Schildgröße von Sternbild und anvisiertem Objekt sofort.
7. Öffnen wechselt zwischen Abzug und Griff. Die andere Taste öffnet und schließt das Panel. Öffnen lässt sich nicht auf Keine stellen.
8. Zielhilfe bietet nur Keine und die freie Taste. Die belegte Taste blendet Strahl und Telrad aus und wieder ein. Öffnen bleibt benutzbar.
9. Seite neu laden: die letzten Werte sind da. Nach `STANDARD` und erneutem Laden sind die Ausgangswerte da.
10. Himmel, Planeten und die Objektliste bleiben.

## Verwandte Seiten

- [Astro-VR Architektur v0.8](astro-vr-architektur-v0.8.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
