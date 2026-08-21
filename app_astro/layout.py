"""Haupt-UI: Sessions | Burst-Liste | Details."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import ui

from app_astro.state import UiState
from core.catalog import BurstRow, ImageRow, SessionRow
from core.eclipse import PHASE_LABELS


def _fmt_dt(value: str | None) -> str:
    if not value:
        return "-"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _c2_range(burst: BurstRow, format_c2: Callable[[float | None], str]) -> str:
    start = format_c2(burst.c2_offset_start_s)
    end = format_c2(burst.c2_offset_end_s)
    if start and end and start != end:
        return f"{start} ... {end}"
    return start or end or ""


def build_ui(
    *,
    state: UiState,
    library_root: Path,
    library_ok: bool,
    catalog_path: Path,
    sessions_fn: Callable[[], list[SessionRow]],
    current_session_fn: Callable[[], SessionRow | None],
    bursts_fn: Callable[[], list[BurstRow]],
    current_burst_fn: Callable[[], BurstRow | None],
    images_fn: Callable[[], list[ImageRow]],
    media_url: Callable[[str | None], str | None],
    phase_label: Callable[[str], str],
    format_c2: Callable[[float | None], str],
    on_scan: Callable[[], None],
    on_select_session: Callable[[int], None],
    on_select_burst: Callable[[int], None],
    on_filter_kind: Callable[[str], None],
    on_filter_phase: Callable[[str], None],
    on_siril_workspace: Callable[[], None],
    on_open_workspace: Callable[[], None],
    workspace_path_fn: Callable[[int], str | None],
) -> None:
    ui.colors(primary="#3d5a80")

    with ui.header().classes("items-center justify-between q-px-md"):
        ui.label("Astro Session Manager").classes("text-h6")
        with ui.row().classes("items-center q-gutter-sm"):
            ui.label(str(library_root)).classes("text-caption")
            if not library_ok:
                ui.badge("NAS offline", color="orange")
            ui.button("NAS scannen", icon="sync", on_click=on_scan).props("unelevated")

    status_label = ui.label().classes("text-caption q-px-md whitespace-pre-line")

    with ui.row().classes("w-full no-wrap q-pa-md q-gutter-md"):
        with ui.column().classes("w-1/5"):
            session_box = ui.column().classes("w-full")
        with ui.column().classes("w-1/2"):
            with ui.row().classes("w-full items-center q-gutter-sm"):
                ui.select(
                    {"all": "Alle", "burst": "Nur Bursts", "single": "Nur Einzelbilder"},
                    value=state.kind_filter,
                    label="Typ",
                    on_change=lambda e: on_filter_kind(str(e.value)),
                ).classes("w-40")
                phase_options = {"all": "Alle Phasen"}
                phase_options.update({k: v for k, v in PHASE_LABELS.items() if k})
                ui.select(
                    phase_options,
                    value=state.phase_filter,
                    label="Phase",
                    on_change=lambda e: on_filter_phase(str(e.value)),
                ).classes("w-56")
                count_label = ui.label().classes("text-caption")
            with ui.scroll_area().classes("w-full h-[70vh]"):
                grid_box = ui.column().classes("w-full")
        with ui.column().classes("w-1/3"):
            detail_box = ui.column().classes("w-full")

    def render_sessions() -> None:
        session_box.clear()
        session_rows = sessions_fn()
        current = current_session_fn()
        with session_box:
            ui.label("Sessions").classes("text-subtitle2")
            if not session_rows:
                ui.label("Noch keine Session. NAS scannen.").classes("text-caption")
            for row in session_rows:
                selected_session = current is not None and row.id == current.id
                extra = " bg-blue-1" if selected_session else ""
                ui.button(
                    on_click=lambda sid=row.id: on_select_session(sid),
                ).props("flat no-caps align=left").classes("w-full" + extra).set_text(
                    f"{row.title}\n{row.slug} ? {row.image_count} Fotos ? {row.burst_count} Gruppen"
                )

    def render_list() -> None:
        grid_box.clear()
        burst_rows = bursts_fn()
        selected = current_burst_fn()
        count_label.text = f"{len(burst_rows)} Gruppen"
        with grid_box:
            if not burst_rows:
                ui.label("Keine Gruppen in dieser Filterung.").classes("text-caption")
                return
            for burst in burst_rows:
                is_sel = selected is not None and burst.id == selected.id
                extra = " bg-blue-1" if is_sel else ""
                bits = [burst.drive_guess, phase_label(burst.phase)]
                extra_c2 = _c2_range(burst, format_c2)
                if extra_c2:
                    bits.append(extra_c2)
                line2 = " ? ".join(b for b in bits if b)
                label = (
                    f"Burst {burst.burst_no:03d}  ?  {burst.frame_count} Frames\n"
                    f"{line2}\n"
                    f"{_fmt_dt(burst.start_dt)}"
                )
                ui.button(
                    on_click=lambda bid=burst.id: on_select_burst(bid),
                ).props("flat no-caps align=left").classes("w-full q-mb-xs" + extra).set_text(label)

    def render_details() -> None:
        detail_box.clear()
        selected = current_burst_fn()
        image_rows = images_fn()
        with detail_box:
            ui.label("Details").classes("text-subtitle2")
            if selected is None:
                ui.label("Burst auswaehlen.").classes("text-caption")
                return
            first = image_rows[0] if image_rows else None
            preview_slot = ui.column().classes("w-full")
            ui.label(f"Burst {selected.burst_no:03d}").classes("text-h6")
            ui.markdown(
                "\n".join(
                    [
                        f"- Typ: **{selected.kind}** / {selected.drive_guess or '-'}",
                        f"- Frames: **{selected.frame_count}**",
                        f"- Phase: **{phase_label(selected.phase) or '-'}**",
                        f"- {_c2_range(selected, format_c2) or 'kein C2-Offset'}",
                        f"- {_fmt_dt(selected.start_dt)} -> {_fmt_dt(selected.end_dt)}",
                    ]
                )
            )
            with ui.row().classes("q-gutter-sm q-mt-sm"):
                ui.button("Siril-Workspace", icon="folder", on_click=on_siril_workspace).props("unelevated")
                ui.button("Ordner oeffnen", icon="open_in_new", on_click=on_open_workspace).props("flat")
            ws = workspace_path_fn(selected.id)
            if ws:
                ui.label(ws).classes("text-caption")
            if first:
                ui.separator()
                ui.markdown(
                    "\n".join(
                        [
                            f"- Camera: {first.camera or '-'}",
                            f"- Lens: {first.lens or '-'}",
                            f"- Brennweite: {first.focal_length or '-'} mm",
                            f"- Belichtung: {first.exposure or '-'}",
                            f"- ISO: {first.iso or '-'}",
                            f"- Blende: {first.aperture or '-'}",
                            f"- RAW: `{Path(first.filepath).name}`",
                        ]
                    )
                )
            if image_rows:
                rows = [
                    {
                        "nr": img.burst_index,
                        "datei": Path(img.filepath).name,
                        "zeit": _fmt_dt(img.datetime),
                        "c2": format_c2(img.c2_offset_s),
                        "exp": img.exposure,
                    }
                    for img in image_rows[:200]
                ]
                ui.table(
                    columns=[
                        {"name": "nr", "label": "#", "field": "nr"},
                        {"name": "datei", "label": "Datei", "field": "datei"},
                        {"name": "zeit", "label": "Zeit", "field": "zeit"},
                        {"name": "c2", "label": "C2", "field": "c2"},
                        {"name": "exp", "label": "Belichtung", "field": "exp"},
                    ],
                    rows=rows,
                ).classes("w-full q-mt-md")

        jpg = selected.preview_jpg if selected is not None else None

        def load_preview() -> None:
            url = media_url(jpg)
            if not url:
                return
            preview_slot.clear()
            with preview_slot:
                ui.image(url).classes("w-full rounded")

        ui.timer(0.05, load_preview, once=True)

    def render() -> None:
        status_label.text = state.status or f"Katalog: {catalog_path}"
        render_sessions()
        render_list()
        render_details()

    def render_selection() -> None:
        render_list()
        render_details()

    state.refs["refresh"] = render
    state.refs["refresh_selection"] = render_selection
    render()
