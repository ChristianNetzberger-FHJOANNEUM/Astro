# Astro-VR Architektur v1.7 — XR-10a Montierungsanzeige

> Quelle: abgenommene Tagesbahn in [v1.6](astro-vr-architektur-v1.6.md)
> Stand: **Auf der Quest abgenommen** am 2026-10-12. Sieben Feldtests auf der Quest, der Sicherheitspunkt im Client und in der Caddy-Freigabe. `GET /nina/mount` auf Port 8443. Kein GoTo von der Quest. Fortschreibung: [v1.8](astro-vr-architektur-v1.8.md).

Dies ist XR-10a, die lesende erste Phase der Montierungsintegration XR-10. XR-10b und XR-10c sind nicht Teil dieser Seite. XR-9a bleibt. Tagesbahn, Katalog, Suche, ZIEL FINDEN, roter und grüner Telrad, aimToggle, LIVE, Himmels-Schalter, Foto-Helligkeit, Ziehen und die Controllerbelegung sind unverändert. NINA, SynScan und Aufnahme bleiben unberührt. Eine Mindesthöhe von 25° ist nicht eingebaut. Flug, Monde und Sonnensystem heißen XR-20 und bleiben außerhalb dieser Arbeit.

## Bedienung

Auf der Übersicht steht `MONTIERUNG` neben `EINSTELLUNGEN`. Die Ansicht liegt auf derselben Tafel. `ZURÜCK` führt zur Übersicht. Es gibt keine Steuerknöpfe.

Die Quest liest einmal pro Sekunde `GET /nina/mount`. Ein zweiter Abruf wartet, solange der erste läuft. Eine ältere Antwort wird verworfen. Die Position wird nicht interpoliert.

Der gelbe Telrad zeigt die von NINA gemeldete Teleskoprichtung. Seine Kreise haben dieselben Durchmesser wie Rot und Grün: 0,5°, 2° und 4°. Die Lage kommt nur aus `azimuth_deg` und `altitude_deg`, über dieselbe Abbildung wie die anderen Telrade. Neben dem äußeren Kreis steht `GTi`. Ein Richtungspfeil gibt es nicht.

Rot bleibt die Controller-Richtung, Grün das ausgewählte Ziel. Alle drei können gleichzeitig sichtbar sein. Gelb wird vor Rot und Grün gezeichnet, damit es die beiden nicht verdeckt. Fehlt die Verbindung, die Montierung oder Azimut oder Höhe, verschwindet der gelbe Telrad sofort. Die Tafel nennt dann den Zustand und höchstens die Uhrzeit der letzten gültigen Antwort, keine scheinbar aktuelle Richtung. Kommt eine gültige Position wieder, erscheint der Telrad von selbst.

Die Tafel zeigt Verbindung, RA, Dec, Azimut, Höhe, Tracking, Slew, Parken, Pier und die Uhrzeit. `Abstand Ziel–Montierung` erscheint nur, wenn Ziel und Montierung gleichzeitig gültig sind. Der Winkel ist die Differenz aus den beiden Azimut-Höhe-Richtungen. Er misst nicht unabhängig, ob die Montierung am Himmel wirklich dort steht.

## Schnittstelle

Vorhanden, nur lesend: `GET /nina/mount`

Dahinter steht NINA `GET /equipment/mount/info`. SynScan wird nicht gefragt. Die Quest sendet keinen Slew, keinen Stop und keine Achsbewegung.

Auf Port 8443 ist nur dieser GET-Pfad ergänzt:

```
@mount_read {
    method GET
    path /nina/mount
}
handle @mount_read {
    reverse_proxy 127.0.0.1:8082
}
```

`/nina/mount/slew`, `/nina/mount/move` und die übrigen NINA-Pfade bleiben gesperrt.

## Quest-Abnahme

Auf der Quest bestätigt am 2026-10-12: Tracking über die verlangte Zeit, Verbindungsabbruch, Neuverbinden, Zielabstand, die drei Telrade zugleich, Tagesbahn und Katalogsuche. Dazu die frühere Prüfung, dass der gelbe Telrad einer manuellen SynScan-Bewegung folgt und `MONTIERUNG` lesbar ist.

Der Punkt Sicherheit ist nicht auf der Quest beobachtet. In `vr.html` gibt es keinen POST und keinen WebSocket. Der einzige NINA-Abruf ist `GET /nina/mount`. Auf Port 8443 ist von den NINA-Pfaden nur dieser GET freigegeben. Slew, Stop und Move bleiben geschlossen.

Fortschreibung: [Astro-VR Architektur v1.8](astro-vr-architektur-v1.8.md).

## Verwandte Seiten

- [Astro-VR Architektur v1.6](astro-vr-architektur-v1.6.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
