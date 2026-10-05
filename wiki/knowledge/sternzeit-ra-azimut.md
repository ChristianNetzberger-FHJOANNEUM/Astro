# Sternzeit, RA und Azimut

> Quelle: KI-Antwort (Cursor), 2026-10-02 · SynScan / Vega-Beispiel, Standort ~48° N

Der Zusammenhang ist elegant und lässt sich in zwei Transformationen zerlegen:

**Katalogkoordinaten RA/DEC → Stundenwinkel → lokale Position Azimut/Höhe.**

## 1. RA und DEC sind die „Adresse“ des Sterns

Für Vega ungefähr:

- α = RA ≈ 18h 36m 56s  
- δ = DEC ≈ +38° 47′

RA und DEC sind am Himmel das Analogon zu Länge und Breite auf der Erde. Sie ändern sich innerhalb einer Nacht praktisch nicht.

Die RA sagt aber **nicht** unmittelbar, wo der Stern gerade steht. Dafür brauchen wir die Sternzeit.

## 2. Local Sidereal Time (LST)

Die lokale Sternzeit beantwortet eine anschauliche Frage:

**Welche Rektaszension steht gerade auf meinem lokalen Meridian?**

Wenn z. B. LST = 22h 54m ist, steht ein Objekt mit RA = 22h 54m gerade auf dem Meridian.

Genau deshalb ist die Sternzeit für eine parallaktische Montierung so wichtig.

## 3. RA und Sternzeit ergeben den Stundenwinkel

Zentrale Gleichung:

```
H = LST − RA
```

mit H = Stundenwinkel.

Beispiel Vega (SynScan-Werte):

- LST = 22:54:32  
- RA_Vega = 18:36:56  

```
H = 22:54:32 − 18:36:56 = 4h 17m 36s
```

Eine Stunde Stundenwinkel entspricht 15°:

```
4.2933 h × 15°/h ≈ 64.4°
```

Vega lag also etwa **64,4° Stundenwinkel westlich** des Meridians.

| H | Bedeutung |
|---|-----------|
| H < 0 | östlich des Meridians |
| H = 0 | auf dem Meridian |
| H > 0 | westlich des Meridians |

Kurz: **HA = LST − RA** — eine der wichtigsten Beziehungen überhaupt.

## 4. Standort → Höhe und Azimut

Mit Stundenwinkel H, Deklination δ und geografischer Breite φ:

```
sin h = sin φ · sin δ + cos φ · cos δ · cos H
h = arcsin(…)
```

Azimut (robust mit atan2), astronomische Konvention 0° = Nord, 90° = Ost, 180° = Süd, 270° = West:

```
A = atan2( −sin H · cos δ ,
           sin δ · cos φ − cos δ · sin φ · cos H )
```

anschließend in 0…360° bringen.

## 5. Woher kommt die Sternzeit?

Kette:

```
Datum/Uhrzeit → UTC → JD → GMST → LST
```

mit geografischer Länge λ (östlich positiv):

```
LST = GMST + λ
```

Gesamt:

```
LST − RA → H
H, δ, φ → Azimut, Höhe
```

Das ist im Kern die Mathematik hinter SynScan, Stellarium und `app_mele`.

## Anschauliche Interpretation

Das äquatoriale System ist fest mit dem Sternhimmel verbunden. Vega hat die Adresse RA ≈ 18:37, DEC ≈ +38.8°. Die Erde dreht sich darunter — die lokale Sternzeit läuft 18:00 → 19:00 → …

- Wenn **LST = RA**, dann **H = 0**: Vega steht auf dem lokalen Meridian.  
- Eine Stunde später: **H = +1h = +15°** westlich des Meridians.

Deshalb muss eine korrekt poleingestellte parallaktische Montierung die RA-Achse im Wesentlichen mit Sternzeitgeschwindigkeit nachführen.

## Meridian ≠ immer Azimut 180°

Ein Objekt auf dem lokalen Meridian hat **H = 0**, steht aber nicht zwingend bei Azimut 180°.

Der lokale Meridian ist der Großkreis **Nordpunkt → Zenit → Südpunkt**:

- Objekt **südlich** des Zenits → A = 180° (Süden)  
- Objekt **nördlich** des Zenits → A = 0° (Norden)  
- Genau im Zenit → Azimut mathematisch nicht eindeutig  

Entscheidend: Deklination δ im Vergleich zur Breite φ.

Oberer Meridiandurchgang:

```
h = 90° − |φ − δ|
```

Beispiel φ ≈ 48° N, Vega δ ≈ +38.8°:

```
h ≈ 90° − |48° − 38.8°| ≈ 80.8°
```

→ kulminiert hoch, aber **südlich** des Zenits (A = 180°).

Sterne mit **δ > φ** kulminieren **nördlich** des Zenits (A = 0°).

> **LST = RA ⇔ H = 0** bedeutet: „auf meinem lokalen Meridian“ — nicht automatisch „genau im Süden“.

Kleiner Begriffsunterschied: Der lokale Meridian ist **nicht** die geografische Länge. Die Länge legt fest, *wo auf der Erde* dein Meridian liegt; am Himmel ist er der Großkreis durch Nord, Zenit, Süd und die Himmelspole.

## Ausblick (Polfehler / Sternstriche)

Dieselbe Transformation lässt sich um eine leicht falsch ausgerichtete Polachse erweitern (z. B. Mel/Maz). Dann kann man berechnen, wo ein Stern nach 60 s landet — die Differenz ergibt Länge und Richtung eines Sternstrichs auf der Kamera. Das ist ein guter Kandidat für eine spätere Funktion in `app_mele`.
