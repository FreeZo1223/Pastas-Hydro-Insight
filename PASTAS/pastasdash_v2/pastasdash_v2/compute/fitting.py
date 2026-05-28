"""Model-fit wrappers — gebruikt pastas_adapter waar mogelijk, valt terug op pastas direct."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from pastasdash_v2.state.cache import invalidate_store
from pastasdash_v2.state.store import STORE

if TYPE_CHECKING:
    import pastas as ps

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FitOptions:
    rfunc: str = "Gamma"
    noise_model: bool = True
    tmin: str | None = None
    tmax: str | None = None
    stresses: tuple[str, ...] = ("neerslag_KNMI", "verdamping_KNMI")


def fit_model(oseries_name: str, opts: FitOptions) -> tuple[bool, str, "ps.Model | None"]:
    """Fit een RechargeModel; geeft (success, message, model) terug.

    Bij success wordt het model opgeslagen in de PastaStore en de cache
    voor dit store_key wordt gepartieel geïnvalideerd zodat plots opnieuw
    berekend worden.
    """
    import pastas as ps

    try:
        oseries = STORE.pstore.get_oseries(oseries_name)
        if isinstance(oseries, pd.DataFrame):
            oseries = oseries.iloc[:, 0]
        oseries = oseries.dropna()
        if oseries.size < 50:
            return False, f"Te weinig observaties ({oseries.size}) voor fit", None

        ml = ps.Model(oseries, name=oseries_name)

        rfunc_cls = getattr(ps.rfunc, opts.rfunc, ps.rfunc.Gamma)
        try:
            prec = STORE.pstore.get_stresses(opts.stresses[0])
            evap = STORE.pstore.get_stresses(opts.stresses[1])
        except Exception as exc:  # noqa: BLE001
            return False, f"Stresses ontbreken: {exc}", None

        if isinstance(prec, pd.DataFrame):
            prec = prec.iloc[:, 0]
        if isinstance(evap, pd.DataFrame):
            evap = evap.iloc[:, 0]

        rm = ps.RechargeModel(
            prec=prec, evap=evap, rfunc=rfunc_cls(), name="recharge", recharge=ps.rch.Linear()
        )
        ml.add_stressmodel(rm)
        if opts.noise_model:
            try:
                ml.add_noisemodel(ps.ArNoiseModel())
            except AttributeError:
                ml.add_noisemodel(ps.ArmaNoiseModel())

        ml.solve(tmin=opts.tmin, tmax=opts.tmax, report=False)

        STORE.pstore.add_model(ml, overwrite=True)
        invalidate_store(STORE.store_key)
        return True, f"Fit OK (R²={ml.stats.rsq():.3f})", ml

    except Exception as exc:  # noqa: BLE001
        log.exception("Fit faalde voor %s", oseries_name)
        return False, f"Fit faalde: {exc}", None
