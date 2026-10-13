"""De ingang voor de webpagina: een naam en JSON erin, JSON eruit.

Elke handeling hieronder is één knop of weergave in de pagina. Het rekenwerk
zit in ``pastasdash_v2.core``; hier wordt alleen aangeroepen en ingepakt.
Fouten gaan als bericht terug in plaats van als uitzondering, zodat de pagina
ze kan tonen.
"""

from __future__ import annotations

import json
import logging
import math
import traceback
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from pastasdash_v2.core import droogte as droogte_kern
from pastasdash_v2.core.fitting import FitOptions, fit_model
from pastasdash_v2.core.statistics import average_foe, gw_stats
from pastasdash_v2.core.stations import DEFAULT_STATION_CODE, STATIONS, STATIONS_BY_CODE
from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import get_oseries, get_stress, gxg, model_summary
from pastasdash_v2.ui.components import plots
from pastasdash_v3 import __version__, figuren, meteo, project, zoeken
from pastasdash_v3.bronnen import BRONNEN

log = logging.getLogger(__name__)

# Waar de projecten staan. In de browser is dit een map in het geheugen.
PROJECTEN = Path("/project")
UITVOER = Path("/tmp")

HANDELINGEN: dict[str, Callable[..., Any]] = {}


def handeling(fn: Callable[..., Any]) -> Callable[..., Any]:
    HANDELINGEN[fn.__name__] = fn
    return fn


def _schoon(waarde: Any) -> Any:
    """Maak een uitkomst geschikt voor JSON: geen NaN, geen numpy-typen."""
    if isinstance(waarde, dict):
        return {str(k): _schoon(v) for k, v in waarde.items()}
    if isinstance(waarde, (list, tuple)):
        return [_schoon(v) for v in waarde]
    if isinstance(waarde, np.generic):
        waarde = waarde.item()
    if isinstance(waarde, float) and not math.isfinite(waarde):
        return None
    if isinstance(waarde, (pd.Timestamp, Path)):
        return str(waarde)
    return waarde


def roep(naam: str, argumenten: str = "{}") -> str:
    try:
        uit = HANDELINGEN[naam](**json.loads(argumenten or "{}"))
        return json.dumps({"ok": _schoon(uit)})
    except Exception as fout:  # noqa: BLE001 - de pagina toont de melding
        if not isinstance(fout, ValueError):  # een ValueError is een gewone melding voor de gebruiker
            log.exception("Handeling %s mislukt", naam)
        return json.dumps(
            {
                "fout": str(fout) or type(fout).__name__,
                "soort": type(fout).__name__,
                "spoor": traceback.format_exc()[-3000:],
            }
        )


def _fig(fig) -> dict:
    return plots.clean_fig(fig)


# ── project ─────────────────────────────────────────────────────────────────
@handeling
def versies() -> dict:
    import pastas
    import pastastore
    import plotly
    import plotly.offline

    return {
        "pastasdash": __version__,
        "pastas": pastas.__version__,
        "pastastore": pastastore.__version__,
        "pandas": pd.__version__,
        "plotly": plotly.__version__,
        "plotly_js": plotly.offline.get_plotlyjs_version(),
    }


@handeling
def nieuw_project(naam: str) -> dict:
    PROJECTEN.mkdir(parents=True, exist_ok=True)
    project.nieuw(PROJECTEN, naam)
    project.schijf_is_leeg()
    return project.toestand()


@handeling
def open_project(naam: str) -> dict:
    """Open de store die de pagina zojuist onder ``PROJECTEN/<naam>`` heeft gezet."""
    project.open_map(PROJECTEN / naam)
    project.schijf_is_gelijk()
    return project.toestand()


@handeling
def open_zip(pad: str) -> dict:
    PROJECTEN.mkdir(parents=True, exist_ok=True)
    project.uit_zip(pad, PROJECTEN)
    project.schijf_is_leeg()
    return project.toestand()


