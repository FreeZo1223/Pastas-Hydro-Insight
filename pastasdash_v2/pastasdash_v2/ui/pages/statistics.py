"""Statistics-pagina: Menyanthes 'Groundwater Level Statistics' replica.

Toont:
- Selectie-tabel met peilbuizen + statistieken (GT/MLGL/MG/MSGL/MHGL/surf.l.)
- Groundwater Hydrograph (overlay van geselecteerde reeksen)
- Frequency of Exceedance plot (per buis + gemiddelde)
- Regime Curve (gemiddelde per maand)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from nicegui import ui

from pastasdash_v2.core.statistics import average_foe, gw_stats
from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import get_oseries
from pastasdash_v2.ui.components.plots import (
    clean_fig,
    empty_figure,
    foe_figure,
    regime_curve_figure,
    timeseries_overlay,
)
from pastasdash_v2.ui.shell import geselecteerd, pagina

log = logging.getLogger(__name__)


def _inhoud() -> None:
    with ui.column().classes("w-full p-4 gap-4"):
        if not STORE.is_loaded:
            _render_empty_state()
            return
        _render_content()


def _render_empty_state() -> None:
    with ui.card().classes("w-full max-w-2xl mx-auto"):
        ui.icon("info", size="2em").classes("text-blue-500")
        ui.label("Nog geen PastaStore geladen").classes("text-xl font-medium")
        ui.label("Ga naar Start om een store te laden.").classes("opacity-75")
        ui.link("→ Naar Start", target="/").classes("text-blue-600 mt-2")


def _render_content() -> None:
    ui_state = STORE.ui_state
    show_avg_foe: bool = ui_state.get("statistics.show_avg_foe", True)
    relative_to_surface: bool = ui_state.get("statistics.rel_to_surface", False)

    # De peilbuiskeuze komt uit de zijbalk en geldt voor álle weergaven. De
    # tabel hieronder is dus een afleesvenster, geen tweede keuzelijst.
    selected = geselecteerd()

    df = STORE.oseries()
    all_names = list(df.index)

    # Bereken statistieken voor alle peilbuizen één keer (gecached)
    stats_rows = [_stats_row(name) for name in all_names]

    with ui.row().classes("w-full gap-4 items-stretch"):
        # ── Linkerkolom: statistieken-tabel ───────────────────────────────
        with ui.column().classes("flex-1 min-w-0 gap-2"):
            ui.label("Grondwaterstatistiek").classes("peil-label")
            ui.label(
                "GxG en grondwatertrap per peilbuis. De grafieken rechts volgen "
                "je selectie links."
            ).classes("text-xs").style("color: var(--peil-slate)")

            cols = [
                {"name": "name", "label": "Naam",   "field": "name", "align": "left", "sortable": True},
                {"name": "gt",   "label": "GT",     "field": "gt",   "align": "center", "sortable": True},
                {"name": "mlgl", "label": "GLG",    "field": "mlgl", "sortable": True},
                {"name": "mg",   "label": "Gem.",   "field": "mg",   "sortable": True},
                {"name": "msgl", "label": "GVG",    "field": "msgl", "sortable": True},
                {"name": "mhgl", "label": "GHG",    "field": "mhgl", "sortable": True},
                {"name": "sl",   "label": "Maaiveld", "field": "sl", "sortable": True},
            ]
            ui.table(columns=cols, rows=stats_rows, row_key="name").classes(
                "w-full peil-num"
            ).props("flat dense")

            if all(r.get("gt") in ("?", None) for r in stats_rows):
                ui.label(
                    "Grondwatertrap ontbreekt: deze dataset bevat geen "
                    "maaiveldhoogte bij de peilbuizen."
                ).classes("text-xs").style("color: var(--peil-low)")

            with ui.row().classes("gap-3 items-center mt-2"):
                avg_toggle = ui.switch("Gemiddelde FOE-curve tonen", value=show_avg_foe)
                rel_toggle = ui.switch("Hoogtes t.o.v. maaiveld (m-mv)", value=relative_to_surface)

        # ── Rechterkolom: drie plots ──────────────────────────────────────
        with ui.column().classes("flex-1 min-w-0 gap-3"):
            hydrograph_holder = ui.column().classes("w-full")
            foe_holder = ui.column().classes("w-full")
            regime_holder = ui.column().classes("w-full")

    # ── render helpers ────────────────────────────────────────────────────
    def _series_for(names: list[str]) -> dict[str, pd.Series]:
        out: dict[str, pd.Series] = {}
        for name in names:
            try:
                s = get_oseries(name)
            except Exception as exc:  # noqa: BLE001
                log.warning("get_oseries faalde voor %s: %s", name, exc)
                continue
            if s.empty:
                continue
            if rel_toggle.value:
                sl = _surface_level_of(name)
                if np.isfinite(sl):
                    s = (sl - s).rename(name)  # cm-mv conversie blijft m
            out[name] = s.rename(name)
        return out

    def _redraw() -> None:
        series = _series_for(selected)
        ylabel = "Grondwaterstand (m onder maaiveld)" if rel_toggle.value else "Grondwaterstand (m NAP)"

        # Hydrograph
        hydrograph_holder.clear()
        with hydrograph_holder:
            if not series:
                ui.plotly(
                    clean_fig(empty_figure("Selecteer links een of meer peilbuizen."))
                ).classes("w-full")
            else:
                fig = timeseries_overlay(series, title="Groundwater Hydrograph", height=380)
                fig.update_yaxes(title_text=ylabel, autorange=("reversed" if rel_toggle.value else True))
                ui.plotly(clean_fig(fig)).classes("w-full")

        # FOE
        foe_holder.clear()
        with foe_holder:
            avg = average_foe(series) if avg_toggle.value else None
            fig = foe_figure(series, average=avg, height=340)
            fig.update_yaxes(title_text=ylabel, autorange=("reversed" if rel_toggle.value else True))
            ui.plotly(clean_fig(fig)).classes("w-full")

        # Regime curve
        regime_holder.clear()
        with regime_holder:
            fig = regime_curve_figure(series, height=320)
            fig.update_yaxes(title_text=ylabel, autorange=("reversed" if rel_toggle.value else True))
            ui.plotly(clean_fig(fig)).classes("w-full")

    def _on_avg_toggle() -> None:
        ui_state.set("statistics.show_avg_foe", avg_toggle.value)
        _redraw()

    def _on_rel_toggle() -> None:
        ui_state.set("statistics.rel_to_surface", rel_toggle.value)
        _redraw()

    avg_toggle.on_value_change(_on_avg_toggle)
    rel_toggle.on_value_change(_on_rel_toggle)

    _redraw()


# ── helpers ─────────────────────────────────────────────────────────────────
def _stats_row(name: str) -> dict:
    """Bereken en formatteer één tabel-regel."""
    try:
        d = gw_stats(STORE.store_key, name)
    except Exception as exc:  # noqa: BLE001
        log.warning("gw_stats faalde voor %s: %s", name, exc)
        d = {"name": name, "gt": "?", "mlgl": np.nan, "mg": np.nan,
             "msgl": np.nan, "mhgl": np.nan, "surface_level": np.nan}
    return {
        "name": d["name"],
        "gt":   d["gt"],
        "mlgl": _fmt(d["mlgl"]),
        "mg":   _fmt(d["mg"]),
        "msgl": _fmt(d["msgl"]),
        "mhgl": _fmt(d["mhgl"]),
        "sl":   _fmt(d["surface_level"]),
    }


def _fmt(val: float, digits: int = 2) -> str:
    if val is None or (isinstance(val, float) and not np.isfinite(val)):
        return ""
    return f"{val:.{digits}f}"


def _surface_level_of(name: str) -> float:
    try:
        col = STORE.columns.ground_level
        row = STORE.pstore.oseries.loc[name]
        if col in row.index and pd.notna(row[col]):
            return float(row[col])
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


def render() -> None:
    """Weergave binnen de vaste omlijsting (kop + peilbuizenlijst)."""
    with pagina("statistics"):
        _inhoud()
