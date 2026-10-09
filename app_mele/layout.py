"""MeLE-UI: Panorama, Horizontlinie, Nordmarkierung, Himmelsgrid."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from nicegui import ui

from app_mele.state import UiState
from mele.horizon import overlay_svg, profile_belongs_to, sample_profile, sky_obstruction
from mele.mask import mask_tint_data_uri
from mele.sky import format_latitude, format_longitude, format_pointer, preview_to_horizontal

FORMULAS_MD = """
#### Projektion (equirektangular, 360° × 180°)

`Az = 360° · (x − x_N) / W   mod 360°`  
`h = 90° − 180° · y / H`  (geometrischer Horizont bei y = H/2)

#### Verfahren

**Automatisch.** Feste Blau/Sonne-Regel, erste Hinderniskante von oben.

**Farbpicker.** Nur Blau-Proben. Helle Hauswaende sind kein Himmel.
Sonne: eigener Exclude-Kreis (Farbe passt nie ins Blau). Optional
*Kein Himmel* auf Wände/Fenster. Danach nur die mit dem Zenit
zusammenhaengende Himmelsschicht.

**Hybrid.** Zuerst grobe Floor-Linie (Zeichnen / 360°-Punktwolke), dann
Himmelsfarben wie beim Picker. Ergebnis: Himmel = alles oberhalb der Floor
**oder** farbähnlich. So bleiben wolkenfreie Luecken unter der Floor
transparent, ohne die Floor zu verlieren. Details: Hilfe-Wiki.

**Zeichnen.** Stuetzpunkte, zirkulaer interpoliert.

**Pinsel / Radierer.** Malt die Alpha-Maske: Pinsel = Himmel (transparent),
Radierer = Boden (opak). Arbeit auf der Vorschau; Export rechnet auf
Vollaufloesung hoch (Nearest-Neighbour).

#### Speichern / Export

Pro Foto in `data/horizon/`:

- `{stem}.horizon.json` / `.csv` — h(Az), bleibt beim naechsten Oeffnen
- `{stem}.horizon.mask.png` — Graustufenmaske (0 = Himmel, 255 = Boden)
- `{stem}.horizon.png` / `.tif` — RGB + Alpha (Vorschau)
- `{stem}.horizon.full.png` — dasselbe in Originalgroesse
- `{stem}.landscape/` — Stellarium *spherical landscape* (PNG + `landscape.ini`)

Das ist das uebliche Format in der Astro-Community (Stellarium-Landschaften).
Spaeter: transparenter Himmel + Sternenhimmel / Quest-3-Skybox.

#### Nur oberer Halbraum

Option *oberhalb geometrischer Horizont*: zeigt y = 0 … H/2. Im Garten ist
der untere Teil fast immer Boden. Ausnahme: Berg mit Sicht nach unten.

#### Verdeckte Himmelsflaeche (Raumwinkel)

Nicht Pixel zaehlen (equirektangular verzerrt den Zenit). Mit Hoehe **h**
in Bogenmass: `dΩ = cos(h) · dh · dAz`. Obere Hemisphaere = `2π` sr.

Verdeckt: `(1 / 2π) ∫ sin(max(h(Az), 0)) dAz`. Bei konstantem h = 30°
sind das 50 %.

#### 360-Ansicht / Mini-Stellarium

Three.js-Kugel im Browser, **ohne Internet**: `three.module.js` liegt lokal
unter `app_mele/static/three/` und wird von NiceGUI ausgeliefert.

Oben umschalten: **1 Vorschau** · **2 Transparentes PNG** · **3 Original**
(oder Tasten 1/2/3). PNG ist erst aktiv, wenn zuvor exportiert wurde.
Ziehen = umsehen, Mausrad / +/− = Zoom (Blickwinkel, nicht Kameradistanz).

Sterne/Sternbilder/Messier: lokale SQLite (`data/catalogs/sky.sqlite`).
Einmal mit Internet: `python -m mele.catalog import`. Danach offline.
Mond/Planeten/Sonne: keine Tabelle, Positionen lokal aus Kepler/Meeus.

In der 360-Ansicht: Jetzt / Fotozeit / ±1h ±1d / Datum-Uhrzeit.
Klick auf Stern/Mond/DSO oeffnet Eigenschaften; Schalter **Bahn**
zeichnet den Tagesbogen: dick durchgezogen = Nacht, gestrichelt =
Daemmerung (±1 h um Sonnenauf-/-untergang), gepunktet = Tag.
Blass = hinter der Horizontmaske. **Stunden** setzt Marken + Uhrzeit
auf jeder vollen Stunde. **Anzeige**: Az/h-Gitter, Aequatorraster
(Stundenkreise + Deklination) und Ekliptik, Schritt 5°/10°.
Aequator und Ekliptik folgen Datum, Uhrzeit und Standort.
Einstellungen bleiben in `data/horizon/ui-prefs.json`.
Standort pro 360-Foto in `data/horizon/sites.json`. Beim erneuten
Oeffnen kommen die GPS-Werte zurueck. Handyfotos mit GPS-EXIF liegen
in `media/GPS-locations/` (nicht bei den 360-Panos in `media/`).