@handeling
def maak_zip() -> dict:
    UITVOER.mkdir(parents=True, exist_ok=True)
    pad = UITVOER / f"{STORE.display_name}.zip"
    project.naar_zip(pad)
    return {"pad": pad.as_posix(), "bestandsnaam": pad.name}


@handeling
def toestand() -> dict:
    return project.toestand()


@handeling
def gewijzigd() -> dict:
    return project.gewijzigd()


@handeling
def schijf_is_leeg() -> None:
    project.schijf_is_leeg()


@handeling
def voeg_put_toe(gmw: str) -> dict:
    return project.voeg_put_toe(gmw)


@handeling
def zoek_putten(gebied: dict, marge_m: float = 0.0) -> dict:
    """De BRO-putten in een gebied; voor een bestand dat Cowork met een projectgrens maakte."""
    try:
        putten = zoeken.zoek_putten(BRONNEN["bro"]["zoeken"], gebied, marge_m)
    except zoeken.TeGroot:
        raise ValueError("In en rond dit gebied staan meer dan 2000 putten; de BRO levert ze dan niet. "
                         "Kies een kleiner gebied.") from None
    return {"putten": putten}


@handeling
def verwijder_put(naam: str) -> dict:
    project.verwijder_put(naam)
    return project.toestand()


# ── reeksen ─────────────────────────────────────────────────────────────────
def _reeksen(namen: list[str]) -> dict[str, pd.Series]:
    uit = {}
    for naam in namen:
        try:
            uit[naam] = get_oseries(naam)
        except Exception as fout:  # noqa: BLE001
            log.warning("Reeks %s niet leesbaar: %s", naam, fout)
    return uit


@handeling
def reeksen(namen: list[str], onder_elkaar: bool = False, met_stress: bool = False) -> dict:
    series = _reeksen(namen)
    if met_stress:
        for stress in STORE.pstore.stresses_names:
            try:
                series[stress] = get_stress(stress)
            except Exception:  # noqa: BLE001
                continue
    if not series:
        return {"figuur": _fig(plots.empty_figure("Deze reeksen bevatten geen metingen."))}
    fig = plots.timeseries_stacked(series) if onder_elkaar else plots.timeseries_overlay(series)
    return {"figuur": _fig(fig)}


@handeling
def ligging() -> dict:
    return {"punten": figuren.punten()}


# ── model ───────────────────────────────────────────────────────────────────
@handeling
def fit(
    naam: str, rfunc: str = "Gamma", ruis: bool = True, tmin: str = "", tmax: str = ""
) -> dict:
    prec, evap, meldingen = meteo.zorg_voor_stresses(naam)
    opties = FitOptions(
        rfunc=rfunc, noise_model=ruis, tmin=tmin or None, tmax=tmax or None, stresses=(prec, evap)
    )
    gelukt, melding, _ml = fit_model(naam, opties)
    return {
        "gelukt": gelukt,
        "melding": melding,
        "meldingen": meldingen,
        "samenvatting": model_summary(STORE.store_key, naam) if gelukt else {},
    }


@handeling
def model(naam: str) -> dict:
    if naam not in STORE.model_names():
        return {"heeft_model": False}
    ml = STORE.pstore.get_models(naam)
    parameters = [
        {"naam": p, "waarde": rij.get("optimal"), "stderr": rij.get("stderr"), "vrij": bool(rij.get("vary"))}
        for p, rij in ml.parameters.iterrows()
    ]
    return {
        "heeft_model": True,
        "resultaten": _fig(plots.model_results_figure(ml)),
        "diagnostiek": _fig(plots.model_diagnostics_figure(ml)),
        "samenvatting": model_summary(STORE.store_key, naam),
        "parameters": parameters,
        "stresses": [
            reeks.name
            for sm in ml.stressmodels.values()
            for reeks in (getattr(sm, "prec", None), getattr(sm, "evap", None))
            if reeks is not None
        ],
    }


@handeling
def vergelijk(namen: list[str]) -> dict:
    met_model = [n for n in namen if n in set(STORE.model_names())]
    return {
        "figuur": _fig(figuren.vergelijk_figuur(met_model)),
        "tabel": figuren.vergelijk_tabel(met_model),
        "zonder_model": [n for n in namen if n not in met_model],
    }


