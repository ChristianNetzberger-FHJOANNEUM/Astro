# Astro-VR Architektur v1.12 — Himmelspunkt

> Quelle: Quest-Achse in [v1.11](astro-vr-architektur-v1.11.md)
> Stand: **Abgenommen am 2026-10-13.** Stabile Referenz zusammen mit [v1.11](astro-vr-architektur-v1.11.md). Nächstes Kapitel: [v1.13](astro-vr-architektur-v1.13.md).

Ein Punkt am Himmel kann die Zielkoordinaten eines GoTo liefern. Der Abzug übernimmt nur die Anzeige. Die Fahrt bleibt die bestehende Bestätigung. Ein Name und eine Tour sind nicht Teil dieses Schritts.

## Bedienung

Im Montierungsblatt steht **HIMMELSPUNKT**. Danach zeigt der Suchstrahl auf die Himmelsschale. Der Abzug übernimmt den Punkt, an dem der Strahl die Schale trifft, sofern er keine Taste und nicht die Tafel selbst trifft. Die Tafel zeigt Azimut, Höhe, Rektaszension, Deklination und die verwendete Himmelszeit. Bei live steht „Zeit live“. Bei festgehaltener Zeit steht die Uhrzeit dieser Ansicht.

**GOTO PUNKT** öffnet dieselbe Bestätigung wie ein Katalogziel. **GOTO BESTÄTIGEN** sendet die Grad an `POST /nina/mount/slew` als `ra` und `dec`, ohne Katalognamen. **ABBRECHEN** sendet nichts. Liegt der Punkt unter dem Horizont oder hinter der Gartenmaske, bleibt **GOTO PUNKT** aus und die bekannte Ablehnung steht auf der Tafel.

## Rechnung

Die Seite kehrt nur die Abbildung der Himmelsschale um, einschließlich des Nord-Offsets. Rektaszension und Deklination rechnet der Server mit `az_alt_to_radec`, derselben Umkehrung, die den Katalog an den Himmel zeichnet. Ein Punkt auf einem gezeichneten Stern trifft dessen GoTo-Grad. Die Quest rechnet diese Grad nicht selbst.

`GET /sky/point` liest nur. Port 8443 gibt diesen Pfad frei, nicht als Steuerbefehl. Horizont, Gartenmaske, PHD2, Parken und die Kopplung prüft weiterhin der bestehende Schwenk.

## Abnahme

Abgenommen am 2026-10-13 für den beschriebenen Umfang. Zusammen mit der manuellen Achse in v1.11 ist das der getestete Stand.

| Kapitel | Funktion | Status |
| --- | --- | --- |
| XR-10a | Montierungsanzeige | Abgenommen |
| XR-10b | Katalog-GoTo und STOP | Abgenommen |
| v1.11 / XR-10c B2 | Manuelle Achse, STOP ACHSE, Unterbrechung der Quest | Abgenommen |
| v1.12 | Freier Himmelspunkt | Abgenommen |

| Feldprüfung | Ergebnis |
| --- | --- |
| Suchstrahl zeigt Azimut, Höhe, Rektaszension und Deklination und sendet keine Fahrt | Bestanden |
| GOTO PUNKT, danach GOTO BESTÄTIGEN startet die Fahrt | Bestanden |
| ABBRECHEN sendet keinen Fahrbefehl | Bestanden |
| Punkt unter dem Horizont oder hinter der Gartenmaske wird abgelehnt | Bestanden |
| Zeit live und festgehaltene Himmelszeit werden korrekt angezeigt | Bestanden |
| Koordinatenumrechnung bleibt auf dem Server | Bestanden |

## Referenz für spätere Kapitel

Diese Fassung bleibt die Referenz, bevor eine weitere Funktion beginnt. Spätere Erweiterungen lassen die bestehende Koordinatenumrechnung, die Sicherheitsprüfungen und die Controllerbelegung unverändert. Die Umrechnung bleibt `az_alt_to_radec` auf dem Server. Horizont, Gartenmaske, PHD2, Parken und die Kopplung bleiben die Prüfungen des bestehenden Schwenks. `select` bleibt der Abzug, `squeeze` die optionale Zielhilfe.

## Nicht in diesem Schritt

Kein gespeicherter Name, keine Tour, kein Schwenk durch den Abzug allein. Parken und Hibernate sind nicht begonnen.
