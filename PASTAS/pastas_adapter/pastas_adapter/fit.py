"""Tijdreeksmodel-fitting via PASTAS — minimal entry point voor LESA.

Een PASTAS-model bestaat uit een ``oseries`` (de te modelleren reeks,
meestal grondwaterstand) en stresses (neerslag, verdamping, peilstress
etc.). Dit module verbergt de PASTAS-API achter een dunne, getypeerde
laag zodat de LESA-grondwater-plugin niet rechtstreeks PASTAS hoeft te
importeren.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import pandas as pd


SolverName = Literal["LeastSquares", "LmfitSolve"]


@dataclass
class FitConfig:
    """Configuratie voor één modelfit."""

    name: str
    tmin: str | None = None
    tmax: str | None = None
    solver: SolverName = "LeastSquares"
    noise_model: bool = True
    rfunc: str = "Exponential"
    """``Exponential``, ``Gamma``, ``Hantush`` etc. — zie pastas.rfunc."""
    extra_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class FitResult:
    """Resultaat van één modelfit; bevat alleen samenvattende metrics.

    Het volledige pastas.Model-object blijft eigendom van de aanroeper —
    deze adapter geeft het niet aan LESA-domein door.
    """

    name: str
    success: bool
    rsq: float | None = None
    aic: float | None = None
    rmse: float | None = None
    parameters: dict[str, float] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def fit_oseries(
    oseries: "pd.Series",
    stresses: dict[str, "pd.Series"],
    config: FitConfig,
) -> tuple[FitResult, Any]:
    """Bouw + fit een PASTAS-model en geef samenvatting + ml-object terug.

    Returns
    -------
    (FitResult, pastas.Model)
        FitResult is veilig om te serialiseren naar SessionState.
        ml-object blijft bij aanroeper voor verdere analyse / opslag in
        PastaStoreAdapter.
    """
    import pastas as ps  # noqa: WPS433 — adapter-grens

    ml = ps.Model(oseries, name=config.name, **config.extra_kwargs)

    rfunc_cls = getattr(ps.rfunc, config.rfunc, None)
    if rfunc_cls is None:
        raise ValueError(f"Onbekende rfunc '{config.rfunc}'. Zie pastas.rfunc.")

    for stress_name, stress in stresses.items():
        sm = ps.StressModel(stress, rfunc=rfunc_cls(), name=stress_name)
        ml.add_stressmodel(sm)

    if not config.noise_model:
        ml.del_noisemodel()

    try:
        ml.solve(
            tmin=config.tmin,
            tmax=config.tmax,
            solver=getattr(ps, config.solver)(),
            report=False,
        )
    except Exception as exc:  # noqa: BLE001
        return FitResult(name=config.name, success=False, error=f"{type(exc).__name__}: {exc}"), ml

    stats = ml.stats.summary().to_dict() if hasattr(ml.stats, "summary") else {}
    params = ml.parameters["optimal"].to_dict() if hasattr(ml, "parameters") else {}

    return (
        FitResult(
            name=config.name,
            success=True,
            rsq=float(ml.stats.rsq()) if hasattr(ml.stats, "rsq") else None,
            aic=float(ml.stats.aic()) if hasattr(ml.stats, "aic") else None,
            rmse=float(ml.stats.rmse()) if hasattr(ml.stats, "rmse") else None,
            parameters=params,
            diagnostics={"summary": stats},
        ),
        ml,
    )
