"""Store loader: upload-knop, BRO-mappad invoer, close-knop."""

from __future__ import annotations

import logging
from pathlib import Path

from nicegui import events, ui

from pastasdash_v2.state.persistence import AppState
from pastasdash_v2.state.store import STORE
from pastasdash_v2.tasks import run_in_thread

log = logging.getLogger(__name__)


def render_store_loader() -> None:
    """Render het complete laad-paneel."""
    with ui.card().classes("w-full"):
        ui.label("PastaStore laden").classes("text-lg font-medium")

        with ui.tabs().classes("w-full") as tabs:
            tab_upload = ui.tab("Upload ZIP", icon="upload_file")
            tab_path = ui.tab("Pad op schijf", icon="folder_open")
            tab_recent = ui.tab("Recent", icon="history")

        with ui.tab_panels(tabs, value=tab_upload).classes("w-full"):
            with ui.tab_panel(tab_upload):
                _render_upload()
            with ui.tab_panel(tab_path):
                _render_path_input()
            with ui.tab_panel(tab_recent):
                _render_recent()

        # status
        status_row = ui.row().classes("items-center gap-2 mt-4")

        def _refresh_status() -> None:
            status_row.clear()
            with status_row:
                if STORE.is_loaded:
                    ui.icon("check_circle", color="positive").classes("text-xl")
                    ui.label(f"Geladen: {STORE.display_name}").classes("font-medium")
                    ui.button("Sluiten", icon="close", on_click=_close).props("flat color=negative")
                else:
                    ui.icon("info", color="grey").classes("text-xl")
                    ui.label("Geen store geladen").classes("opacity-75")

        _refresh_status()
        STORE.on_change(_refresh_status)


def _close() -> None:
    STORE.close()
    ui.notify("Store gesloten", type="info")


def _render_upload() -> None:
    ui.label("Upload een .pastastore-, .zip- of BRO Loket-export-ZIP.").classes("text-sm opacity-75")

    async def _handle_upload(e: events.UploadEventArguments) -> None:
        blob = e.content.read()
        name = e.name

        async def _load() -> None:
            STORE.load_from_zip_bytes(blob, name)

        try:
            await run_in_thread(f"Laden: {name}", _load_sync, blob, name, notify=True)
        except Exception as exc:  # noqa: BLE001
            ui.notify(f"Laden mislukt: {exc}", type="negative", timeout=8000)

    ui.upload(label="Sleep ZIP hier of klik om te kiezen", on_upload=_handle_upload, auto_upload=True).props(
        "accept=.zip,.pastastore"
    ).classes("w-full")


def _load_sync(blob: bytes, name: str) -> None:
    STORE.load_from_zip_bytes(blob, name)


def _render_path_input() -> None:
    ui.label("Geef een pad op schijf naar een ZIP-bestand of een uitgepakte BRO Loket-map.").classes(
        "text-sm opacity-75"
    )
    last = AppState.get("last_store_path", "")
    path_input = ui.input(label="Pad", value=last, placeholder="C:/...").classes("w-full")

    async def _load() -> None:
        path = path_input.value.strip() if path_input.value else ""
        if not path:
            ui.notify("Voer eerst een pad in.", type="warning")
            return
        if not Path(path).exists():
            ui.notify(f"Pad bestaat niet: {path}", type="negative")
            return
        try:
            await run_in_thread(f"Laden: {Path(path).name}", STORE.load_from_path, path, notify=True)
        except Exception as exc:  # noqa: BLE001
            ui.notify(f"Laden mislukt: {exc}", type="negative", timeout=8000)

    ui.button("Laden", icon="play_arrow", on_click=_load).props("color=primary").classes("mt-2")


def _render_recent() -> None:
    last = AppState.get("last_store_path")
    if not last:
        ui.label("Nog geen recente stores.").classes("opacity-75 italic")
        return
    exists = Path(last).exists()
    with ui.row().classes("items-center gap-2"):
        ui.icon("history")
        ui.label(last).classes("font-mono text-sm")
        if not exists:
            ui.badge("ontbreekt", color="negative")

    if exists:
        async def _reload() -> None:
            try:
                await run_in_thread(
                    f"Laden: {Path(last).name}", STORE.load_from_path, last, notify=True
                )
            except Exception as exc:  # noqa: BLE001
                ui.notify(f"Laden mislukt: {exc}", type="negative", timeout=8000)

        ui.button("Opnieuw openen", icon="refresh", on_click=_reload).classes("mt-2")