#### Wetter / Beobachtungsfenster

Eigene Seite wie die 360-Ansicht, gleicher Standort. Quelle:
GeoSphere Austria NWP v2 (1 km, stündlich, ~60 h): Bewoelkung, Wind,
Feuchte, Temperatur, Niederschlag. Abruf über den MeLE-Server, Cache
in `data/weather/`. Ohne Netz bleibt der letzte Stand. Quellenangabe
CC-BY 4.0. Seeing/Transparenz sind nicht enthalten.
Lokale Station (Ecowitt via `weather_server`) erscheint zusätzlich —
MeLE pullt `/api/current` und speist das Wetter-Journal.
"""


def build_ui(
    *,
    state: UiState,
    media_dir: Path,
    images_fn: Callable[[], list[Path]],
    on_select_image: Callable[[str], None],
    on_detect: Callable[[], None],
    on_save: Callable[[], None],
    on_pointer: Callable[..., None],
    on_clear_samples: Callable[[], None],
    on_clear_rejects: Callable[[], None],
    on_clear_suns: Callable[[], None],
    on_find_sun: Callable[[], None],
    on_undo_point: Callable[[], None],
    on_clear_points: Callable[[], None],
    on_clear_mask: Callable[[], None],
    on_export_transparent: Callable[[], None],
    on_export_fullres: Callable[[], None],
    on_toggle_sky_view: Callable[[], None],
    on_open_pano: Callable[[], None],
    on_open_weather: Callable[[], None],
    on_open_help: Callable[[], None],
    on_open_prefs: Callable[[], None],
    on_open_wiki: Callable[[], None],
    on_open_observe: Callable[[], None],
    on_open_tools: Callable[[], None],
    on_set_site: Callable[[float, float, str], None],
    on_start_synscan: Callable[[], None],
    on_start_nina: Callable[[], None],
    on_start_phd2: Callable[[], None],
    on_start_weather_server: Callable[[], None],
    on_open_guiding: Callable[[], None],
    locations_fn: Callable[[], list[tuple[str, str, float, float, str]]],
    active_location_id_fn: Callable[[], str],
    on_apply_location: Callable[[str], bool],
    on_save_location: Callable[[str, float, float], bool],
    geotagged_fn: Callable[[], list[tuple[str, float | None, float | None]]],
    on_gps_upload: Callable[..., None],
    preview_url_fn: Callable[[], str | None],
) -> None:
    ui.colors(primary="#1f4e5f")

    with ui.header().classes("items-center justify-between q-px-md"):
        ui.label("MeLE Astro-Computer").classes("text-h6")
        ui.label("Horizont / Norden").classes("text-caption")

    status_label = ui.label().classes("text-caption q-px-md")

    # Feste Drawer-Breiten (bei ~1920px Viewport):
    # links media ~280px, rechts tools ~420px, Mitte bekommt den Rest (flex).
    # Vorher: links w-1/5 (~20% ≈ 384px bei 1920), rechts fix 300px (zu schmal fuer Toggles).
    _MEDIA_DRAWER_PX = 280
    _TOOLS_DRAWER_PX = 460
    media_open = {"value": True}
    tools_open = {"value": False}

    def _apply_media_drawer() -> None:
        open_ = bool(media_open["value"])
        media_panel.set_visibility(open_)
        btn = state.refs.get("media_toggle")
        if btn is not None:
            try:
                btn.props(f'icon={"chevron_left" if open_ else "photo_library"}')
                btn.text = "Schliessen" if open_ else "Panoramas"
            except RuntimeError:
                pass

    def _toggle_media_drawer() -> None:
        media_open["value"] = not media_open["value"]
        _apply_media_drawer()

    def _apply_tools_drawer() -> None:
        open_ = bool(tools_open["value"])
        tools_panel.set_visibility(open_)
        btn = state.refs.get("tools_toggle")
        if btn is not None:
            try:
                btn.props(f'icon={"chevron_right" if open_ else "architecture"}')
                btn.text = "Schliessen" if open_ else "Horizont"
            except RuntimeError:
                pass

    def _toggle_tools_drawer() -> None:
        tools_open["value"] = not tools_open["value"]
        _apply_tools_drawer()

    with ui.row().classes("w-full no-wrap q-pa-md q-gutter-md items-start"):
        with ui.column().classes("q-gutter-xs").style(
            f"flex:0 0 {_MEDIA_DRAWER_PX}px; width:{_MEDIA_DRAWER_PX}px; "
            f"max-height:calc(100vh - 6rem); overflow:auto;"
        ) as media_panel:
            state.refs["media_panel"] = media_panel
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("Panoramas").classes("text-subtitle2")
                ui.button(
                    icon="chevron_left",
                    on_click=lambda: _toggle_media_drawer(),
                ).props("flat dense round").tooltip("Panorama-Liste einklappen")
            ui.label(str(media_dir)).classes("text-caption")
            ui.label("360-Fotos hier, GPS-Handyfotos in media/GPS-locations").classes("text-caption")
            file_box = ui.column().classes("w-full")

        # Zentrum waechst; Seiten-Drawers klappen ein und geben Breite frei
        with ui.column().classes("col q-gutter-none").style("flex:1 1 0%; min-width:0"):
            # Schlanke Toolbar: Drawer-Toggles + WLAN + App-Buttons
            with ui.row().classes("w-full items-center justify-end no-wrap q-gutter-sm"):
                media_toggle = ui.button(
                    "Panoramas",
                    icon="photo_library",
                    on_click=lambda: _toggle_media_drawer(),
                ).props("flat dense").tooltip(
                    "Panorama-Liste links ein- oder ausblenden"
                )
                state.refs["media_toggle"] = media_toggle
                wifi_label = ui.label("WLAN …").classes("text-caption")
                with wifi_label:
                    wifi_tip = ui.tooltip("WLAN-Status wird geladen …")
                state.refs["wifi_label"] = wifi_label
                state.refs["wifi_tooltip"] = wifi_tip
                tools_toggle = ui.button(
                    "Horizont",
                    icon="architecture",
                    on_click=lambda: _toggle_tools_drawer(),
                ).props("flat dense").tooltip(
                    "Horizont-/Standort-Werkzeuge rechts ein- oder ausblenden (Bild bleibt sichtbar)"
                )
                state.refs["tools_toggle"] = tools_toggle
                ui.button("360-Ansicht", icon="360", on_click=on_open_pano).props("flat dense").tooltip(
                    "Neues Fenster: Klick auf Sterne, Anzeige-Prefs, Mausrad zoomt. Lokal, kein Internet."
                )
                ui.button("Wetter", icon="cloud", on_click=on_open_weather).props("flat dense").tooltip(
                    "Neues Fenster: GeoSphere-Prognose + lokale Station (weather_server)."
                )
                ui.button("Hilfe", icon="help", on_click=on_open_help).props("flat dense").tooltip(
                    "App-Bedienung: Horizont, Einnorden, Hybrid, Wetter-Journal"
                )
                ui.button(icon="settings", on_click=on_open_prefs).props("flat dense round").tooltip(
                    "Preferences: CAPTURE / WORK / ARCHIVE Pfade (mele.yaml)"
                )
                ui.button("Wiki", icon="menu_book", on_click=on_open_wiki).props("flat dense").tooltip(
                    "Wissen, Inventar, Galerie — Markdown unter wiki/"
                )
                ui.button("Almanach", icon="event", on_click=on_open_observe).props("flat dense").tooltip(
                    "Sichtbarkeit Messier/Sterne · Tonight-Liste"
                )
                ui.button("Tools", icon="explore", on_click=on_open_tools).props("flat dense").tooltip(
                    "True North / Sonnenmeridian (offline)"
                )
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    weather_led = ui.html(
                        '<span style="display:inline-block;width:0.7em;height:0.7em;'
                        "border-radius:50%;background:#64748b;"
                        'box-shadow:inset 0 0 0 1px rgba(15,23,42,.55);"></span>'
                    )
                    state.refs["weather_server_led"] = weather_led
                    ui.button(
                        "WxServer",
                        icon="cloud_sync",
                        on_click=on_start_weather_server,
                    ).props("flat dense").tooltip(
                        "weather_server starten (Ecowitt→SQLite→:8765). "
                        "LED gruen = Prozess/API erreichbar. Autostart bleibt Task Scheduler."
                    )
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    nina_led = ui.html(
                        '<span style="display:inline-block;width:0.7em;height:0.7em;'
                        "border-radius:50%;background:#64748b;"
                        'box-shadow:inset 0 0 0 1px rgba(15,23,42,.55);"></span>'
                    )
                    state.refs["nina_led"] = nina_led
                    ui.button("NINA", icon="camera", on_click=on_start_nina).props("flat dense").tooltip(
                        "NINA starten. LED gruen = NINA.exe laeuft bereits."
                    )
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    synscan_led = ui.html(
                        '<span style="display:inline-block;width:0.7em;height:0.7em;'
                        "border-radius:50%;background:#64748b;"
                        'box-shadow:inset 0 0 0 1px rgba(15,23,42,.55);"></span>'
                    )
                    state.refs["synscan_led"] = synscan_led
                    ui.button("SynScan", icon="settings_remote", on_click=on_start_synscan).props(
                        "flat dense"
                    ).tooltip(
                        "SynScan Pro starten (Skywatcher-Montierung). LED gruen = laeuft bereits."
                    )
                with ui.row().classes("items-center no-wrap q-gutter-xs"):
                    phd2_led = ui.html(
                        '<span style="display:inline-block;width:0.7em;height:0.7em;'
                        "border-radius:50%;background:#64748b;"
                        'box-shadow:inset 0 0 0 1px rgba(15,23,42,.55);"></span>'
                    )
                    state.refs["phd2_led"] = phd2_led
                    ui.button("PHD2", icon="filter_center_focus", on_click=on_start_phd2).props(
                        "flat dense"
                    ).tooltip(
                        "PHD2 Guiding starten (ASI120). LED gruen = phd2.exe laeuft."
                    )
                    ui.button("Guiding", icon="open_in_new", on_click=on_open_guiding).props(
                        "flat dense"
                    ).tooltip("Guiding-Seite: ASI120-Bild, Loop, Mount-Pad")

            # Kontext-Box: Live | Forecast | Ort+Himmel
            with ui.card().classes("w-full q-pa-sm q-mb-sm").props("flat bordered") as safety_card:
                state.refs["weather_safety_card"] = safety_card
                with ui.row().classes("w-full items-center justify-between no-wrap q-mb-xs"):
                    ui.label("LIVE CONDITIONS").classes("text-caption text-weight-bold")
                    safety_badge = ui.label("UNKNOWN").classes("text-caption text-weight-bold")
                    state.refs["weather_safety_badge"] = safety_badge
                with ui.row().classes("w-full items-stretch no-wrap q-gutter-sm"):
                    with ui.column().classes("col q-gutter-none").style("min-width:0; flex:1.15"):
                        ui.label("Station").classes("text-caption text-grey-7")
                        safety_lines = ui.label("—").classes(
                            "text-caption font-mono whitespace-pre-wrap"
                        )
                        state.refs["weather_safety_lines"] = safety_lines
                        safety_reasons = ui.label("").classes("text-caption text-grey-7")
                        state.refs["weather_safety_reasons"] = safety_reasons
                    with ui.column().classes("col q-gutter-none").style("min-width:0; flex:1"):
                        ui.label("Prognose").classes("text-caption text-grey-7")
                        weather_forecast = ui.label("Wetter: —").classes(
                            "text-caption whitespace-pre-wrap"
                        )
                        state.refs["weather_label"] = weather_forecast
                    with ui.column().classes("col q-gutter-none").style("min-width:0; flex:1"):
                        ui.label("Ort & Himmel").classes("text-caption text-grey-7")
                        sky_cover_label = ui.label("Himmel: —").classes("text-caption")
                        state.refs["sky_cover_label"] = sky_cover_label
                        context_site = ui.label("Standort: —").classes(
                            "text-caption whitespace-pre-wrap"
                        )
                        state.refs["context_site_label"] = context_site

            # Hover-Koordinaten gehoeren zum Panorama-Bild
            cursor_label = ui.label("Maus ueber das Bild: Az / h und RA / Dec.").classes(
                "text-caption font-mono whitespace-pre-wrap text-grey-8"
            )

            image_box = ui.column().classes("w-full")

        with ui.column().classes("q-gutter-xs").style(
            f"flex:0 0 {_TOOLS_DRAWER_PX}px; width:{_TOOLS_DRAWER_PX}px; "
            f"max-height:calc(100vh - 6rem); overflow:auto;"
        ) as tools_panel:
            state.refs["tools_panel"] = tools_panel
            with ui.row().classes("w-full items-center justify-between no-wrap"):
                ui.label("Verfahren").classes("text-subtitle2")
                ui.button(
                    icon="chevron_right",
                    on_click=lambda: _toggle_tools_drawer(),
                ).props("flat dense round").tooltip("Werkzeuge einklappen")
            hint = ui.label("").classes("text-caption text-grey-7 q-mb-xs")
            state.refs["method_hint"] = hint
            def on_method(event) -> None:
                if event.value:
                    state.method = str(event.value)
                render_meta()
                render_status()

            def on_click_mode(event) -> None:
                if event.value:
                    state.click_mode = str(event.value)
                render_status()

            ui.toggle(
                {
                    "auto": "Auto",
                    "picker": "Farbpicker",
                    "hybrid": "Hybrid",
                    "draw": "Zeichnen",
                    "brush": "Pinsel",
                },
                value=state.method,
                on_change=on_method,
            )
            ui.toggle(
                {"tool": "Klick: Verfahren", "north": "Klick: Norden"},
                value=state.click_mode,
                on_change=on_click_mode,
            )

            def on_sky_view(event) -> None:
                state.above_horizon = bool(event.value)
                on_toggle_sky_view()

            ui.switch(
                "Nur oberhalb geometr. Horizont",
                value=state.above_horizon,
                on_change=on_sky_view,
            )
            detect_btn = ui.button("Horizont erkennen", icon="timeline", on_click=on_detect).props("unelevated")
            save_btn = ui.button("Profil speichern", icon="save", on_click=on_save).props("flat")
            ui.button("PNG/TIFF + Stellarium", icon="image", on_click=on_export_transparent).props("flat")
            ui.button("Vollaufloesung PNG", icon="hd", on_click=on_export_fullres).props("flat")
            north_label = ui.label().classes("text-body1 q-mt-md")
            range_label = ui.label().classes("text-caption")
            site_label = ui.label().classes("text-caption q-mt-sm")
            ui.label("Beobachterstandorte").classes("text-caption q-mt-sm")
            loc_select = ui.select(
                options={"": "Standort waehlen …"},
                value="",
            ).classes("w-full").props("dense")
            with ui.row().classes("w-full items-end no-wrap q-gutter-xs"):
                loc_name_in = ui.input("Name", placeholder="z.B. Garten, Sternwarte").classes("w-40").props("dense")
                ui.button("Uebernehmen", icon="place", on_click=lambda: _apply_selected_location()).props(
                    "flat dense"
                ).tooltip("Ausgewaehlten Listen-Standort in Breite/Laenge uebernehmen")
                ui.button("In Liste", icon="playlist_add", on_click=lambda: _save_named_location()).props(
                    "flat dense"
                ).tooltip(
                    "Koordinaten + aktuell gewaehltes Panorama unter Name speichern (fuer Session-Start)"
                )
            with ui.row().classes("w-full items-end no-wrap q-gutter-xs"):
                lat_in = ui.number("Breite", value=state.latitude_deg, format="%.6f").classes("w-28").props("dense")
                lon_in = ui.number("Laenge", value=state.longitude_deg, format="%.6f").classes("w-28").props("dense")
                ui.button("Speichern", icon="save", on_click=lambda: _save_typed_site()).props("flat dense").tooltip(
                    "Nach configs/mele.yaml schreiben (Default-Standort)"
                )
            map_btn = ui.button("Karte pruefen (OSM)", icon="map", on_click=lambda: _open_osm()).props("flat dense")
            site_select = ui.select(
                options={"": "Handyfoto in media/GPS-locations waehlen"},
                value="",
            ).classes("w-full").props("dense")
            ui.upload(
                label="Oder Datei waehlen / ablegen",
                auto_upload=True,
                on_upload=on_gps_upload,
            ).props('accept=".jpg,.jpeg,image/jpeg" dense').classes("w-full")
            ui.label(
                "Liste: Standort + optional verknuepftes 360-Foto. Beim Speichern muss das Panorama "
                "ausgewaehlt sein. Naechste Session laedt Standort und Foto automatisch."
            ).classes("text-caption")

            def _open_osm() -> None:
                if state.latitude_deg is None or state.longitude_deg is None:
                    ui.notify("Zuerst Standort setzen.", type="warning")
                    return
                url = (
                    f"https://www.openstreetmap.org/?mlat={state.latitude_deg:.6f}"
                    f"&mlon={state.longitude_deg:.6f}#map=18/"
                    f"{state.latitude_deg:.6f}/{state.longitude_deg:.6f}"
                )
                ui.run_javascript(f"window.open({url!r}, '_blank')")

            def _sync_site_inputs() -> None:
                lat_in.value = state.latitude_deg
                lon_in.value = state.longitude_deg
                map_btn.visible = state.latitude_deg is not None and state.longitude_deg is not None

            def _fill_location_select() -> None:
                options: dict[str, str] = {"": "Standort waehlen …"}
                for loc_id, label, lat, lon, pano_stem in locations_fn():
                    pano_note = f" · {pano_stem}" if pano_stem else ""
                    options[loc_id] = f"{label}  ({lat:.5f}, {lon:.5f}){pano_note}"
                active_id = active_location_id_fn()
                loc_select.options = options
                if active_id and active_id in options:
                    loc_select.value = active_id
                loc_select.update()

            def _apply_selected_location() -> None:
                loc_id = str(loc_select.value or "")
                if not loc_id:
                    ui.notify("Zuerst einen Standort in der Liste waehlen.", type="warning")
                    return
                if on_apply_location(loc_id):
                    _sync_site_inputs()
                    _fill_location_select()

            def _save_named_location() -> None:
                name = str(loc_name_in.value or "").strip()
                if not name:
                    # Falls Auswahl existiert, deren Label aktualisieren
                    loc_id = str(loc_select.value or "")
                    if loc_id:
                        for item_id, label, _lat, _lon, _stem in locations_fn():
                            if item_id == loc_id:
                                name = label
                                break
                if not name:
                    ui.notify("Namen fuer den Standort eingeben (z.B. Garten).", type="warning")
                    return
                if lat_in.value is None or lon_in.value is None:
                    ui.notify("Breite und Laenge setzen.", type="warning")
                    return
                if on_save_location(name, float(lat_in.value), float(lon_in.value)):
                    loc_name_in.value = ""
                    _sync_site_inputs()
                    _fill_location_select()

            def _save_typed_site() -> None:
                if lat_in.value is None or lon_in.value is None:
                    ui.notify("Breite und Laenge setzen oder Handyfoto waehlen.", type="warning")
                    return
                on_set_site(float(lat_in.value), float(lon_in.value), "config")
                _sync_site_inputs()

            def _fill_site_select() -> None:
                options = {"": "Handyfoto in media/GPS-locations waehlen"}
                for name, lat, lon in geotagged_fn():
                    if lat is not None and lon is not None:
                        options[name] = f"{name}  ({lat:.5f}, {lon:.5f})"
                    else:
                        options[name] = f"{name}  (kein GPS in EXIF)"
                site_select.options = options
                site_select.update()

            def _on_site_photo(event) -> None:
                name = str(event.value or "")
                if not name:
                    return
                for fname, lat, lon in geotagged_fn():
                    if fname != name:
                        continue
                    if lat is None or lon is None:
                        ui.notify(
                            f"{name} hat keine GPS-EXIF. Original vom Handy kopieren "
                            "(Ortung an, nicht teilen/exportieren).",
                            type="warning",
                            timeout=8000,
                        )
                        return
                    on_set_site(lat, lon, "exif")
                    _sync_site_inputs()
                    return
                ui.notify("Datei nicht gefunden.", type="warning")

            site_select.on_value_change(_on_site_photo)
            _fill_location_select()
            _fill_site_select()
            _sync_site_inputs()
            state.refs["sync_site_inputs"] = _sync_site_inputs
            state.refs["fill_site_select"] = _fill_site_select
            state.refs["fill_location_select"] = _fill_location_select
            method_box = ui.column().classes("w-full q-mt-sm")
            ui.separator()
            ui.label("Himmelsgrid").classes("text-subtitle2")

            def on_grid_toggle(event) -> None:
                state.show_grid = bool(event.value)
                _set_svg()

            def on_grid_step(event) -> None:
                try:
                    state.grid_step = int(event.value)
                except (TypeError, ValueError):
                    state.grid_step = 10
                _set_svg()

            ui.switch("Linien konstanter Hoehe/Azimut", value=state.show_grid, on_change=on_grid_toggle)
            ui.toggle({5: "5°", 10: "10°"}, value=state.grid_step, on_change=on_grid_step)
            table_box = ui.column().classes("w-full q-mt-md")

        _apply_media_drawer()
        _apply_tools_drawer()

    with ui.expansion("Berechnungen und Formeln", icon="functions").classes("w-full q-px-md q-pb-md"):
        ui.markdown(FORMULAS_MD)

    interactive = {"image": None}

    def _profile():
        return state.profile if profile_belongs_to(state.profile, state.image_path) else None

    def _overlay() -> str:
        pw, ph = state.preview_width, state.preview_height
        sw = state.source_width or pw
        sh = state.source_height or ph
        profile = _profile()
        samples = (
            [(s.preview_x, s.preview_y) for s in state.sky_samples]
            if state.method in {"picker", "hybrid"}
            else []
        )
        rejects = (
            [(s.preview_x, s.preview_y) for s in state.reject_samples]
            if state.method in {"picker", "hybrid"}
            else []
        )
        suns = []
        if state.method in {"picker", "hybrid", "auto"}:
            suns = [
                (excl.preview_x, excl.preview_y, excl.preview_radius) for excl in state.sun_excludes
            ]
        handles = []
        if state.method in {"draw", "hybrid"} and sw and sh and pw and ph:
            handles = [(x * pw / sw, y * ph / sh) for x, y in state.manual_points]
        mask_uri = ""
        if state.method == "brush" and state.mask is not None:
            mask_uri = mask_tint_data_uri(state.mask, ph if not state.above_horizon else ph)
        return overlay_svg(
            profile,
            pw,
            ph,
            state.north_x,
            sw,
            sh,
            state.show_grid,
            state.grid_step,
            samples,
            handles,
            mask_uri,
            suns,
            rejects,
        )

    def _set_svg() -> None:
        image = interactive.get("image")
        if image is None or not state.preview_width:
            return
        try:
            image.content = _overlay()
        except RuntimeError:
            interactive["image"] = None

    def _display_size() -> tuple[int, int]:
        pw, ph = state.preview_width, state.preview_height
        if state.above_horizon and ph:
            return pw, max(1, ph // 2)
        return pw, ph

    def _update_pointer(preview_x: float, preview_y: float) -> None:
        if not state.preview_width or not state.preview_height:
            return
        src_w = state.source_width or state.preview_width
        src_h = state.source_height or state.preview_height
        az, alt = preview_to_horizontal(
            preview_x,
            preview_y,
            state.preview_width,
            state.preview_height,
            src_w,
            src_h,
            state.north_x,
        )
        horizon_alt = None
        profile = _profile()
        if profile is not None and profile.points:
            horizon_alt = profile.altitude_at(az)
        cursor_label.text = format_pointer(
            az,
            alt,
            latitude_deg=state.latitude_deg,
            longitude_deg=state.longitude_deg,
            when=datetime.now(timezone.utc),
            horizon_alt=horizon_alt,
            include_site=False,
        )

    def render_files() -> None:
        try:
            file_box.clear()
        except RuntimeError:
            return
        paths = images_fn()
        with file_box:
            if not paths:
                ui.label("Keine JPG in media/.").classes("text-caption")
                return
            for path in paths:
                selected = state.image_path is not None and path == state.image_path
                extra = " bg-blue-1" if selected else ""
                ui.button(
                    on_click=lambda name=path.name: on_select_image(name),
                ).props("flat no-caps align=left").classes("w-full" + extra).set_text(path.name)

    def render_image() -> None:
        url = preview_url_fn()
        try:
            image_box.clear()
        except RuntimeError:
            return
        interactive["image"] = None
        with image_box:
            if not url or not state.preview_width:
                ui.label("Panorama waehlen.").classes("text-caption")
                return
            disp_w, disp_h = _display_size()

            def on_mouse(event) -> None:
                px = float(event.image_x)
                py = float(event.image_y)
                event_type = getattr(event, "type", "")
                buttons = int(getattr(event, "buttons", 0) or 0)
                if event_type in {"click", "mousedown", "mousemove", "mouseup"}:
                    on_pointer(
                        px,
                        py,
                        is_click=event_type == "click",
                        buttons=buttons,
                        event_type=event_type,
                    )
                _update_pointer(px, py)

            image = ui.interactive_image(
                url,
                content=_overlay(),
                size=(disp_w, disp_h),
                on_mouse=on_mouse,
                events=["click", "mousemove", "mousedown", "mouseup"],
                cross="#22c55e",
                sanitize=False,
            ).classes("w-full rounded")
            interactive["image"] = image

    def render_method_panel() -> None:
        try:
            method_box.clear()
        except RuntimeError:
            return
        with method_box:
            if state.method in {"picker", "hybrid"}:
                if state.method == "hybrid":
                    ui.label(
                        "1) Floor: Zeichnen oder 360°-Punktwolke. "
                        "2) Himmelsfarben klicken. 3) Horizont erkennen."
                    ).classes("text-caption")
                else:
                    ui.label("Klick setzt je nach Rolle: Himmel, Sonne oder Hauswand.").classes("text-caption")
                def on_picker_role(event) -> None:
                    state.picker_role = str(event.value or "sky")
                    render_status()

                ui.toggle(
                    {"sky": "Himmel", "sun": "Sonne ausnehmen", "reject": "Kein Himmel"},
                    value=state.picker_role,
                    on_change=on_picker_role,
                )
                ui.label(
                    f"{len(state.sky_samples)} Himmel (cyan), "
                    f"{len(state.reject_samples)} Ausschluss (rosa), "
                    f"{len(state.sun_excludes)} Sonne (orange)."
                    + (
                        f" Floor-Punkte: {len(state.manual_points)}."
                        if state.method == "hybrid"
                        else ""
                    )
                ).classes("text-caption")
                with ui.row().classes("flex-wrap q-gutter-xs"):
                    for sample in state.sky_samples:
                        ui.element("div").style(
                            f"width:18px;height:18px;border-radius:3px;"
                            f"background:rgb({sample.r},{sample.g},{sample.b});"
                            f"border:1px solid #334155;"
                        )
                    for sample in state.reject_samples:
                        ui.element("div").style(
                            f"width:18px;height:18px;border-radius:3px;"
                            f"background:rgb({sample.r},{sample.g},{sample.b});"
                            f"border:2px solid #fb7185;"
                        )
                ui.label("Hue-Toleranz (Grad)").classes("text-caption")
                ui.slider(min=0, max=40, step=1, value=state.hue_pad).on_value_change(
                    lambda e: setattr(state, "hue_pad", float(e.value))
                )
                ui.label("Saettigungs-Toleranz").classes("text-caption")
                ui.slider(min=0.02, max=0.5, step=0.02, value=state.sat_pad).on_value_change(
                    lambda e: setattr(state, "sat_pad", float(e.value))
                )
                ui.label("Helligkeits-Toleranz").classes("text-caption")
                ui.slider(min=0.02, max=0.5, step=0.02, value=state.val_pad).on_value_change(
                    lambda e: setattr(state, "val_pad", float(e.value))
                )
                ui.label("Sonnen-Radius").classes("text-caption")
                ui.slider(min=8, max=80, step=1, value=state.sun_radius_preview).on_value_change(
                    lambda e: setattr(state, "sun_radius_preview", float(e.value))
                )
                ui.button("Sonne automatisch", on_click=on_find_sun).props("flat dense")
                ui.button("Himmel loeschen", on_click=on_clear_samples).props("flat dense")
                ui.button("Ausschluss loeschen", on_click=on_clear_rejects).props("flat dense")
                ui.button("Sonne loeschen", on_click=on_clear_suns).props("flat dense")
                if state.method == "hybrid":
                    ui.separator()
                    ui.label(
                        f"Floor-Stuetzpunkte: {len(state.manual_points)} (gelb). "
                        "Im Hybrid-Modus setzt ein Klick Farben; Floor in Zeichnen/360 setzen."
                    ).classes("text-caption")
            elif state.method == "draw":
                ui.label(
                    f"{len(state.manual_points)} Stuetzpunkte (gelb). "
                    "Klick setzt, Klick auf Punkt loescht."
                ).classes("text-caption")
                ui.button("Letzten Punkt loeschen", on_click=on_undo_point).props("flat dense")
                ui.button("Zeichnung loeschen", on_click=on_clear_points).props("flat dense")
            elif state.method == "brush":
                ui.label("Pinsel = Himmel transparent, Radierer = Boden halten.").classes("text-caption")
                ui.switch(
                    "Radierer",
                    value=state.brush_erase,
                    on_change=lambda e: setattr(state, "brush_erase", bool(e.value)),
                )
                ui.label("Pinselgroesse").classes("text-caption")
                ui.slider(min=4, max=80, step=1, value=state.brush_radius).on_value_change(
                    lambda e: setattr(state, "brush_radius", float(e.value))
                )
                ui.button("Maske loeschen", on_click=on_clear_mask).props("flat dense")

    def render_meta() -> None:
        if state.method in {"draw", "brush"}:
            detect_btn.set_text("Nur Auto / Picker / Hybrid")
            detect_btn.disable()
        else:
            detect_btn.set_text("Erkenne ..." if state.detecting else "Horizont erkennen")
            if state.detecting:
                detect_btn.disable()
            else:
                detect_btn.enable()
        profile = _profile()
        if profile is None and state.mask is None:
            save_btn.disable()
        else:
            save_btn.enable()
        current = state.image_path.name if state.image_path else "kein Foto"
        north_label.text = f"{current}  |  Norden x = {state.north_x:.0f} px"
        if profile and profile.points:
            alts = [point.alt_deg for point in profile.points]
            blocked, free = sky_obstruction(profile)
            range_label.text = (
                f"{len(profile.points)} Punkte  |  h(Az) {min(alts):.1f} ... {max(alts):.1f} deg"
            )
            sky_cover_label.text = f"Himmel frei {free:.1f} %  ·  verdeckt {blocked:.1f} %"
        else:
            range_label.text = "Noch kein Horizont fuer dieses Foto."
            sky_cover_label.text = "Himmel: —"
        context_site = state.refs.get("context_site_label")
        if state.latitude_deg is None or state.longitude_deg is None:
            site_text = "Standort fehlt (Osmo-GPS ungueltig — configs/mele.yaml)."
            site_label.text = site_text
            if context_site is not None:
                try:
                    context_site.text = site_text
                except RuntimeError:
                    pass
        else:
            src = {
                "exif": "EXIF",
                "config": "yaml",
                "saved": "sites.json",
                "pano": "360-Ansicht",
            }.get(state.site_src, state.site_src)
            site_text = (
                f"Standort  {state.latitude_deg:.4f}°, {state.longitude_deg:.4f}°\n"
                f"{format_latitude(state.latitude_deg)}, {format_longitude(state.longitude_deg)}"
                f"  ({src})"
            )
            if state.photo_when is not None:
                site_text += state.photo_when.astimezone().strftime("\nPano %Y-%m-%d %H:%M")
            site_label.text = (
                f"Standort  {state.latitude_deg:.4f}°, {state.longitude_deg:.4f}°"
                f"  ·  {format_latitude(state.latitude_deg)}, {format_longitude(state.longitude_deg)}"
                f"  ({src})"
            )
            if state.photo_when is not None:
                site_label.text += state.photo_when.astimezone().strftime("  ·  Pano %Y-%m-%d %H:%M")
            if context_site is not None:
                try:
                    context_site.text = site_text
                except RuntimeError:
                    pass
        sync_site = state.refs.get("sync_site_inputs")
        if sync_site is not None:
            try:
                sync_site()
            except RuntimeError:
                pass
        fill_sites = state.refs.get("fill_site_select")
        if fill_sites is not None:
            try:
                fill_sites()
            except RuntimeError:
                pass
        render_method_panel()
        try:
            table_box.clear()
        except RuntimeError:
            return
        with table_box:
            if profile and profile.points:
                rows = [{"az": f"{az:.0f}", "alt": f"{alt:.1f}"} for az, alt in sample_profile(profile, 10.0)]
                ui.table(
                    columns=[
                        {"name": "az", "label": "Az", "field": "az"},
                        {"name": "alt", "label": "h / deg", "field": "alt"},
                    ],
                    rows=rows,
                ).classes("w-full")
        _set_svg()

    def render_status() -> None:
        status_label.text = state.status or f"Medien: {media_dir}"
        if state.click_mode == "north":
            hint.text = "Naechster Klick setzt Norden (gruene Linie) auf dem gewaehlten Foto."
        elif state.method == "picker":
            if state.picker_role == "sun":
                hint.text = "Klick auf die Sonne setzt einen Exclude-Kreis (kein Hindernis)."
            elif state.picker_role == "reject":
                hint.text = "Klick auf Hauswand/Fenster: diese Farbe ist kein Himmel."
            else:
                hint.text = "Klick ins Blau. Sonne extra ausnehmen, Wände als 'Kein Himmel'."
        elif state.method == "hybrid":
            hint.text = (
                "Hybrid: Floor aus Zeichnen/360, dann Blau klicken, dann Erkennen. "
                "Himmel = Floor-darueber ODER Farbe."
            )
        elif state.method == "draw":
            hint.text = (
                "Klick setzt einen Horizontpunkt. Profil speichern erzeugt die Linie. "
                "Genauer geht das als Punktwolke in der 360-Ansicht."
            )
        elif state.method == "brush":
            hint.text = "Ziehen mit gedrueckter Taste malt. Cyan = Himmel (wird transparent)."
        else:
            # Auto: kein dauerhafter Hinweistext mehr in der UI
            hint.text = ""

    def render() -> None:
        render_status()
        render_files()
        render_image()
        render_meta()

    def render_overlay_only() -> None:
        render_status()
        render_meta()

    state.refs["refresh"] = render
    state.refs["refresh_files"] = render_files
    state.refs["refresh_image"] = render_image
    state.refs["refresh_meta"] = render_overlay_only
    state.refs["refresh_overlay"] = _set_svg
    render()
