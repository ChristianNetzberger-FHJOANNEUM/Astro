# Astro-VR Architektur v1.5 — XR-8g.2 Katalogsuche

> Quelle: abgenommene Systemtastatur in [v1.4](astro-vr-architektur-v1.4.md)
> Stand: **Auf der Quest bestätigt** am 2026-10-11. `app_mele/vr.html` und die Caddy-Freigabe auf Port 8443. Keine neue Python-Route, keine 3D-Tastatur, kein GoTo. Die Quest-Tastatur füllt einen früheren Suchbegriff nicht vor. Das ist kein Fehler.

XR-8f und XR-8g.1 bleiben. Die Sechserliste, der rote Telrad, Pfeil, Winkel, aimToggle, Panorama, Sterne, Messier, NGC, TYPEN, Unruhe, LIVE und die Tafelgröße sind unverändert. NINA, SynScan, GoTo und Aufnahme bleiben unberührt. Eine Mindesthöhe von 25° ist nicht eingebaut. Die Unterscheidung zwischen astronomischem Horizont und Verdeckung durch Haus oder Baum ist nicht Teil dieses Schritts.

## Bedienung

OBJEKTE zeigt weiter die Sechserliste. `SUCHEN` öffnet dasselbe HTML-Feld wie der Tastaturtest, am unteren Bildrand, nur solange die Eingabe läuft. Fokus kommt aus dem Controllerereignis. Die Quest-Systemtastatur übernimmt den Text. Übernehmen schließt das Feld und sucht.

Die Treffer ersetzen die Sechserliste auf derselben Tafel, höchstens sechs pro Seite. `ZURÜCK` und `WEITER` in dieser Zeile blättern. Der untere Knopf heißt dann `LISTE` und kehrt zur Sechserliste zurück. Der Suchbegriff bleibt erhalten. `SUCHEN` öffnet das Feld erneut. Die Quest-Tastatur zeigt ihn nicht in ihrer eigenen Zeile. Über dem Feld steht `Zuletzt: …`, und der Knopf daneben sucht diesen Begriff erneut.

Ein Treffer ruft die Detailansicht. Erst `ZIEL FINDEN` setzt das Navigationsziel. Dafür wird `/catalog/resolve` zum aktuellen Himmelzeitpunkt erneut gerufen und mit Herkunft `resolve` übernommen. Der grüne Telrad, der Pfeil und die Winkelanzeige sind dieselben wie in XR-8f.

## Schnittstellen

Vorhanden, nur lesend:

`GET /catalog/search?q=&limit=`

`limit` ist 1 bis 50, Voreinstellung 20. Die Quest sendet `limit=48`. Leeres `q` liefert `{ok:true, query:"", hits:[]}`. Ein Treffer hat `key`, `id`, `name`, `kind`, und je nach Art `type`, `ra`, `dec`, `mag`, `mag_band`, `hip`, `con`. Azimut und Höhe stehen hier nicht.

`GET /catalog/resolve?q=&lat=&lon=&when=&stem=`

`key` ist dasselbe wie `q`. Leeres `when` ist die aktuelle UTC-Zeit. Die Quest lässt `when` bei LIVE weg und sendet bei manueller Zeit `skyView.when`. `lat`, `lon` und, wenn gesetzt, `stem` sind dieselben wie beim Himmels-Overlay. Die Antwort ist `{ok, query, object}`. Das Objekt hat `az`, `alt`, `ra`, `dec`, `above`, `when` und die Katalogfelder. `above` nutzt die Gartenmaske nur, wenn `stem` gesetzt ist. Das ist das bestehende Verhalten, keine neue Horizontart.

Eine veraltete Antwort überschreibt keine neuere Suche und kein neueres Auflösen. Leerer Begriff, keine Treffer, ungültige Eingabe, ein nicht erreichbares Backend und eine langsame Antwort bleiben auf der Tafel stehen, ohne die letzte Himmelsantwort zu ersetzen.

## Ziel und Zeit

`adoptNavTarget` speichert bei diesem Weg die Herkunft `resolve` und den Katalogschlüssel. Steht das Objekt in der nächsten Overlay-Antwort, gelten deren Azimut und Höhe. Fehlt es, weil Messier aus ist, NGC aus ist, es nicht in MEINE AUSWAHL liegt oder die Grenzhelligkeit es ausblendet, ruft die nächste Himmelsantwort `/catalog/resolve` erneut. Die letzte Position gilt nicht still als aktuelle Position: schlägt das Auflösen fehl, verschwindet der grüne Telrad und die Anzeige lautet `Position nicht erneuert`. Die Identität bleibt.

Liegt `above` auf falsch oder die Höhe bei 0° oder darunter, lautet die Anzeige `Ziel unter Horizont`. Der grüne Telrad wird nicht über dem Horizont gezeichnet.

Ein Overlay-Ziel, dessen Katalogschalter aus ist, bleibt wie in v1.3 auf der letzten Position und erhält `fest`. Das gilt nicht für ein Resolve-Ziel.

## Caddy, Port 8443

Zusätzlich zur bestehenden Pfadliste, nur GET, genaue Pfade:

```
@catalog_read {
    method GET
    path /catalog/search /catalog/resolve
}
handle @catalog_read {
    reverse_proxy 127.0.0.1:8082
}
```

`/catalog` und `/catalog/picks` bleiben zu. POST auf die beiden Suchpfade bleibt zu. NINA, SynScan, GoTo und Aufnahme sind nicht freigegeben.

## Quest-Abnahme

Auf der Quest bestätigt am 2026-10-11.

Die Kette SUCHEN, Systemtastatur, Trefferliste, Detail, ZIEL FINDEN setzt den grünen Telrad. Der rote Telrad führt mit Pfeil und Winkel. LISTE stellt die Sechserliste wieder her.

Geprüft: M13 bei MESSIER AUS, NGC 7009 bei NGC AUS, ein IC-Objekt (vorgegeben war IC 5146), der Planet Saturn, benannte Sterne, Blättern, erneute Suche, keine Treffer, +1 h für ein Resolve-Ziel außerhalb des Overlays, Griff aus, Messier, NGC-Modi, TYPEN und Unruhe. Es wurden keine Gerätebefehle ausgelöst.

`GET /catalog/picks` auf Port 8443 bleibt gesperrt. Das ist lokal gegen Caddy geprüft, nicht als eigener Quest-Lauf.

## Verwandte Seiten

- [Astro-VR Architektur v1.4](astro-vr-architektur-v1.4.md)
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
