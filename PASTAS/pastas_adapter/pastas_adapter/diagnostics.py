"""Diagnostiek-uitlezing van een PASTAS-model voor LESA-rapportage.

Houdt de adapter-grens: in de adapter wordt het pastas.Model-object
geïnspecteerd; alleen samenvattende metrics gaan terug naar LESA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelDiagnostics:
    """LESA-vriendelijke diagnose-samenvatting van een PASTAS-model."""

    name: str
    rsq: float | None = None
    aic: float | None = None
    bic: float | None = None
    rmse: float | None = None
    n_observations: int | None = None
    n_parameters: int | None = None
    parameter_table: dict[str, dict[str, float]] = field(default_factory=dict)
    """``param_name -> {optimal, stderr, pmin, pmax}``."""
    stationarity_warning: str | None = None
    notes: list[str] = field(default_factory=list)


def summarise_diagnostics(ml: Any, name: str | None = None) -> ModelDiagnostics:  # noqa: ANN401
    """Lees relevante diagnostiek uit een pastas.Model-object."""
    diag = ModelDiagnostics(name=name or getattr(ml, "name", "model"))

    if hasattr(ml.stats, "rsq"):
        diag.rsq = float(ml.stats.rsq())
    if hasattr(ml.stats, "aic"):
        diag.aic = float(ml.stats.aic())
    if hasattr(ml.stats, "bic"):
        diag.bic = float(ml.stats.bic())
    if hasattr(ml.stats, "rmse"):
        diag.rmse = float(ml.stats.rmse())

    if hasattr(ml, "observations"):
        diag.n_observations = int(len(ml.observations()))

    if hasattr(ml, "parameters"):
        params = ml.parameters
        diag.n_parameters = int(len(params))
        for pname, row in params.iterrows():
            diag.parameter_table[pname] = {
                "optimal": float(row.get("optimal", float("nan"))),
                "stderr": float(row.get("stderr", float("nan"))),
                "pmin": float(row.get("pmin", float("nan"))),
                "pmax": float(row.get("pmax", float("nan"))),
            }

    return diag
