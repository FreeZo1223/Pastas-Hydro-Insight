"""Model-pagina: bestaand model bekijken of nieuw model fitten."""

from __future__ import annotations

import logging
from dataclasses import asdict

from nicegui import ui

from pastasdash_v2.components.header import render_header
from pastasdash_v2.components.plots import (
    clean_fig, empty_figure, model_diagnostics_figure, model_results_figure,
)
from pastasdash_v2.compute.fitting import FitOptions, fit_model
from pastasdash_v2.compute.timeseries import model_summary
from pastasdash_v2.state.store import STORE
from pastasdash_v2.tasks import run_in_thread

log = logging.getLogger(__name__)


def render() -> None:
    render_header(active_tab="model")
    if not STORE.is_loaded:
        _empty()
        return

    ui_state = STORE.ui_state
    oseries_names = STORE.oseries_names()
    model_names = STORE.model_names()
    last_selected = ui_state.get("model.selected") or (model_names[0] if model_names else None) or (
        oseries_names[0] if oseries_names else None
    )

    with ui.column().classes("w-full p-4 gap-4"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.label("Peilbuis / model:").classes("font-medium")
            select = (
                ui.select(options=oseries_names, value=last_selected, with_input=True)
                .classes("min-w-80")
            )
            ui.label("(modellen gemarkeerd met ★ hebben een gefit model)").classes(
                "text-xs opacity-75"
            )

        plot_container = ui.column().classes("w-full")
        info_container = ui.column().classes("w-full")

        # ── fit-controls ──────────────────────────────────────────────────
        with ui.card().classes("w-full"):
            ui.label("Model fitten").classes("text-lg font-medium")
            with ui.row().classes("gap-3 items-end"):
                rfunc = ui.select(
                    options=["Gamma", "Exponential", "DoubleExponential", "Hantush"],
                    value=ui_state.get("model.rfunc", "Gamma"),
                    label="Respons-functie",
                ).classes("min-w-40")
                noise = ui.switch(
                    "Noise model", value=ui_state.get("model.noise", True)
                )
                tmin = ui.input(
                    label="tmin (optioneel, YYYY-MM-DD)",
                    value=ui_state.get("model.tmin", ""),
                ).classes("w-44")
                tmax = ui.input(
                    label="tmax (optioneel)", value=ui_state.get("model.tmax", "")
                ).classes("w-44")

                async def _on_fit() -> None:
                    name = select.value
                    if not name:
                        ui.notify("Selecteer eerst een peilbuis.", type="warning")
                        return
                    opts = FitOptions(
                        rfunc=rfunc.value,
                        noise_model=noise.value,
                        tmin=tmin.value or None,
                        tmax=tmax.value or None,
                    )
                    ui_state.set("model.rfunc", opts.rfunc)
                    ui_state.set("model.noise", opts.noise_model)
                    ui_state.set("model.tmin", opts.tmin or "")
                    ui_state.set("model.tmax", opts.tmax or "")
                    success, msg, _ml = await run_in_thread(
                        f"Fit model: {name}", fit_model, name, opts, notify=False
                    )
                    if success:
                        ui.notify(msg, type="positive")
                        _redraw(name)
                    else:
                        ui.notify(msg, type="negative", timeout=8000)

                ui.button("Fit / refit", icon="play_arrow", on_click=_on_fit).props("color=primary")

        def _redraw(name: str | None) -> None:
            plot_container.clear()
            info_container.clear()
            if not name:
                with plot_container:
                    ui.plotly(clean_fig(empty_figure("Selecteer een peilbuis")))
                return
            ui_state.set("model.selected", name)

            with plot_container:
                if name in STORE.model_names():
                    try:
                        ml = STORE.pstore.get_models(name)
                        ui.label("Resultaten").classes("text-lg font-medium")
                        ui.plotly(clean_fig(model_results_figure(ml))).classes("w-full")
                        ui.label("Diagnostiek").classes("text-lg font-medium mt-4")
                        ui.plotly(clean_fig(model_diagnostics_figure(ml))).classes("w-full")
                    except Exception as exc:  # noqa: BLE001
                        log.exception("Model laden faalde")
                        ui.plotly(clean_fig(empty_figure(f"Model laden faalde: {exc}")))
                else:
                    ui.plotly(clean_fig(empty_figure(
                        f"Nog geen model voor '{name}'. Klik 'Fit / refit' om er een te bouwen."
                    )))

            with info_container:
                summary = model_summary(STORE.store_key, name) if name in STORE.model_names() else {}
                if summary:
                    with ui.card().classes("w-full"):
                        ui.label("Samenvatting").classes("text-lg font-medium")
                        with ui.row().classes("gap-8"):
                            for label, key, fmt in [
                                ("R²", "rsq", "{:.3f}"),
                                ("EVP", "evp", "{:.1f}%"),
                                ("# observaties", "n_obs", "{:d}"),
                                ("tmin", "tmin", "{}"),
                                ("tmax", "tmax", "{}"),
                            ]:
                                v = summary.get(key)
                                if v is None:
                                    continue
                                with ui.column():
                                    ui.label(label).classes("text-sm opacity-75")
                                    try:
                                        ui.label(fmt.format(v)).classes("text-lg font-medium")
                                    except (ValueError, TypeError):
                                        ui.label(str(v)).classes("text-lg font-medium")

        select.on_value_change(lambda _e: _redraw(select.value))
        _redraw(last_selected)


def _empty() -> None:
    with ui.card().classes("w-full max-w-xl mx-auto mt-8"):
        ui.label("Laad eerst een PastaStore op de Start-pagina.").classes("text-lg")
        ui.link("→ Start", target="/").classes("text-blue-600")
