# Astro-VR Architektur v1.4 — XR-8g.1 Tastaturtest

> Quelle: abgenommene Zielführung in [v1.3](astro-vr-architektur-v1.3.md)
> Stand: **Auf der Quest bestätigt** am 2026-10-11. Die Systemtastatur erscheint, `M13` wurde übernommen, Tafel und Zielführung blieben danach bedienbar. Nur `app_mele/vr.html`. Keine Suche, keine neue Route. Eine 3D-Tastatur ist nicht nötig. Fortschreibung: [v1.5](astro-vr-architektur-v1.5.md).

XR-8f bleibt. Eine eigene 3D-Tastatur ist nicht gebaut. Die Eingabemethode für XR-8g.2 wird erst nach diesem Test festgelegt.

## Sitzung

`optionalFeatures` sind `local` und `dom-overlay`. Das Overlay-Wurzelelement ist `#xr-overlay`, nur das Testfeld, nicht die ganze Seite. Schlägt diese Sitzung fehl, startet dieselbe Seite noch einmal nur mit `local`. Ein Start der XR-Sitzung gilt nicht als Nachweis für das Overlay.

Sichtbar wird der tatsächliche Zustand `session.domOverlayState.type`. Fehlt er, steht auf der Übersicht `DOM-Overlay: nicht aktiv`. Mögliche Typen sind `screen`, `floating` und `head-locked`.

## Test

Unter OBJEKTE steht `TASTATUR TEST`. Der Knopf liegt auf der 3D-Tafel. Das Feld selbst ist HTML am unteren Bildrand und nur offen, solange der Test läuft. Es verdeckt die Tafel nicht dauerhaft.

Der Knopf setzt den Fokus in demselben Controllerereignis. Ob der Quest-Browser das als Nutzeraktion für die Systemtastatur anerkennt, ist der offene Punkt. Gelingt der Fokus nicht, sagt das Feld das, und es kann direkt angetippt werden, falls es im Headset sichtbar ist.

Übernehmen zeigt den Text nur lokal, zum Beispiel `Übernommen: M13`. Es gibt keinen Katalogaufruf. Schließen blendet das Feld aus und nimmt den Fokus weg. Die XR-Sitzung bleibt.

## Quest-Abnahme

1. Seite neu öffnen und die immersive Sitzung starten.
2. Auf der Übersicht den Overlay-Status lesen.
3. OBJEKTE, dann TASTATUR TEST.
4. Prüfen, ob das Feld im Headset sichtbar ist.
5. Prüfen, ob die Systemtastatur erscheint.
6. `M13` eingeben und übernehmen.
7. Schließen.
8. Tafel, Telrad und Zielführung weiter bedienen.
9. Prüfen, ob die Sitzung durchgehend aktiv war.

Vor dem Test die App neu starten und die Quest-Seite neu öffnen.

## XR-8g.2, nicht gebaut

`GET /catalog/resolve` rechnet Azimut und Höhe bereits serverseitig für den übergebenen Zeitpunkt und liefert `az`, `alt`, `ra`, `dec`, `above` und `when`. Eine grüne Markierung braucht dafür keine Ephemeride im Browser. Nach einem späteren Zeitsprung bleibt diese Position stehen, bis das Objekt im Overlay auftaucht oder resolve erneut gerufen wird.

## Verwandte Seiten

- [Astro-VR Architektur v1.3](astro-vr-architektur-v1.3.md)
- [Astro-VR Architektur v1.5](astro-vr-architektur-v1.5.md) — XR-8g.2 Katalogsuche, Quest-Abnahme offen
- [Quest 3 — XR-Roadmap](quest3-xr-roadmap.md)
