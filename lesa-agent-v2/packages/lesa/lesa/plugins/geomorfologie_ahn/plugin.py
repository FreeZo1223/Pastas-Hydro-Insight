"""Geomorfologie AHN4 — reliëfanalyse op basis van het Actueel Hoogtebestand Nederland.

Berekent maaiveld-statistieken, helling en laagtegebieden uit AHN4 DTM.
Geen directe HTTP-aanroepen: data-acquisitie via geo_stack.skills.ahn.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from lesa.domain.claim import Claim
from lesa.domain.scope import ScopeStatement
from lesa.plugins._base import (
    Plugin,
    PluginInputs,
    PluginOutputs,
    PluginRawData,
    QgisLayerSpec,
)
from lesa.plugins.geomorfologie_ahn.params import GeomorfologieAhnParams

log = logging.getLogger(__name__)

AHN_SOURCE_VERSION = "AHN4 (PDOK, datum download)"
MAX_TILE_EXTENT_M = 5_000.0


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


class GeomorfologieAhnPlugin:
    PLUGIN_ID = "geomorfologie_ahn"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = GeomorfologieAhnParams

    @classmethod
    def params_schema(cls) -> dict:
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs: PluginInputs) -> None:
        p = GeomorfologieAhnParams.model_validate(inputs.params)
        if not isinstance(inputs.aoi_geojson, dict):
            raise ValueError("aoi_geojson moet een dict zijn")
        # WCS-modus bij 0.5m + grote buffer kan de 5km-limiet overschrijden;
        # in dat geval geeft fetch_ahn_tile een duidelijke foutmelding.
        # In 'auto'/'cog' modus wordt automatisch COG gebruikt — geen beperking.
        if p.fetch_method == "wcs" and p.resolution == 0.5 and p.aoi_buffer_m > 500:
            raise ValueError(
                "Bij fetch_method='wcs' en resolution=0.5 mag aoi_buffer_m niet groter zijn "
                "dan 500m (WCS tile-limiet 5km). Gebruik fetch_method='auto' of 'cog'."
            )

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        """Download AHN4 DTM (en optioneel DSM) voor AOI + buffer.

        Bij grote AOIs (>~5km kantlengte of >25 Mpx bij 0.5m) schakelt
        fetch_method='auto' automatisch naar COG-streaming via PDOK OGC API.
        """
        from geo_stack.skills.ahn import async_fetch_ahn_tile
        from shapely.geometry import shape

        p = GeomorfologieAhnParams.model_validate(inputs.params)
        aoi_geom = shape(inputs.aoi_geojson)
        minx, miny, maxx, maxy = aoi_geom.bounds
        b = p.aoi_buffer_m

        # Bij WCS-modus + 0.5m: buffer clippen zodat de tile binnen 5km blijft
        if p.fetch_method == "wcs" and p.resolution == 0.5:
            b = min(b, (MAX_TILE_EXTENT_M - (maxx - minx)) / 2,
                      (MAX_TILE_EXTENT_M - (maxy - miny)) / 2, 500.0)

        fetch_bbox = (minx - b, miny - b, maxx + b, maxy + b)
        artifact_dir = Path(inputs.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        dtm_path = artifact_dir / f"ahn4_dtm_{p.resolution}m.tif"
        log.info(
            "Ophalen AHN4 %s %.1fm @ %s (fetch_method=%s)",
            p.product, p.resolution, fetch_bbox, p.fetch_method,
        )
        dtm_path = await async_fetch_ahn_tile(
            fetch_bbox,
            p.product,
            resolution=p.resolution,
            output_path=dtm_path,
            fetch_method=p.fetch_method,
        )

        raw = PluginRawData(
            files={"dtm": str(dtm_path)},
            metadata={
                "bbox": fetch_bbox,
                "resolution": p.resolution,
                "product": p.product,
                "fetch_method": p.fetch_method,
                "ahn_source": AHN_SOURCE_VERSION,
            },
        )
        return raw

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        """Bereken reliëf-statistieken, helling en laagtepolygonen."""
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.features import shapes
        from shapely.geometry import shape

        p = GeomorfologieAhnParams.model_validate(inputs.params)
        dtm_path = Path(raw.files["dtm"])
        artifact_dir = dtm_path.parent

        # ── Raster laden ─────────────────────────────────────────────────
        with rasterio.open(dtm_path) as ds:
            data = ds.read(1).astype(np.float32)
            transform = ds.transform
            crs_wkt = ds.crs.to_wkt() if ds.crs else None
            nodata = ds.nodata if ds.nodata is not None else -9999.0
            res_m = abs(transform.a)

        data = np.where(data == nodata, np.nan, data)

        if np.all(np.isnan(data)):
            return self._empty_outputs("AHN4 DTM bevat alleen NoData — controleer bbox.")

        # ── Statistieken ─────────────────────────────────────────────────
        valid = data[~np.isnan(data)]
        z_min = float(np.nanmin(data))
        z_max = float(np.nanmax(data))
        z_mean = float(np.nanmean(data))
        z_std = float(np.nanstd(data))
        laagte_grens = float(np.nanpercentile(data, p.laagte_percentiel))
        hoog_grens = float(np.nanpercentile(data, 100 - p.laagte_percentiel))
        local_relief = z_max - z_min

        # ── Helling berekenen ─────────────────────────────────────────────
        dy, dx = np.gradient(np.where(np.isnan(data), 0.0, data), res_m, res_m)
        slope_rad = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
        slope_deg = np.degrees(slope_rad)
        slope_deg = np.where(np.isnan(data), np.nan, slope_deg)
        slope_mean = float(np.nanmean(slope_deg))
        slope_max = float(np.nanmax(slope_deg))

        # ── Helling opslaan als GeoTIFF ──────────────────────────────────
        slope_path = artifact_dir / "helling_graden.tif"
        with rasterio.open(dtm_path) as ds:
            profile = ds.profile.copy()
        profile.update(dtype=rasterio.float32, nodata=-9999.0)
        slope_out = np.where(np.isnan(slope_deg), -9999.0, slope_deg).astype(np.float32)
        with rasterio.open(slope_path, "w", **profile) as ds:
            ds.write(slope_out, 1)

        # ── Laagtegebieden vectoriseren ───────────────────────────────────
        laagte_mask = (data <= laagte_grens) & ~np.isnan(data)
        with rasterio.open(dtm_path) as ds:
            laagte_transform = ds.transform
            laagte_crs = ds.crs

        laagte_polygons = []
        laagte_z_vals = []
        for geom_dict, val in shapes(
            laagte_mask.astype(np.uint8),
            mask=laagte_mask.astype(bool),
            transform=laagte_transform,
        ):
            if val == 1:
                laagte_polygons.append(shape(geom_dict))
                # gemiddelde hoogte in dit vlak
                laagte_z_vals.append(laagte_grens)

        laagte_gpkg_path = artifact_dir / "laagtegebieden.gpkg"
        if laagte_polygons:
            if laagte_crs and "RD New" in str(laagte_crs):
                laagte_crs = "EPSG:28992"
            laagte_gdf = gpd.GeoDataFrame(
                {"z_grens_m": laagte_z_vals},
                geometry=laagte_polygons,
                crs=laagte_crs or "EPSG:28992",
            )
            print(f"DEBUG: laagte_gdf.crs = {laagte_gdf.crs}")
            if laagte_gdf.crs and laagte_gdf.crs.to_epsg() != 28992:
                laagte_gdf = laagte_gdf.to_crs("EPSG:28992")
            laagte_gdf = laagte_gdf[~laagte_gdf.geometry.is_empty]
            laagte_gdf = laagte_gdf[laagte_gdf.geometry.area > res_m ** 2]
            laagte_gdf.to_file(laagte_gpkg_path, driver="GPKG")
            laagte_opp_ha = float(laagte_gdf.geometry.area.sum() / 10_000)
        else:
            laagte_opp_ha = 0.0

        total_valid_ha = len(valid) * res_m ** 2 / 10_000
        laagte_pct = (laagte_opp_ha / total_valid_ha * 100) if total_valid_ha > 0 else 0.0

        # ── Claims ────────────────────────────────────────────────────────
        claims = [
            Claim(
                id=_new_id(),
                plugin_id=self.PLUGIN_ID,
                topic="reliëf",
                text=(
                    f"Maaiveld in het studiegebied varieert van {z_min:.2f} tot "
                    f"{z_max:.2f} m NAP (gemiddeld {z_mean:.2f} m, σ={z_std:.2f} m). "
                    f"Lokale reliëfamplitude: {local_relief:.2f} m."
                ),
                based_on=[AHN_SOURCE_VERSION, f"Resolutie: {res_m:.1f}m"],
                uncertainty="laag",
                substantiation=f"Berekend uit AHN4 DTM {res_m:.1f}m.",
            ),
            Claim(
                id=_new_id(),
                plugin_id=self.PLUGIN_ID,
                topic="laagtegebieden",
                text=(
                    f"Laagtegebieden (≤ P{p.laagte_percentiel:.0f} = {laagte_grens:.2f} m NAP) "
                    f"beslaan {laagte_pct:.1f}% van het studiegebied ({laagte_opp_ha:.2f} ha). "
                    f"Deze gebieden zijn potentieel gevoelig voor kwel of inundatie."
                ),
                based_on=[AHN_SOURCE_VERSION],
                uncertainty="laag" if laagte_opp_ha > 0 else "middel",
                substantiation=(
                    f"Afgeleid door rasterdrempel op P{p.laagte_percentiel:.0f} "
                    f"hoogte-percentiel (vectorisatie)."
                ),
            ),
            Claim(
                id=_new_id(),
                plugin_id=self.PLUGIN_ID,
                topic="helling",
                text=(
                    f"Gemiddelde helling in het studiegebied is {slope_mean:.1f}°, "
                    f"maximale helling {slope_max:.1f}°. "
                    + (
                        "Steile hellingen (>5°) wijzen mogelijk op duinmorfologie of ingesneden dalen."
                        if slope_max > 5 else
                        "Overwegend vlak reliëf — weinig versnelling grondwaterstroming te verwachten."
                    )
                ),
                based_on=[AHN_SOURCE_VERSION],
                uncertainty="laag",
                substantiation="Berekend als √(∂z/∂x² + ∂z/∂y²) omgezet naar graden.",
            ),
        ]

        # ── Artifacts ─────────────────────────────────────────────────────
        artifacts = {
            "dtm_tif": str(dtm_path),
            "helling_tif": str(slope_path),
        }
        qgis_layers = [
            QgisLayerSpec(
                name="AHN4 DTM",
                source_path=str(dtm_path),
                layer_type="raster",
                group="Geomorfologie",
                visible=True,
            ),
            QgisLayerSpec(
                name="Helling (graden)",
                source_path=str(slope_path),
                layer_type="raster",
                group="Geomorfologie",
                visible=False,
            ),
        ]
        if laagte_polygons:
            artifacts["laagtegebieden_gpkg"] = str(laagte_gpkg_path)
            qgis_layers.append(
                QgisLayerSpec(
                    name="Laagtegebieden",
                    source_path=str(laagte_gpkg_path),
                    layer_type="vector",
                    group="Geomorfologie",
                    visible=True,
                )
            )

        # ── Scope ─────────────────────────────────────────────────────────
        scope = ScopeStatement(
            scope="plugin",
            subject_id=self.PLUGIN_ID,
            based_on=[AHN_SOURCE_VERSION, f"DTM {res_m:.1f}m resolutie"],
            not_tested=[
                "Veldverificatie maaiveld-hoogte",
                "Onderscheid antropogene vs. natuurlijke reliëfvormen",
                "Historische morfologische veranderingen (Topotijdreis)",
                "Diepere bodemopbouw (geen boorgegevens gebruikt)",
            ],
            uncertainty_level="laag",
            consequences=(
                "Reliëfanalyse is objectief en reproduceerbaar. Interpretatie van "
                "laagtegebieden als 'kwelgevoelig' vereist hydrologische plugin. "
                "Antropogeen reliëf (sloten, wegen) is niet gefilterd."
            ),
        )

        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            claims=claims,
            hypotheses=[],
            scope=scope,
            artifacts=artifacts,
            qgis_layers=qgis_layers,
            summary={
                "z_min": round(z_min, 2),
                "z_max": round(z_max, 2),
                "z_mean": round(z_mean, 2),
                "local_relief_m": round(local_relief, 2),
                "laagte_pct": round(laagte_pct, 1),
                "laagte_ha": round(laagte_opp_ha, 2),
                "slope_mean_deg": round(slope_mean, 1),
                "slope_max_deg": round(slope_max, 1),
            },
        )

    def _empty_outputs(self, reason: str) -> PluginOutputs:
        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            scope=ScopeStatement(
                scope="plugin",
                subject_id=self.PLUGIN_ID,
                based_on=[AHN_SOURCE_VERSION],
                not_tested=["alles — lege data"],
                uncertainty_level="hoog",
                consequences=reason,
            ),
        )
