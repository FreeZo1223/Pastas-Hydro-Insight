"""pastas_adapter — LESA-naar-PASTAS koppellaag.

Adapter-grens (hard):
- Buiten naar binnen: LESA-types (Pydantic models, paths, Series)
- Binnen: pastas.Model, pastastore.PastaStore (publieke API)
- Geen lekkage van pastas-internals naar LESA-domein

Het LESA-project ``C:\\GIS_Projecten\\PASTAS\\`` heeft zijn eigen venv en
pipeline. Deze adapter dupliceert die niet — hij gebruikt pastas/pastastore
direct via hun publieke API.
"""

from pastas_adapter.diagnostics import ModelDiagnostics, summarise_diagnostics
from pastas_adapter.fit import FitConfig, FitResult, fit_oseries
from pastas_adapter.store import PastaStoreAdapter

__version__ = "0.1.0"

__all__ = [
    "FitConfig",
    "FitResult",
    "ModelDiagnostics",
    "PastaStoreAdapter",
    "fit_oseries",
    "summarise_diagnostics",
]
