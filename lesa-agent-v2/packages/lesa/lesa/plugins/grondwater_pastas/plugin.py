"""LESA grondwater-plugin op basis van BRO peilbuizen + KNMI + PASTAS.

Twee-fase uitvoering:
1. fetch_data — peilbuispunten (WFS), KNMI-dagwaarden, optioneel GLD-tijdreeksen.
2. analyze    — claims op data-beschikbaarheid; optioneel PASTAS-fits met NSE/EVP.

Fitten van PASTAS-modellen vereist `pastas-adapter[full]` (pastas + pastastore).
Zonder die extra werkt de plugin in 'inventarisatie-modus': alleen punten en
KNMI-data, geen modeling.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import uuid

from lesa.domain.claim import Claim
from lesa.domain.hypothesis import FieldProtocolStub, Hypothesis
from lesa.domain.scope import ScopeStatement
from lesa.plugins._base import (
    PluginInputs,
    PluginOutputs,
    PluginRawData,
    QgisLayerSpec,
)
from lesa.plugins.grondwater_pastas.params import GrondwaterPastasParams

if TYPE_CHECKING:
    import geopandas as gpd
    import pandas as pd

log = logging.getLogger(__name__)


class GrondwaterPastasPlugin:
    """LESA-plugin voor rangorde 4 (grondwater)."""

    PLUGIN_ID = "grondwater_pastas"
    PLUGIN_VERSION = "0.1.0"
    PARAMS_CLASS = GrondwaterPastasParams

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        return cls.PARAMS_CLASS.params_schema()

    def validate_inputs(self, inputs: PluginInputs) -> None:
        params = self.PARAMS_CLASS.model_validate(inputs.params)
        if params.fit_pastas_models and not params.gld_ids:
            raise ValueError(
                "fit_pastas_models=True maar geen gld_ids opgegeven; "
                "PASTAS-fitten vereist minimaal één GLD-identificatie."
            )

    async def fetch_data(self, inputs: PluginInputs) -> PluginRawData:
        from geo_stack.skills.bro.peilbuizen import (
            fetch_gld_timeseries,
            fetch_peilbuizen,
        )
        from geo_stack.skills.knmi import (
            fetch_recharge_inputs,
            nearest_climate_station,
        )

        params = self.PARAMS_CLASS.model_validate(inputs.params)
        artifact_dir = Path(inputs.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        bbox = self._aoi_bbox(inputs)
        files: dict[str, str] = {}
        metadata: dict[str, Any] = {}

        # 1. Peilbuispunten
        peilbuizen_path = artifact_dir / "peilbuizen.gpkg"
        try:
            gdf_pbz = fetch_peilbuizen(
                bbox=bbox,
                output_path=peilbuizen_path,
                extra_buffer_m=params.aoi_buffer_m,
            )
            metadata["n_peilbuizen"] = int(len(gdf_pbz))
            if not gdf_pbz.empty:
                files["peilbuizen_gpkg"] = str(peilbuizen_path)
        except Exception as exc:  # noqa: BLE001 — capture WFS issues
            log.warning("Peilbuizen-WFS faalde: %s", exc)
            metadata["n_peilbuizen"] = 0
            metadata["peilbuizen_error"] = str(exc)

        # 2. KNMI station bepalen + neerslag/verdamping
        lat, lon = self._aoi_centroid_wgs84(inputs)
        if params.knmi_station:
            station_id = params.knmi_station
            station_name = "(handmatig)"
            station_dist_km = None
        else:
            station_id, station_dist_km, station_name = nearest_climate_station(lat, lon)

        metadata["knmi_station"] = {
            "id": station_id,
            "name": station_name,
            "afstand_km": round(station_dist_km, 1) if station_dist_km is not None else None,
        }

        try:
            neerslag, verdamping = fetch_recharge_inputs(
                station_id, start=params.tmin, end=params.tmax
            )
            n_path = artifact_dir / f"knmi_{station_id}_neerslag.csv"
            e_path = artifact_dir / f"knmi_{station_id}_verdamping.csv"
            neerslag.to_csv(n_path, header=True)
            verdamping.to_csv(e_path, header=True)
            files["knmi_neerslag"] = str(n_path)
            files["knmi_verdamping"] = str(e_path)
            metadata["knmi_records"] = int(len(neerslag))
        except Exception as exc:  # noqa: BLE001
            log.warning("KNMI-fetch faalde: %s", exc)
            metadata["knmi_error"] = str(exc)

        # 3. Grondwater-tijdreeksen voor opgegeven IDs
        # Accepteert zowel GLD- als GMW-id's (GMW vereist filter 1 als default).
        gld_series: dict[str, pd.Series] = {}
        gld_coords: dict[str, tuple[float, float]] = {}
        for bro_id in params.gld_ids:
            try:
                s, coords = self._fetch_groundwater_series(
                    bro_id, tmin=params.tmin, tmax=params.tmax,
                )
                if s is None or len(s) == 0:
                    log.warning("%s leeg of geen data", bro_id)
                    continue
                csv_path = artifact_dir / f"{bro_id}.csv"
                s.to_csv(csv_path, header=True)
                files[f"gld_{bro_id}"] = str(csv_path)
                gld_series[bro_id] = s
                if coords is not None:
                    gld_coords[bro_id] = coords
            except Exception as exc:  # noqa: BLE001
                log.warning("%s fetch faalde: %s", bro_id, exc)

        metadata["n_gld_reeksen"] = len(gld_series)
        metadata["gld_coords"] = gld_coords

        raw = PluginRawData(files=files, metadata=metadata)
        # In-memory frames voor analyze (worden niet geserialiseerd)
        if metadata.get("n_peilbuizen", 0) > 0:
            raw.set_frame("peilbuizen", gdf_pbz)
        if "knmi_neerslag" in files:
            raw.set_frame("neerslag", neerslag)
            raw.set_frame("verdamping", verdamping)
        for gld_id, s in gld_series.items():
            raw.set_frame(f"gld_{gld_id}", s)
        return raw

    def analyze(self, inputs: PluginInputs, raw: PluginRawData) -> PluginOutputs:
        params = self.PARAMS_CLASS.model_validate(inputs.params)

        claims: list[Claim] = []
        hypotheses: list[Hypothesis] = []
        artifacts: dict[str, str] = dict(raw.files)
        qgis_layers: list[QgisLayerSpec] = []
        summary: dict[str, Any] = {}
        based_on: list[str] = []
        not_tested: list[str] = []

        # ── Claim: peilbuizen-inventarisatie ────────────────────────────────
        n_pbz = raw.metadata.get("n_peilbuizen", 0)
        if n_pbz > 0:
            claims.append(
                Claim(
                    id=str(uuid.uuid4()),
                    plugin_id=self.PLUGIN_ID,
                    topic="grondwater",
                    text=(
                        f"{n_pbz} BRO-peilbuispunten beschikbaar in/rondom AOI "
                        f"(buffer {params.aoi_buffer_m:.0f} m). Kandidaten voor "
                        "tijdreeks-analyse via fit_pastas_models=True."
                    ),
                    uncertainty="laag",
                    based_on=["BRO GMW REST API (publiek.broservices.nl)"],
                    substantiation=(
                        f"REST-fetch GMW characteristics binnen AOI + "
                        f"{params.aoi_buffer_m:.0f}m buffer leverde {n_pbz} punten."
                    ),
                )
            )
            based_on.append("BRO GMW peilbuispunten (REST API)")
            qgis_layers.append(
                QgisLayerSpec(
                    name="BRO peilbuizen",
                    source_path=raw.files["peilbuizen_gpkg"],
                    layer_type="vector",
                    group="grondwater",
                )
            )
        else:
            not_tested.append("peilbuizen — geen BRO-punten in/rondom AOI")

        # ── Claim: KNMI-station + reeks ─────────────────────────────────────
        knmi = raw.metadata.get("knmi_station")
        knmi_records = raw.metadata.get("knmi_records", 0)
        if knmi and knmi_records > 0:
            afstand_str = (
                f", {knmi['afstand_km']} km van AOI"
                if knmi.get("afstand_km") is not None else ""
            )
            claims.append(
                Claim(
                    id=str(uuid.uuid4()),
                    plugin_id=self.PLUGIN_ID,
                    topic="meteo",
                    text=(
                        f"KNMI station {knmi['id']} ({knmi['name']}{afstand_str}) "
                        f"levert {knmi_records} dagwaarden neerslag + verdamping "
                        f"({params.tmin} → {params.tmax or 'heden'})."
                    ),
                    uncertainty="laag",
                    based_on=["KNMI dagwaarden REST"],
                    substantiation=(
                        "RD (neerslag) en EV24 (Makkink-verdamping) opgehaald uit "
                        "https://daggegevens.knmi.nl/klimatologie/daggegevens."
                    ),
                )
            )
            based_on.append(f"KNMI station {knmi['id']} ({knmi_records} dagen)")
        elif "knmi_error" in raw.metadata:
            not_tested.append(f"KNMI: {raw.metadata['knmi_error'][:80]}")

        # ── Claim: GLD-tijdreeksen ──────────────────────────────────────────
        n_gld = raw.metadata.get("n_gld_reeksen", 0)
        if n_gld > 0:
            claims.append(
                Claim(
                    id=str(uuid.uuid4()),
                    plugin_id=self.PLUGIN_ID,
                    topic="grondwater",
                    text=(
                        f"GLD-tijdreeks(en) opgehaald voor {n_gld} peilbuis(zen). "
                        + ("PASTAS RechargeModel gefit." if params.fit_pastas_models else
                           "Modellering niet uitgevoerd (fit_pastas_models=False).")
                    ),
                    uncertainty="laag",
                    based_on=["BRO GLD REST"],
                    substantiation=(
                        f"Tijdreeksen voor {n_gld} GLD-id(s) opgehaald via "
                        "publiek.broservices.nl/gm/gld/v1."
                    ),
                )
            )
            based_on.append(f"BRO GLD-tijdreeksen ({n_gld})")

        # ── PastaStore schrijven (altijd wanneer er GLD-reeksen zijn) ──────
        adapter = None
        if n_gld > 0 and knmi_records > 0:
            adapter = self._build_pastastore(inputs, raw)
            if adapter is not None:
                # Pad dat pastasdash kan laden = parent/<name>
                store_root = Path(adapter.location.path) / adapter.location.name
                artifacts["pastastore_dir"] = str(store_root)
                based_on.append("PastaStore (lokale opslag voor pastasdash)")
            else:
                not_tested.append(
                    "PastaStore-opslag overgeslagen (pastastore niet geïnstalleerd)"
                )

        # ── PASTAS-fits indien gevraagd ─────────────────────────────────────
        if params.fit_pastas_models and n_gld > 0:
            self._fit_pastas(
                raw=raw,
                params=params,
                claims=claims,
                hypotheses=hypotheses,
                summary=summary,
                based_on=based_on,
                not_tested=not_tested,
                adapter=adapter,
            )
        elif params.gld_ids and not params.fit_pastas_models:
            not_tested.append(
                "PASTAS-modellering — fit_pastas_models stond op False"
            )

        # ── Scope ───────────────────────────────────────────────────────────
        uncertainty_level: str = (
            "laag" if (n_pbz > 0 and knmi_records > 0) else
            "middel" if (n_pbz > 0 or knmi_records > 0) else
            "hoog"
        )
        scope = ScopeStatement(
            scope="plugin",
            subject_id=self.PLUGIN_ID,
            based_on=based_on,
            not_tested=not_tested,
            uncertainty_level=uncertainty_level,  # type: ignore[arg-type]
            consequences=(
                "Grondwaterstand-respons op neerslag is gemodelleerd; resultaten "
                "zijn punt-specifiek per peilbuis."
                if params.fit_pastas_models and n_gld > 0
                else "Inventarisatie van data-beschikbaarheid; geen processuitspraak."
            ),
        )

        summary.update({
            "n_peilbuizen": n_pbz,
            "n_gld_reeksen": n_gld,
            "knmi_station": knmi.get("id") if knmi else None,
            "knmi_records": knmi_records,
        })

        return PluginOutputs(
            plugin_id=self.PLUGIN_ID,
            plugin_version=self.PLUGIN_VERSION,
            claims=claims,
            hypotheses=hypotheses,
            scope=scope,
            artifacts=artifacts,
            qgis_layers=qgis_layers,
            summary=summary,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _aoi_bbox(self, inputs: PluginInputs) -> tuple[float, float, float, float]:
        """Bereken bbox in EPSG:28992 uit aoi_geojson."""
        from shapely.geometry import shape

        geom = shape(inputs.aoi_geojson)
        return tuple(geom.bounds)  # type: ignore[return-value]

    def _aoi_centroid_wgs84(self, inputs: PluginInputs) -> tuple[float, float]:
        """Centroid in WGS84 (lat, lon) — nodig voor KNMI-station-zoekactie."""
        from pyproj import Transformer
        from shapely.geometry import shape

        geom = shape(inputs.aoi_geojson)
        cx, cy = geom.centroid.x, geom.centroid.y
        transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(cx, cy)
        return lat, lon

    def _build_pastastore(
        self,
        inputs: PluginInputs,
        raw: PluginRawData,
    ) -> Any | None:
        """Maak een PastaStore aan en vul met KNMI-stresses + GLD-oseries.

        Returnt de PastaStoreAdapter (open store), of ``None`` als pastastore
        niet beschikbaar is. Coördinaten voor oseries komen uit de peilbuizen-
        GeoDataFrame, met AOI-centroid als fallback.
        """
        try:
            from pastas_adapter.store import PastaStoreAdapter, StoreLocation
        except ImportError:
            return None

        store_dir = Path(inputs.artifact_dir) / "pastastore"
        adapter = PastaStoreAdapter(
            location=StoreLocation(
                backend="pas",
                path=store_dir,
                name=f"lesa_{inputs.session_id[:8]}",
            )
        )

        neerslag = raw.get_frame("neerslag")
        verdamping = raw.get_frame("verdamping")
        knmi_meta = raw.metadata.get("knmi_station", {})
        try:
            if neerslag is not None:
                adapter.add_stress(
                    name="neerslag_KNMI",
                    series=neerslag,
                    kind="prec",
                    metadata={
                        "station": knmi_meta.get("id"),
                        "naam": knmi_meta.get("name"),
                        "eenheid": "mm/dag",
                    },
                )
            if verdamping is not None:
                adapter.add_stress(
                    name="verdamping_KNMI",
                    series=verdamping,
                    kind="evap",
                    metadata={
                        "station": knmi_meta.get("id"),
                        "naam": knmi_meta.get("name"),
                        "eenheid": "mm/dag",
                    },
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("PastaStore-stress schrijven faalde: %s", exc)
            return None

        peilbuizen = raw.get_frame("peilbuizen")
        coord_lookup = self._coord_lookup_from_peilbuizen(peilbuizen)
        # Coords uit hydropandas-fetch hebben voorrang (per-buis exact)
        coord_lookup.update(raw.metadata.get("gld_coords", {}))
        cx_default, cy_default = self._aoi_centroid_rd(inputs)

        for key in list(raw._frames.keys()):
            if not key.startswith("gld_"):
                continue
            gld_id = key.removeprefix("gld_")
            oseries = raw.get_frame(key)
            if oseries is None or oseries.empty:
                continue
            x, y = coord_lookup.get(gld_id, (cx_default, cy_default))
            try:
                adapter.add_oseries(
                    name=gld_id,
                    series=oseries,
                    metadata={
                        "x": float(x),
                        "y": float(y),
                        "eenheid": "m NAP",
                        "bron": "BRO GLD",
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("PastaStore-oseries %s faalde: %s", gld_id, exc)

        return adapter

    def _fetch_groundwater_series(
        self,
        bro_id: str,
        *,
        tmin: str,
        tmax: str | None,
    ) -> tuple[Any | None, tuple[float, float] | None]:
        """Haal een grondwaterstandreeks op voor een GLD- of GMW-id.

        Probeert eerst hydropandas (geeft x, y mee als metadata). Valt
        terug op de directe REST-route voor GLD-id's wanneer hydropandas
        ontbreekt of faalt.

        Returns
        -------
        (series_or_none, coords_or_none)
            Series in m NAP met DatetimeIndex; coords als (x, y) in RD.
        """
        # Pad 1: hydropandas (werkt voor GLD én GMW, geeft directe metadata)
        try:
            from geo_stack.skills.bro.peilbuizen import fetch_groundwater_obs

            tube_nr = 1 if bro_id.startswith("GMW") else None
            obs = fetch_groundwater_obs(bro_id, tube_nr=tube_nr, tmin=tmin, tmax=tmax or "2040-01-01")
            if obs.empty:
                return None, None
            value_col = "values" if "values" in obs.columns else obs.columns[0]
            s = obs[value_col].astype(float).copy()
            s.name = bro_id
            coords = (float(obs.x), float(obs.y)) if getattr(obs, "x", None) and getattr(obs, "y", None) else None
            return s, coords
        except ImportError:
            pass  # geen hpd → fall back naar urllib voor GLD
        except Exception as exc:  # noqa: BLE001
            log.info("hydropandas-fetch faalde voor %s: %s — fallback naar REST", bro_id, exc)

        # Pad 2: directe REST (alleen voor GLD)
        if not bro_id.startswith("GLD"):
            return None, None
        from geo_stack.skills.bro.peilbuizen import fetch_gld_timeseries

        s = fetch_gld_timeseries(bro_id, tmin=tmin, tmax=tmax)
        return (s if len(s) > 0 else None), None

    def _aoi_centroid_rd(self, inputs: PluginInputs) -> tuple[float, float]:
        from shapely.geometry import shape

        geom = shape(inputs.aoi_geojson)
        return geom.centroid.x, geom.centroid.y

    def _coord_lookup_from_peilbuizen(
        self, peilbuizen: Any | None,
    ) -> dict[str, tuple[float, float]]:
        """Bouw mapping van gld_id of bro_id naar (x, y) in EPSG:28992.

        Best-effort: peilbuizen-GeoDataFrame heeft niet altijd een directe
        gld_id-kolom, vaak alleen de GMW-id. We mappen wat we kunnen.
        """
        if peilbuizen is None or peilbuizen.empty:
            return {}
        candidates: list[str] = [
            c for c in ("gld_id", "gld", "bro_id", "gmw_id", "id") if c in peilbuizen.columns
        ]
        if not candidates:
            return {}
        id_col = candidates[0]
        return {
            str(row[id_col]): (row.geometry.x, row.geometry.y)
            for _, row in peilbuizen.iterrows()
            if row.geometry is not None and not row.geometry.is_empty
        }

    def _fit_pastas(
        self,
        raw: PluginRawData,
        params: GrondwaterPastasParams,
        claims: list[Claim],
        hypotheses: list[Hypothesis],
        summary: dict[str, Any],
        based_on: list[str],
        not_tested: list[str],
        adapter: Any | None = None,
    ) -> None:
        """Fit een PASTAS RechargeModel per gld_id; voeg claims/hypothesen toe.

        Als ``adapter`` (PastaStoreAdapter) is meegegeven, worden de gefitte
        modellen ook in de store opgeslagen voor latere inspectie via pastasdash.
        """
        try:
            from pastas_adapter.fit import FitConfig, fit_oseries
        except ImportError as exc:
            not_tested.append(
                f"PASTAS-fit overgeslagen: {exc} "
                "(installeer pastas-adapter[full] om te modelleren)"
            )
            return

        neerslag = raw.get_frame("neerslag")
        verdamping = raw.get_frame("verdamping")
        if neerslag is None or verdamping is None:
            not_tested.append("PASTAS-fit overgeslagen: KNMI-stresses ontbreken")
            return

        fit_results: list[dict[str, Any]] = []
        for gld_id in params.gld_ids:
            oseries = raw.get_frame(f"gld_{gld_id}")
            if oseries is None or len(oseries) < 30:
                not_tested.append(f"PASTAS-fit {gld_id}: te weinig metingen")
                continue

            cfg = FitConfig(
                name=gld_id,
                tmin=params.tmin,
                tmax=params.tmax,
                rfunc="Gamma",
                noise_model=True,
            )
            try:
                result, ml = fit_oseries(
                    oseries=oseries,
                    stresses={"neerslag": neerslag, "verdamping": verdamping},
                    config=cfg,
                )
            except Exception as exc:  # noqa: BLE001
                not_tested.append(f"PASTAS-fit {gld_id} crashte: {exc}")
                continue

            if adapter is not None and result.success and ml is not None:
                try:
                    adapter.add_model(name=gld_id, ml=ml)
                except Exception as exc:  # noqa: BLE001
                    log.warning("PastaStore-model %s opslaan faalde: %s", gld_id, exc)

            fit_results.append({
                "gld_id": gld_id,
                "success": result.success,
                "rsq": result.rsq,
                "rmse": result.rmse,
                "aic": result.aic,
            })

            if result.success and result.rsq is not None:
                kwaliteit = (
                    "laag" if result.rsq > 0.7 else
                    "middel" if result.rsq > 0.4 else
                    "hoog"
                )
                claims.append(
                    Claim(
                        id=str(uuid.uuid4()),
                        plugin_id=self.PLUGIN_ID,
                        topic="grondwater",
                        text=(
                            f"PASTAS-fit voor {gld_id}: R²={result.rsq:.3f}, "
                            f"RMSE={result.rmse:.3f} m."
                        ),
                        uncertainty=kwaliteit,
                        based_on=["PASTAS RechargeModel + Gamma"],
                        substantiation=(
                            f"Fit met KNMI-stresses (RD, EV24) over {params.tmin}–"
                            f"{params.tmax or 'heden'}; rfunc=Gamma, noise_model=True."
                        ),
                    )
                )
                if result.rsq < 0.4:
                    hypotheses.append(
                        Hypothesis(
                            id=str(uuid.uuid4()),
                            plugin_id=self.PLUGIN_ID,
                            proposed_mechanism=(
                                f"Bij {gld_id} is de variatie in grondwaterstand "
                                "niet primair door lokale neerslag/verdamping "
                                "gedreven — externe stress (peilbeheer, kwel, "
                                "wegzijging) speelt mogelijk een dominante rol."
                            ),
                            predicted_observation=(
                                "PASTAS-RechargeModel met alleen KNMI-stresses "
                                f"verklaart minder dan 40% van de variatie (R²={result.rsq:.2f})."
                            ),
                            confidence_level="plausibel",
                            falsifier=(
                                "Een PASTAS-model met aanvullende stress (peilstress "
                                "of kwelflux) verbetert R² niet significant boven "
                                "het neerslag-only model."
                            ),
                            weakest_link=(
                                "Slechte fit kan ook door datakwaliteit (hiaten, "
                                "buitenwaarden) komen, niet door fysica."
                            ),
                            field_protocol=FieldProtocolStub(
                                location_description=f"Peilbuislocatie {gld_id}",
                                indicators_to_observe=[
                                    "Aanwezigheid kwelvegetatie (dotterbloem, holpijp)",
                                    "Inundatiepatroon na droge periode",
                                    "IJzer-/sulfaatuitslag op maaiveld",
                                ],
                            ),
                        )
                    )

        summary["pastas_fits"] = fit_results
        based_on.append(f"PASTAS RechargeModel ({len(fit_results)} fits)")
