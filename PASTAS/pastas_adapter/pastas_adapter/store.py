"""PastaStoreAdapter — dunne wrapper rond pastastore.PastaStore.

PastaStore is de canonical store voor PASTAS-modellen + tijdreeksen.
LESA gebruikt dit als secundaire opslag (naast SessionStore artifacts):
de plugin slaat zijn fit-resultaten op in een PastaStore zodat de expert
later interactief modellen kan inspecteren met PASTAS-tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    import pandas as pd


StoreBackend = Literal["dict", "pas", "arctic", "pystore"]


@dataclass
class StoreLocation:
    """Beschrijving van waar de store fysiek staat."""

    backend: StoreBackend
    path: Path | str
    name: str = "lesa_store"


class PastaStoreAdapter:
    """Wrapper rond pastastore.PastaStore.

    Wordt geconstrueerd door de hydrologie-plugin. De plugin gebruikt
    ``add_oseries()``, ``add_stress()``, ``add_model()`` om data te
    persisteren. Nadat de plugin klaar is wordt het store-pad als
    artifact in de PluginOutputs opgenomen.
    """

    def __init__(self, location: StoreLocation) -> None:
        self.location = location
        self._store: Any | None = None

    def open(self) -> Any:  # noqa: ANN401
        """Open of maak de PastaStore (lazy import van pastastore)."""
        if self._store is not None:
            return self._store

        try:
            import pastastore as pst  # noqa: WPS433 — adapter-grens
        except ImportError as exc:
            raise RuntimeError(
                "pastastore is niet geïnstalleerd. Voeg toe aan project-"
                "dependencies of installeer 'pastas-adapter[full]'."
            ) from exc

        path = Path(self.location.path)
        path.mkdir(parents=True, exist_ok=True)

        backend = self.location.backend
        if backend == "dict":
            connector = pst.DictConnector(self.location.name)
        elif backend == "pas":
            connector = pst.PasConnector(self.location.name, path)
        else:
            raise NotImplementedError(
                f"Backend '{backend}' nog niet ondersteund. Gebruik 'dict' of 'pas'."
            )

        self._store = pst.PastaStore(connector)
        return self._store

    def add_oseries(self, name: str, series: "pd.Series", metadata: dict[str, Any] | None = None) -> None:
        store = self.open()
        store.add_oseries(series, name, metadata=metadata or {})

    def add_stress(
        self,
        name: str,
        series: "pd.Series",
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        store = self.open()
        store.add_stress(series, name, kind=kind, metadata=metadata or {})

    def add_model(self, name: str, ml: Any) -> None:  # noqa: ANN401
        """Voeg een gefitte PASTAS-model toe; ``name`` overschrijft ``ml.name``."""
        store = self.open()
        ml.name = name
        store.conn.add_model(ml, overwrite=True)

    def list_models(self) -> list[str]:
        store = self.open()
        return list(store.model_names)

    def close(self) -> None:
        """Sluit de store als de connector dat ondersteunt."""
        if self._store is None:
            return
        connector = getattr(self._store, "conn", None)
        if connector is not None and hasattr(connector, "close"):
            connector.close()
        self._store = None
