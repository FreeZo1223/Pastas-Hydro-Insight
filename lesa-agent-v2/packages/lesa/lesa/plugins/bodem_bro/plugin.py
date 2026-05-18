"""Bodem BRO — bodemtypen uit de BRO Bodemkaart 1:50.000.

Gebruikt geo_stack.skills.bro voor de data-fetch.
Geen directe HTTP — alle I/O via geo_stack.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from lesa.domain.claim import Claim
from lesa.domain.hypothesis import Hypothesis
from lesa.domain.scope import ScopeStatement
from lesa.plugins._base import (
    PluginInputs,
    PluginOutputs,
    PluginRawData,
    QgisLayerSpec,
)
from lesa.plugins.bodem_bro.params import BodemBroParams

log = logging.getLogger(__name__)

BRO_BODEMKAART_SOURCE = "BRO Bodemkaart 1:50.000 (WUR/BIS Nederland)"

VEEN_CODES = {"V", "W"}
_CANDIDATE_TYPE_FIELDS = [
    "first_soilcode",
    "soilcode",
    "bodemeenheid",
    "bodemtype",
    "bodemcode",
    "legendacode",
    "mapunit",
    "soilUnit",
    "omschrijving",
    "soilmap_code",
]


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _find_type_column(gdf: "gpd.GeoDataFrame") -> str | None:
    """Zoek de meest waarschijnlijke kolom met bodemtypecode."""
    cols_lower = {c.lower(): c for c in gdf.columns}
    for candidate in _CANDIDATE_TYPE_FIELDS:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
    return None


def _code_has_veen(code: str) -> bool:
    if not code:
        return False
    return code[0].upper() in VEEN_CODES


class BodemBroPlugin:
    PLUGIN_ID = "bodem_bro"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = BodemBroParams

    @classmethod
    def params_schema(cls) -> dict:
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs: PluginInputs) -> None:
        pass

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        """Haal BRO Bodemkaart op via geo_stack BRO-skill (async wrapper)."""
        import asyncio

        from geo_stack.skills.bro import fetch_bodemkaart
        from shapely.geometry import shape

        p = BodemBroParams.model_validate(inputs.params)
        aoi_geom = shape(inputs.aoi_geojson)
        bbox = aoi_geom.bounds  # (minx, miny, maxx, maxy)

        artifact_dir = Path(inputs.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifact_dir / "bodemkaart.gpkg"

        log.info("BRO Bodemkaart ophalen voor bbox %s", bbox)

        gdf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: fetch_bodemkaart(
                bbox,
                output_path=output_path,
                extra_buffer_m=p.aoi_buffer_m,
            ),
        )

        raw = PluginRawData(
            files={"bodemkaart_gpkg": str(output_path)} if output_path.exists() else {},
            metadata={
                "n_features": len(gdf),
                "columns": list(gdf.columns),
                "source": BRO_BODEMKAART_SOURCE,
                "bbox": bbox,
            },
        )
        raw.set_frame("bodemkaart", gdf)
        return raw

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        """Analyseer bodemtypen: dominantie, veenaanwezigheid, geschiktheidsindicaties."""
        import geopandas as gpd
        from shapely.geometry import shape

        p = BodemBroParams.model_validate(inputs.params)
        aoi_geom = shape(inputs.aoi_geojson)
        aoi_area_ha = aoi_geom.area / 10_000

        gdf: gpd.GeoDataFrame = raw.get_frame("bodemkaart")
        n_features = raw.metadata.get("n_features", 0)

        if gdf is None or gdf.empty or n_features == 0:
            return self._empty_outputs(
                "Geen bodemkaart-features gevonden in AOI. "
                "Controleer BRO endpoint + typename (zie geo_stack.skills.bro).",
                inputs,
            )

        # ── Intersect met AOI ────────────────────────────────────────────
        aoi_gdf = gpd.GeoDataFrame(geometry=[aoi_geom], crs="EPSG:28992")
        try:
            clipped = gpd.overlay(gdf, aoi_gdf, how="intersection", keep_geom_type=False)
        except Exception as exc:
            log.warning("Bodemkaart overlay mislukt: %s — gebruik ongeselecteerde data", exc)
            clipped = gdf

        if clipped.empty:
            return self._empty_outputs("Bodemkaart-overlay met AOI levert geen vlakken op.", inputs)

        clipped = clipped[~clipped.geometry.is_empty]
        clipped["oppervlakte_ha"] = clipped.geometry.area / 10_000

        # ── Bodemtype-kolom bepalen ──────────────────────────────────────
        type_col = _find_type_column(clipped)
        if type_col is None:
            log.warning(
                "Geen bodemtype-kolom gevonden in %s — beschikbare kolommen: %s",
                BRO_BODEMKAART_SOURCE, list(clipped.columns),
            )
            # Nog steeds bruikbaar als oppervlakte-data
            type_col = None

        claims: list[Claim] = []
        hypotheses: list[Hypothesis] = []

        # ── Dominante bodemtypen ─────────────────────────────────────────
        if type_col is not None:
            dom = (
                clipped.groupby(type_col, dropna=False)["oppervlakte_ha"]
                .sum()
                .sort_values(ascending=False)
            )
            dom_filtered = dom[dom >= p.min_vlak_ha]
            total_mapped = float(dom.sum())
            dekking_pct = (total_mapped / aoi_area_ha * 100) if aoi_area_ha > 0 else 0.0

            # Top-bodemtypen als claim
            top3 = dom_filtered.head(3)
            top3_text = "; ".join(
                f"{code} ({ha:.1f} ha, {ha / total_mapped * 100:.0f}%)"
                for code, ha in top3.items()
                if total_mapped > 0
            )
            claims.append(
                Claim(
                    id=_new_id(),
                    plugin_id=self.PLUGIN_ID,
                    topic="bodem",
                    text=(
                        f"Dominante bodemtypen in het studiegebied "
                        f"({dekking_pct:.0f}% gedekt door bodemkaart): {top3_text}."
                    ),
                    based_on=[BRO_BODEMKAART_SOURCE],
                    uncertainty="laag" if dekking_pct > 80 else "middel",
                    substantiation="Oppervlakte-gewogen top-3 uit BRO Bodemkaart vlakken.",
                )
            )

            # Veendetectie
            veen_codes = [c for c in dom_filtered.index if _code_has_veen(str(c))]
            veen_ha = float(dom_filtered[veen_codes].sum()) if veen_codes else 0.0
            veen_pct = (veen_ha / total_mapped * 100) if total_mapped > 0 else 0.0

            if veen_ha > p.min_vlak_ha:
                claims.append(
                    Claim(
                        id=_new_id(),
                        plugin_id=self.PLUGIN_ID,
                        topic="bodem",
                        text=(
                            f"Veen- of moerige gronden aanwezig: {veen_ha:.1f} ha "
                            f"({veen_pct:.0f}% van gedekte oppervlakte). "
                            f"Codes: {', '.join(str(c) for c in veen_codes)}."
                        ),
                        based_on=[BRO_BODEMKAART_SOURCE],
                        uncertainty="middel",
                        substantiation=(
                            "Veen gedetecteerd via bodemcode-prefix V/W "
                            "(NL bodemeenheden-classificatie)."
                        ),
                    )
                )

                # Hypothese: veen als indicator voor hydrologische conditie
                hyp_veen = Hypothesis(
                    id=_new_id(),
                    plugin_id=self.PLUGIN_ID,
                    proposed_mechanism=(
                        "Aanwezigheid van veen of moerige bodem wijst op een "
                        "historisch natte situatie met hoge grondwaterstanden en/of kwel."
                    ),
                    predicted_observation=(
                        "Grondwaterstanden in peilbuizen nabij de veenvlekken liggen "
                        "dicht bij of boven maaiveld in winterperiode."
                    ),
                    falsifier=(
                        "Peilbuismetingen tonen geen winterse grondwaterstand "
                        "binnen 50 cm van maaiveld, ondanks aanwezigheid van veen."
                    ),
                    confidence_level="plausibel",
                    weakest_link=(
                        "BRO Bodemkaart 1:50.000 heeft een minimale kaarteenheid van "
                        "ca. 1 ha — kleinere veenvlekken worden gemist."
                    ),
                    supporting_claims=[],
                )
                hypotheses.append(hyp_veen)

        # ── Artifacts ────────────────────────────────────────────────────
        gpkg_path = raw.files.get("bodemkaart_gpkg")
        artifacts = {}
        qgis_layers = []
        if gpkg_path:
            artifacts["bodemkaart_gpkg"] = gpkg_path
            qgis_layers.append(
                QgisLayerSpec(
                    name="BRO Bodemkaart 1:50.000",
                    source_path=gpkg_path,
                    layer_type="vector",
                    group="Bodem",
                    visible=True,
                )
            )

        # ── Scope ────────────────────────────────────────────────────────
        scope = ScopeStatement(
            scope="plugin",
            subject_id=self.PLUGIN_ID,
            based_on=[BRO_BODEMKAART_SOURCE],
            not_tested=[
                "Veldboringen / profielkuilen ter verificatie bodemtype",
                "Bodemchemie (pH, organisch stof, textuur)",
                "Kleine bodemvlekken < 1 ha (onder kaarteenheid-minimum)",
                "Antropogene bodemverstoringen (ophogingen, uitgravingen)",
            ],
            uncertainty_level="middel",
            consequences=(
                "Bodemkaart 1:50.000 geeft een generaliseerd beeld. "
                "Specifieke locaties kunnen significant afwijken. "
                "Veldverificatie is noodzakelijk voor beslissingen op niveau 3."
            ),
        )

        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            claims=claims,
            hypotheses=hypotheses,
            scope=scope,
            artifacts=artifacts,
            qgis_layers=qgis_layers,
            summary={
                "n_features": n_features,
                "type_column": type_col,
                "n_dominante_types": len(dom_filtered) if type_col else 0,
            },
        )

    def _empty_outputs(self, reden: str, inputs: PluginInputs) -> PluginOutputs:
        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            scope=ScopeStatement(
                scope="plugin",
                subject_id=self.PLUGIN_ID,
                based_on=[BRO_BODEMKAART_SOURCE],
                not_tested=["alle bodemanalyse"],
                uncertainty_level="hoog",
                consequences=reden,
            ),
        )
