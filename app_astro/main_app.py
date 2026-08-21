"""NiceGUI Astro Session Manager."""

from __future__ import annotations

from pathlib import Path

from nicegui import app, ui

from app_astro.layout import build_ui
from app_astro.state import UiState
from core.catalog import BurstRow, Catalog, ImageRow, SessionRow
from core.config import load_app_settings
from core.eclipse import PHASE_LABELS, format_c2_offset
from core.importer import scan_library
from core.thumbs import thumb_url
from core.siril_workspace import WorkspaceError, create_workspace, open_folder


def run(port: int | None = None) -> None:
    settings = load_app_settings()
    catalog = Catalog(settings.catalog_path)
    state = UiState()
    if port is None:
        port = settings.ui_port

    library_ok = settings.library_root.is_dir()
    thumbs_dir = settings.catalog_path.parent / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    app.add_static_files("/thumbs", thumbs_dir)

    def sessions() -> list[SessionRow]:
        return catalog.list_sessions()

    def current_session() -> SessionRow | None:
        if state.session_id is None:
            rows = sessions()
            if not rows:
                return None
            state.session_id = rows[0].id
        return catalog.get_session(state.session_id)

    def bursts() -> list[BurstRow]:
        session = current_session()
        if session is None:
            return []
        kind = None if state.kind_filter == "all" else state.kind_filter
        phase = None if state.phase_filter == "all" else state.phase_filter
        return catalog.list_bursts(session.id, kind=kind, phase=phase)

    def current_burst() -> BurstRow | None:
        if state.burst_id is not None:
            found = catalog.get_burst(state.burst_id)
            if found is not None:
                return found
        rows = bursts()
        if not rows:
            state.burst_id = None
            return None
        state.burst_id = rows[0].id
        return rows[0]

    def images() -> list[ImageRow]:
        burst = current_burst()
        if burst is None:
            return []
        return catalog.list_images(burst.id)

    def refresh() -> None:
        fn = state.refs.get("refresh")
        if fn:
            fn()

    def on_select_session(session_id: int) -> None:
        state.session_id = session_id
        state.burst_id = None
        refresh()

    def on_select_burst(burst_id: int) -> None:
        state.burst_id = burst_id
        fn = state.refs.get("refresh_selection") or refresh
        fn()

    def on_filter_kind(value: str) -> None:
        state.kind_filter = value
        state.burst_id = None
        refresh()

    def on_filter_phase(value: str) -> None:
        state.phase_filter = value
        state.burst_id = None
        refresh()

    def on_scan() -> None:
        state.status = "Scanne NAS ..."
        refresh()
        reports = scan_library(settings, catalog)
        lines = []
        for report in reports:
            lines.append(
                f"{report.session_slug}: {report.captures} Aufnahmen, "
                f"{report.bursts} Bursts, {report.singles} Einzel"
            )
            if report.time_first:
                lines.append(
                    f"  Zeit {report.time_first} -> {report.time_last} ({report.datetime_src})"
                )
            lines.extend(f"  {m}" for m in report.messages)
        state.status = "\n".join(lines) or "Scan abgeschlossen."
        rows = sessions()
        if rows and (state.session_id is None or catalog.get_session(state.session_id) is None):
            state.session_id = rows[0].id
        state.burst_id = None
        refresh()
        ui.notify("NAS-Scan abgeschlossen", type="positive")

    def on_siril_workspace() -> None:
        session = current_session()
        burst = current_burst()
        if session is None or burst is None:
            ui.notify("Kein Burst ausgewaehlt", type="warning")
            return
        frames = images()
        try:
            result = create_workspace(
                session,
                burst,
                frames,
                work_subdir=settings.siril_work_subdir,
            )
            catalog.upsert_workspace(
                burst.id, str(result.path), result.link_mode, result.linked
            )
            ui.notify(
                f"Burst {burst.burst_no:03d}: {result.linked} Links ({result.link_mode})",
                type="positive",
            )
            fn = state.refs.get("refresh_selection") or refresh
            fn()
        except WorkspaceError as exc:
            ui.notify(str(exc), type="negative")
        except OSError as exc:
            ui.notify(f"Workspace fehlgeschlagen: {exc}", type="negative")

    def on_open_workspace() -> None:
        burst = current_burst()
        if burst is None:
            ui.notify("Kein Burst ausgewaehlt", type="warning")
            return
        path = catalog.get_workspace_path(burst.id)
        if not path:
            ui.notify("Zuerst Siril-Workspace erzeugen", type="warning")
            return
        open_folder(Path(path))

    def index() -> None:
        build_ui(
            state=state,
            library_root=settings.library_root,
            library_ok=library_ok,
            catalog_path=settings.catalog_path,
            sessions_fn=sessions,
            current_session_fn=current_session,
            bursts_fn=bursts,
            current_burst_fn=current_burst,
            images_fn=images,
            media_url=lambda p: thumb_url(p, thumbs_dir),
            phase_label=lambda key: PHASE_LABELS.get(key, key),
            format_c2=format_c2_offset,
            on_scan=on_scan,
            on_select_session=on_select_session,
            on_select_burst=on_select_burst,
            on_filter_kind=on_filter_kind,
            on_filter_phase=on_filter_phase,
            on_siril_workspace=on_siril_workspace,
            on_open_workspace=on_open_workspace,
            workspace_path_fn=catalog.get_workspace_path,
        )

    # Wie Fitness: UI als root, Browser auf 127.0.0.1 oeffnen (nicht 0.0.0.0).
    ui.run(
        root=index,
        title="Astro Session Manager",
        port=port,
        host="127.0.0.1",
        show=True,
        reload=False,
    )
