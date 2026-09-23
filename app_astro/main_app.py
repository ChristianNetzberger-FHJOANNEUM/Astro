"""NiceGUI Astro Session Manager."""

from __future__ import annotations

from pathlib import Path

from nicegui import app, run, ui

from app_astro.layout import build_ui
from app_astro.state import UiState
from core.catalog import BurstRow, Catalog, ImageRow, SessionRow
from core.config import load_app_settings, save_app_settings
from core.eclipse import PHASE_LABELS, format_c2_offset
from core.importer import ScanReport, scan_library
from core.siril_workspace import WorkspaceError, create_workspace, open_folder
from core.taxonomy import LibraryFolder, list_library_folders
from core.thumbs import thumb_url


def run_app(port: int | None = None) -> None:
    settings = load_app_settings()
    catalog = Catalog(settings.catalog_path)
    state = UiState()
    if port is None:
        port = settings.ui_port
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

    def library_root() -> Path:
        return settings.library_root

    folder_cache: list[LibraryFolder] = []

    def library_ok() -> bool:
        return state.nas_ok is not False

    def folders() -> list[LibraryFolder]:
        return list(folder_cache)

    def _annotate_folders(items: list[LibraryFolder]) -> list[LibraryFolder]:
        by_slug = {row.slug.casefold(): row for row in catalog.list_sessions()}
        for item in items:
            match = by_slug.get(item.name.casefold())
            if match is not None:
                item.imported = True
                item.session_slug = match.slug
                item.image_count = match.image_count
                if match.object:
                    item.object = match.object
                if match.equipment:
                    item.equipment = match.equipment
        return items

    def _probe_nas() -> tuple[bool, list[LibraryFolder]]:
        root = settings.library_root
        if not root.is_dir():
            return False, []
        return True, list_library_folders(root, settings.skip_dir_names, count_files=False)

    async def load_nas_folders() -> None:
        try:
            ok, items = await run.io_bound(_probe_nas)
        except OSError as exc:
            state.nas_ok = False
            state.status = f"NAS nicht erreichbar: {exc}"
            refresh_status()
            return
        state.nas_ok = ok
        folder_cache.clear()
        folder_cache.extend(_annotate_folders(items) if ok else items)
        if not ok:
            state.status = f"NAS offline: {settings.library_root}"
        fn = state.refs.get("refresh_sessions")
        if fn:
            fn()
        refresh_status()
        if state.page == "library":
            lib = state.refs.get("refresh_library")
            if lib:
                lib()

    def refresh() -> None:
        fn = state.refs.get("refresh")
        if fn:
            fn()

    def refresh_status() -> None:
        fn = state.refs.get("refresh_status")
        if fn:
            fn()

    def _refresh_selection() -> None:
        fn = state.refs.get("refresh_selection")
        if fn:
            fn()
        else:
            refresh()

    def _later(name: str) -> None:
        fn = state.refs.get(name)
        if fn:
            fn()

    def on_select_session(session_id: int) -> None:
        state.session_id = session_id
        state.burst_id = None
        _refresh_selection()
        ui.timer(0.05, lambda: _later("refresh_sessions"), once=True)

    def on_select_burst(burst_id: int) -> None:
        state.burst_id = burst_id
        fn = state.refs.get("refresh_details")
        if fn:
            fn()
        else:
            _refresh_selection()
        ui.timer(0.05, lambda: _later("refresh_list"), once=True)

    def on_filter_kind(value: str) -> None:
        state.kind_filter = value
        state.burst_id = None
        refresh()

    def on_filter_phase(value: str) -> None:
        state.phase_filter = value
        state.burst_id = None
        refresh()

    def on_group_by(value: str) -> None:
        state.group_by = value
        fn = state.refs.get("refresh_sessions") or refresh
        fn()

    def _format_reports(reports: list[ScanReport]) -> str:
        lines: list[str] = []
        for report in reports:
            lines.append(
                f"{report.session_slug}: {report.captures} Aufnahmen, "
                f"{report.bursts} Bursts, {report.singles} Einzel"
            )
            if report.time_first:
                lines.append(
                    f"  Zeit {report.time_first} -> {report.time_last} ({report.datetime_src})"
                )
            lines.extend(f"  {msg}" for msg in report.messages)
        return "\n".join(lines) or "Scan abgeschlossen."

    def _scan_job(slugs: list[str] | None) -> list[ScanReport]:
        return scan_library(settings, catalog=None, slugs=slugs)

    async def _run_scan(slugs: list[str] | None = None) -> None:
        if state.scanning:
            ui.notify("Scan laeuft bereits.", type="warning")
            return
        state.scanning = True
        label = ", ".join(slugs) if slugs else "alle Sessions"
        state.status = f"Scanne NAS ({label}) ..."
        refresh_status()
        ui.notify("NAS-Scan gestartet.", type="info")
        try:
            reports = await run.io_bound(_scan_job, slugs)
            state.status = _format_reports(reports)
            rows = sessions()
            if rows and (state.session_id is None or catalog.get_session(state.session_id) is None):
                state.session_id = rows[0].id
            state.burst_id = None
            ui.notify("NAS-Scan abgeschlossen.", type="positive")
        except OSError as exc:
            state.status = f"Scan fehlgeschlagen: {exc}"
            ui.notify(str(exc), type="negative")
        finally:
            state.scanning = False
            refresh()

    async def on_scan() -> None:
        await _run_scan(None)

    async def on_scan_folder(name: str) -> None:
        await _run_scan([name])

    def on_save_settings(raw_path: str) -> None:
        candidate = Path(raw_path.strip())
        if not raw_path.strip():
            ui.notify("NAS-Root darf nicht leer sein.", type="warning")
            return
        settings.library_root = candidate
        save_app_settings(settings)
        state.status = f"NAS-Root gespeichert: {candidate}"
        ui.notify(state.status, type="positive")
        refresh()
        ui.timer(0.05, load_nas_folders, once=True)

    def on_open_folder(path: str) -> None:
        target = Path(path)
        if not target.exists():
            ui.notify(f"Ordner nicht gefunden: {path}", type="warning")
            return
        open_folder(target)

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
            library_root_fn=library_root,
            library_ok_fn=library_ok,
            catalog_path=settings.catalog_path,
            sessions_fn=sessions,
            current_session_fn=current_session,
            bursts_fn=bursts,
            current_burst_fn=current_burst,
            images_fn=images,
            folders_fn=folders,
            media_url=lambda p: thumb_url(p, thumbs_dir),
            phase_label=lambda key: PHASE_LABELS.get(key, key),
            format_c2=format_c2_offset,
            on_scan=on_scan,
            on_scan_folder=on_scan_folder,
            on_select_session=on_select_session,
            on_select_burst=on_select_burst,
            on_filter_kind=on_filter_kind,
            on_filter_phase=on_filter_phase,
            on_group_by=on_group_by,
            on_save_settings=on_save_settings,
            on_open_folder=on_open_folder,
            on_siril_workspace=on_siril_workspace,
            on_open_workspace=on_open_workspace,
            workspace_path_fn=catalog.get_workspace_path,
        )
        ui.timer(0.05, load_nas_folders, once=True)

    # Wie Fitness: UI als root, Browser auf 127.0.0.1 oeffnen (nicht 0.0.0.0).
    ui.run(
        root=index,
        title="Astro Session Manager",
        port=port,
        host="127.0.0.1",
        show=True,
        reload=False,
    )
