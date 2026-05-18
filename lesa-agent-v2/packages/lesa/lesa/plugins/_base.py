"""Plugin base types — Protocol, params, inputs, outputs.

Alle LESA-plugins implementeren het ``Plugin`` Protocol.  Twee-fase
uitvoering: ``fetch_data()`` is async (HTTP I/O via geo_stack-skills),
``analyze()`` is sync (CPU-werk, deterministisch).

Plugins importeren NOOIT http-libs rechtstreeks — alleen geo_stack-skills.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from lesa.domain.claim import Claim
from lesa.domain.hypothesis import Hypothesis
from lesa.domain.rangorde import RangordePosition
from lesa.domain.scope import ScopeStatement


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Typed plugin parameters ────────────────────────────────────────────────

class PluginParams(BaseModel):
    """Basis voor getypeerde plugin-parameters.

    Elke plugin definieert een subklasse:

        class BodemParams(PluginParams):
            scale: int = Field(50_000, ge=10_000, le=250_000)
            include_grondwater: bool = True

    De orchestrator injecteert het JSON Schema (via ``params_schema()``)
    als tool-definitie zodat Claude alleen geldige params kan opgeven.
    """

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        """JSON Schema van de plugin-parameters (voor tool-definitie)."""
        return cls.model_json_schema()


# ── Plugin inputs ─────────────────────────────────────────────────────────

class PluginInputs(BaseModel):
    """Contextinformatie die elke plugin van de sessie ontvangt."""

    session_id: str
    project_name: str
    scale_level: int = Field(ge=1, le=3)
    landscape_type: str | None = None

    # Geografisch
    aoi_geojson: dict[str, Any] = Field(
        description="GeoJSON-object (Feature of Geometry) in EPSG:28992"
    )
    system_boundary_geojson: dict[str, Any] | None = Field(
        default=None,
        description="Systeemgrens als GeoJSON; None als nog niet bepaald",
    )

    # Context uit hogere-orde plugins
    prior_claims: list[Claim] = Field(default_factory=list)
    prior_hypotheses: list[Hypothesis] = Field(default_factory=list)

    # Plugin-specifieke parameters
    params: dict[str, Any] = Field(default_factory=dict)

    # Opslag
    artifact_dir: str = Field(
        description="Absoluut pad naar <session>/data/<plugin_id>/ voor artifacts"
    )


# ── Plugin raw data ────────────────────────────────────────────────────────

class PluginRawData(BaseModel):
    """Tussenliggende data teruggegeven door ``fetch_data()``.

    De inhoud is plugin-specifiek en wordt doorgegeven aan ``analyze()``.
    Sla paths op als str voor JSON-serialisatie.
    """

    model_config = {"arbitrary_types_allowed": True}

    files: dict[str, str] = Field(
        default_factory=dict,
        description="naam → absoluut bestandspad van gedownloade data",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Optioneel: in-memory GeoDataFrames voor kleine datasets
    # (niet geserialiseerd naar JSON — alleen voor analyze())
    _frames: dict[str, Any] = {}

    def set_frame(self, key: str, gdf: Any) -> None:  # noqa: ANN401
        self._frames[key] = gdf

    def get_frame(self, key: str) -> Any | None:  # noqa: ANN401
        return self._frames.get(key)


# ── QGIS layer specification ───────────────────────────────────────────────

class QgisLayerSpec(BaseModel):
    """Beschrijving van een laag die aan het QGIS-project toegevoegd moet worden."""

    name: str
    source_path: str = Field(description="Absoluut pad naar gpkg/tif/parquet")
    layer_type: str = Field(description="'vector' | 'raster'")
    style_path: str | None = Field(
        default=None,
        description="Absoluut pad naar .qml; None = QGIS-default",
    )
    group: str | None = Field(
        default=None,
        description="Laaggroepnaam in QGIS legenda",
    )
    visible: bool = True
    min_scale: int | None = None
    max_scale: int | None = None


# ── Plugin outputs ─────────────────────────────────────────────────────────

class PluginOutputs(BaseModel):
    """Gestandaardiseerde output van een succesvol afgeronde plugin."""

    plugin_id: str
    plugin_version: str

    # Inhoudelijke output
    claims: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    scope: ScopeStatement

    # Bestands-artifacts: output-naam → absoluut pad
    artifacts: dict[str, str] = Field(default_factory=dict)

    # QGIS-lagen
    qgis_layers: list[QgisLayerSpec] = Field(default_factory=list)

    # Metadata
    completed_at: datetime = Field(default_factory=_utcnow)
    duration_s: float | None = None

    # Vrije key-value store voor plugin-specifieke samenvatting
    summary: dict[str, Any] = Field(default_factory=dict)


# ── Plugin Protocol ────────────────────────────────────────────────────────

@runtime_checkable
class Plugin(Protocol):
    """Protocol waaraan alle LESA-plugins voldoen.

    Minimale implementatie:

        class MijnParams(PluginParams):
            schaal: int = 50_000

        class MijnPlugin:
            PLUGIN_ID = "mijn_plugin"
            PLUGIN_VERSION = "0.1.0"
            PARAMS_CLASS = MijnParams

            @classmethod
            def params_schema(cls) -> dict:
                return cls.PARAMS_CLASS.params_schema()

            def validate_inputs(self, inputs: PluginInputs) -> None:
                ...

            async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
                ...

            def analyze(
                self, inputs: PluginInputs, raw: PluginRawData
            ) -> PluginOutputs:
                ...
    """

    PLUGIN_ID: str
    PLUGIN_VERSION: str
    PARAMS_CLASS: type[PluginParams]

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        """JSON Schema van plugin-parameters voor de tool-definitie."""
        ...

    def validate_inputs(self, inputs: PluginInputs) -> None:
        """Valideer inputs vóór fetch_data.

        Gooi ``ValueError`` als de inputs ongeldig zijn.
        Controleer hier bv. of het landscape_type wordt ondersteund of
        dat verplichte prior-plugins al zijn gedraaid.
        """
        ...

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        """Haal data op via geo_stack-skills (async, paralleliseerbaar).

        Geen directe HTTP-calls. Gebruik uitsluitend geo_stack-skills.
        Schrijf tussenresultaten naar ``inputs.artifact_dir``.
        """
        ...

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        """Analyseer de opgehaalde data en genereer claims/hypothesen (sync).

        CPU-werk: GIS-operaties, statistieken, PASTAS-modellen.
        Gooi geen exceptions na succesvolle fetch — gebruik lege claims
        met lage confidence en hoge onzekerheid als data dun is.
        """
        ...