# ── statistiek ──────────────────────────────────────────────────────────────
def _maaiveld(naam: str) -> float:
    try:
        rij = STORE.pstore.oseries.loc[naam]
        kolom = STORE.columns.ground_level
        if kolom in rij.index and pd.notna(rij[kolom]):
            return float(rij[kolom])
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


@handeling
def statistiek(
    namen: list[str], gemiddelde_foe: bool = True, tov_maaiveld: bool = False
) -> dict:
    rijen = []
    for naam in sorted(STORE.oseries_names()):
        try:
            rij = dict(gw_stats(STORE.store_key, naam))
            rij["jaren"] = gxg(STORE.store_key, naam).get("n_years")
        except Exception as fout:  # noqa: BLE001
            log.warning("Statistiek voor %s mislukt: %s", naam, fout)
            rij = {"name": naam, "gt": "?"}
        rijen.append(rij)

    series: dict[str, pd.Series] = {}
    for naam, s in _reeksen(namen).items():
        if s.empty:
            continue
        maaiveld = _maaiveld(naam)
        if tov_maaiveld and np.isfinite(maaiveld):
            s = maaiveld - s
        series[naam] = s.rename(naam)

    as_titel = "Grondwaterstand (m onder maaiveld)" if tov_maaiveld else "Grondwaterstand (m NAP)"
    richting = "reversed" if tov_maaiveld else True

    if series:
        hydro = plots.timeseries_overlay(series, title="Grondwaterstand", height=380)
    else:
        hydro = plots.empty_figure("Selecteer links een of meer peilbuizen.")
    foe = plots.foe_figure(series, average=average_foe(series) if gemiddelde_foe else None, height=340)
    regime = plots.regime_curve_figure(series, height=320)
    for fig in (hydro, foe, regime):
        fig.update_yaxes(title_text=as_titel, autorange=richting)
    return {"rijen": rijen, "hydro": _fig(hydro), "foe": _fig(foe), "regime": _fig(regime)}


@handeling
def kaart(metriek: str = "rsq") -> dict:
    if metriek not in figuren.METRIEKEN:
        raise ValueError(f"onbekende maat: {metriek}")
    return {"punten": figuren.punten(metriek), "metrieken": figuren.METRIEKEN}


# ── droogte ─────────────────────────────────────────────────────────────────
@handeling
def stations() -> dict:
    return {
        "standaard": DEFAULT_STATION_CODE,
        "stations": [
            {"code": s.code, "naam": s.name} for s in sorted(STATIONS, key=lambda s: s.name)
        ],
    }


@handeling
def droogte(
    station: int = DEFAULT_STATION_CODE,
    ref_van: int = 1990,
    ref_tot: int = 2020,
    jaren: list[int] | None = None,
    knip: bool = True,
) -> dict:
    df = meteo.knmi_dag(int(station), min(int(ref_van), meteo.START_JAAR))
    tekort = droogte_kern.daily_deficit(df["RH"], df["EV24"])
    cumulatief = droogte_kern.cumulative_deficit_by_doy(tekort, clip_negative=knip)
    per_dag = droogte_kern.pivot_by_doy(cumulatief)
    banden = droogte_kern.percentile_bands(
        droogte_kern.select_reference_years(per_dag, int(ref_van), int(ref_tot))
    )
    naam = STATIONS_BY_CODE[int(station)].name if int(station) in STATIONS_BY_CODE else str(station)
    fig = plots.droogte_figure(
        bands=banden,
        current=droogte_kern.current_year_series(cumulatief),
        comparisons=droogte_kern.comparison_year_series(cumulatief, [int(j) for j in jaren or []]),
        title=f"Neerslagtekort {naam} (referentie {ref_van}–{ref_tot})",
    )
    return {"figuur": _fig(fig), "laatste_dag": df.dropna().index[-1].date().isoformat()}
