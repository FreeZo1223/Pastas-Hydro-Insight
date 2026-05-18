"""LESA MCP Server — exposes the LESA pipeline as Claude Code tools.

Geen eigen Anthropic-client nodig: Claude Code IS de orchestrator.
De tools wikkelen de PluginRunner, SessionState en registry in.

Starten:
    uv run python -m lesa_agent.mcp.server

Of via Claude Code automatisch via .mcp.json in de projectroot.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ── PROJ fix (zelfde als conftest) ────────────────────────────────────────────
# Moet vóór eerste rasterio/pyproj-import gezet worden.
try:
    import rasterio as _rio
    _rp = Path(_rio.__file__).parent / "proj_data"
    if (_rp / "proj.db").exists():
        os.environ.setdefault("PROJ_DATA", str(_rp))
        os.environ.setdefault("PROJ_LIB", str(_rp))
except Exception:
    pass

# ── Server instantie ──────────────────────────────────────────────────────────

mcp = FastMCP(
    "LESA Agent",
    instructions=(
        "Je bent een LESA-assistent (LandschapsEcologische Systeem Analyse).\n"
        "Werk in dialoog met de expert — niet autonoom.\n\n"
        "WERKWIJZE PER PLUGIN-STAP (verplicht):\n"
        "1. Roep lesa_preview_plugin aan vóór lesa_run_plugin. Toon endpoint, "
        "bbox, buffer, parameters en geschat datavolume.\n"
        "2. Vraag de expert óf en met welke parameters je verder mag — bijvoorbeeld "
        "resolutie, buffer-afstand, of een ander product (DTM/DSM).\n"
        "3. Pas na bevestiging: lesa_run_plugin.\n"
        "4. Roep daarna lesa_get_artifact_paths aan en toon de paden zodat de "
        "expert in QGIS visueel kan verifiëren vóór je verdergaat.\n"
        "5. Pas na visuele bevestiging: volgende rangorde-stap.\n\n"
        "RANGORDE (Bakker 1979): geologie (1) → geomorfologie (2) → bodem (3) → "
        "grondwater (4) → oppervlaktewater (5) → vegetatie (6) → mens (7). "
        "Sla posities over met lesa_skip_plugin met expliciete motivatie.\n\n"
        "HYPOTHESES: alleen formuleren met falsifier én weakest_link. "
        "Confidence eerlijk: 'speculatief' als data dun is, niet 'plausibel'.\n\n"
        "Alle analyse-CRS is EPSG:28992 (RD New)."
    ),
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SESSIONS_DIR = _REPO_ROOT / "sessions"


def _sessions_dir() -> Path:
    path = Path(os.environ.get("LESA_SESSIONS_DIR", str(_DEFAULT_SESSIONS_DIR)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_store():
    from lesa.session.local_store import LocalSessionStore
    return LocalSessionStore(base_dir=_sessions_dir())


def _get_registry():
    from lesa.plugins._registry import get_registry
    return get_registry()


# ── QGIS-laag-annotatie (filename → layer hint) ───────────────────────────────

_QGIS_LAYER_HINTS: dict[str, dict[str, str]] = {
    ".tif": {"layer_type": "raster", "qgis_action": "Sleep .tif in QGIS-canvas"},
    ".tiff": {"layer_type": "raster", "qgis_action": "Sleep .tif in QGIS-canvas"},
    ".gpkg": {"layer_type": "vector", "qgis_action": "Sleep .gpkg in QGIS; kies laag"},
    ".geojson": {"layer_type": "vector", "qgis_action": "Sleep .geojson in QGIS"},
    ".shp": {"layer_type": "vector", "qgis_action": "Sleep .shp in QGIS"},
    ".parquet": {"layer_type": "vector", "qgis_action": "QGIS 3.34+: open als GeoParquet"},
    ".csv": {"layer_type": "table", "qgis_action": "Layer → Add Delimited Text"},
    ".qml": {"layer_type": "style", "qgis_action": "Right-click laag → Properties → Style → Load"},
    ".qpt": {"layer_type": "layout-template", "qgis_action": "Project → Layout Manager → New from template"},
}


def _annotate_qgis_layers(artifacts: dict[str, str]) -> list[dict[str, Any]]:
    """Verrijk artifact-paden met QGIS-laaghints op basis van extensie."""
    out: list[dict[str, Any]] = []
    for name, path_str in artifacts.items():
        path = Path(path_str)
        ext = path.suffix.lower()
        hint = _QGIS_LAYER_HINTS.get(ext, {"layer_type": "unknown", "qgis_action": "Onbekend bestandstype"})
        size_mb = None
        if path.exists():
            try:
                size_mb = round(path.stat().st_size / 1_048_576, 2)
            except OSError:
                pass
        out.append({
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "size_mb": size_mb,
            **hint,
        })
    return out


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def lesa_load_aoi(file_path: str, layer: str | None = None) -> dict:
    """Laad een AOI uit een ruimtelijke datafile.

    Ondersteunde formaten:
    - .geojson / .json — gelezen als pure GeoJSON
    - .gpkg / .shp / .gml / .kml / .fgb — via geopandas (alle GDAL-driver-formats)

    Auto-reproject naar EPSG:28992 als de bron-CRS afwijkt. Bij meerdere
    features → unie als single polygon. Geeft GeoJSON-geometry terug + bbox
    + area_ha.

    Args:
        file_path: Absoluut pad of pad relatief aan repo-root.
        layer: Voor multi-layer formaten (gpkg) — laagnaam. Default = eerste laag.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    if not path.exists():
        return {"error": f"Bestand niet gevonden: {path}"}

    suffix = path.suffix.lower()

    if suffix in (".geojson", ".json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("type") == "FeatureCollection":
            features = data.get("features", [])
            if not features:
                return {"error": "FeatureCollection is leeg"}
            data = features[0]
        if data.get("type") == "Feature":
            data = data["geometry"]
        # Compute bbox/area via shapely
        from shapely.geometry import shape
        geom = shape(data)
        bbox = list(geom.bounds)
        area_ha = round(geom.area / 10_000, 1)
        return {
            "geometry": data,
            "path": str(path),
            "format": "geojson",
            "bbox_rd": bbox,
            "area_ha": area_ha,
            "crs_assumed": "EPSG:28992 (geen reproject mogelijk uit pure GeoJSON)",
        }

    # Geopandas-pad (gpkg, shp, gml, kml, fgb, ...)
    try:
        import geopandas as gpd
    except ImportError:
        return {"error": "geopandas niet geïnstalleerd (vereist voor .gpkg/.shp)"}

    try:
        gdf = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Kan {path.name} niet lezen: {exc}"}

    if gdf.empty:
        return {"error": f"{path.name} bevat geen features"}

    # Reproject naar RD als nodig
    src_crs = str(gdf.crs) if gdf.crs is not None else "onbekend"
    if gdf.crs is None or gdf.crs.to_epsg() != 28992:
        try:
            gdf = gdf.to_crs("EPSG:28992")
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Reprojectie naar EPSG:28992 faalde: {exc}"}

    # Unie alle features tot één polygon
    geom = gdf.union_all() if hasattr(gdf, "union_all") else gdf.unary_union
    bbox = list(geom.bounds)
    area_ha = round(geom.area / 10_000, 1)

    # Naar GeoJSON-dict
    import shapely.geometry as sgeom
    geometry_dict = sgeom.mapping(geom)

    return {
        "geometry": geometry_dict,
        "path": str(path),
        "format": suffix.lstrip("."),
        "n_features_unioned": int(len(gdf)),
        "src_crs": src_crs,
        "bbox_rd": bbox,
        "area_ha": area_ha,
    }


@mcp.tool()
def lesa_create_session(
    project_name: str,
    aoi_geojson: dict,
    scale_level: int = 2,
    landscape_type: str = "duinen",
) -> dict:
    """Maak een nieuwe LESA-sessie aan.

    Args:
        project_name: Naam van het project (bijv. "Burgh-Haamstede 2026")
        aoi_geojson: GeoJSON Polygon geometry in EPSG:28992. Gebruik
                     lesa_load_aoi() om dit vanuit een bestand te laden.
        scale_level: 1=regionaal, 2=lokaal (standaard), 3=perceel
        landscape_type: duinen | beekdal | veen | zandlandschap | klei

    Geeft session_id terug — sla op voor vervolgaanroepen.
    """
    from lesa.domain.aoi import AOI
    from lesa.session.state import SessionState

    aoi = AOI(geometry=aoi_geojson, crs="EPSG:28992", name=project_name, source="mcp_tool")
    session = SessionState(
        project_name=project_name,
        aoi=aoi,
        scale_level=scale_level,  # type: ignore[arg-type]
        landscape_type=landscape_type,  # type: ignore[arg-type]
    )
    store = _get_store()
    store.save(session)

    return {
        "session_id": session.session_id,
        "project_name": project_name,
        "scale_level": scale_level,
        "landscape_type": landscape_type,
        "bbox": list(aoi.bbox),
        "sessions_dir": str(_sessions_dir() / session.session_id),
        "tip": "Gebruik lesa_list_plugins() om te zien welke plugins beschikbaar zijn.",
    }


@mcp.tool()
def lesa_list_sessions() -> list[dict]:
    """Toon alle bestaande LESA-sessies."""
    return _get_store().list_sessions()


@mcp.tool()
def lesa_list_plugins(landscape_type: str | None = None) -> list[dict]:
    """Toon alle beschikbare plugins met rangorde, beschrijving en vereisten.

    Args:
        landscape_type: filter op duinen | beekdal | veen | zandlandschap | klei
                        (None = toon alle)
    """
    registry = _get_registry()
    return [
        {
            "id": m.id,
            "name": m.name,
            "rangorde": m.rangorde_position,
            "description": m.description,
            "landscape_types": m.landscape_types or ["alle"],
            "prerequisites": m.prerequisites or [],
            "version": m.version,
        }
        for m in registry.list_plugins(landscape_type=landscape_type)
    ]


@mcp.tool()
def lesa_preview_plugin(
    session_id: str,
    plugin_id: str,
    params: dict[str, Any] | None = None,
) -> dict:
    """Toon WAT een plugin zou doen vóór er HTTP-calls gebeuren.

    Geen fetch, geen schijf-I/O. Gebruik dit altijd vóór lesa_run_plugin
    om met de expert te bevestigen dat de parameters kloppen.

    Geeft terug:
    - Plugin metadata (naam, beschrijving, rangorde, prerequisites)
    - Rangorde-check: kan deze plugin nu draaien?
    - Landscape-check
    - Effectieve parameters (defaults + jouw overrides) + JSON Schema
    - AOI: bbox, buffered bbox, oppervlakte
    - Geschat datavolume (voor raster-plugins)
    - Waarschuwingen
    """
    from lesa.domain.aoi import AOI
    from lesa.domain.rangorde import can_run
    from lesa.session.local_store import SessionNotFoundError

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    registry = _get_registry()
    meta = registry.get_meta(plugin_id)
    if meta is None:
        return {"error": f"Plugin '{plugin_id}' niet gevonden"}

    warnings: list[str] = []

    # Rangorde + landscape check
    ok, msg = can_run(
        meta.rangorde_position,
        session.completed_positions(),
        session.skipped_positions(),
    )
    if not ok:
        warnings.append(f"Rangorde-blokkade: {msg}")

    if (
        session.landscape_type is not None
        and "all" not in meta.landscape_types
        and session.landscape_type not in meta.landscape_types
    ):
        warnings.append(
            f"Plugin niet bedoeld voor landschapstype '{session.landscape_type}' "
            f"(ondersteund: {meta.landscape_types})"
        )

    # Params: defaults + user overrides
    instance = registry.get_instance(plugin_id)
    schema = instance.params_schema()
    defaults = {
        name: prop.get("default")
        for name, prop in schema.get("properties", {}).items()
        if "default" in prop
    }
    effective_params = {**defaults, **(params or {})}

    # Validate via PARAMS_CLASS to catch errors early
    params_cls = getattr(instance, "PARAMS_CLASS", None)
    validated_params = effective_params
    if params_cls is not None:
        try:
            validated_params = params_cls.model_validate(effective_params).model_dump()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Parameter-validatie zou falen: {exc}")

    # AOI bbox + buffered
    aoi = session.aoi
    bbox_native = list(aoi.bbox)
    buffer_m = float(validated_params.get("aoi_buffer_m", 0.0) or 0.0)
    bbox_buffered = [
        bbox_native[0] - buffer_m,
        bbox_native[1] - buffer_m,
        bbox_native[2] + buffer_m,
        bbox_native[3] + buffer_m,
    ]
    width_m = bbox_buffered[2] - bbox_buffered[0]
    height_m = bbox_buffered[3] - bbox_buffered[1]
    area_ha = round((width_m * height_m) / 10000, 1)

    # Schat datavolume voor raster-plugins (resolutie² * area)
    estimate: dict[str, Any] = {}
    resolution = validated_params.get("resolution")
    if resolution and isinstance(resolution, (int, float)):
        n_cells = (width_m / resolution) * (height_m / resolution)
        size_mb = round(n_cells * 4 / 1_048_576, 1)  # float32
        estimate["raster_cells"] = int(n_cells)
        estimate["estimated_size_mb"] = size_mb
        if size_mb > 200:
            warnings.append(
                f"Datavolume groot ({size_mb} MB). Overweeg lagere resolutie of kleinere buffer."
            )

    return {
        "plugin": {
            "id": meta.id,
            "name": meta.name,
            "version": meta.version,
            "rangorde": meta.rangorde_position,
            "description": meta.description.strip(),
            "prerequisites": meta.prerequisites,
            "landscape_types": meta.landscape_types,
        },
        "kan_draaien": ok,
        "params": {
            "effective": validated_params,
            "user_overrides": params or {},
            "schema": schema,
        },
        "aoi": {
            "bbox_native_rd": bbox_native,
            "bbox_buffered_rd": bbox_buffered,
            "buffer_m": buffer_m,
            "area_ha": area_ha,
        },
        "estimate": estimate,
        "warnings": warnings,
        "next_step": (
            "Bespreek met de expert; pas params aan; daarna lesa_run_plugin"
            if not warnings else "Los waarschuwingen op of bevestig met expert"
        ),
    }


@mcp.tool()
async def lesa_run_plugin(
    session_id: str,
    plugin_id: str,
    params: dict[str, Any] | None = None,
) -> dict:
    """Draai een LESA-plugin: haalt data op en analyseert.

    BELANGRIJK: roep eerst lesa_preview_plugin aan en bevestig parameters
    met de expert. Pas daarna deze tool gebruiken.

    Geeft terug: claims, hypothesen, scope, artifact-paden met QGIS-instructie.
    """
    from lesa.agent.runner import PluginRunner
    from lesa.session.local_store import SessionNotFoundError

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    registry = _get_registry()
    runner = PluginRunner(registry=registry, store=store)
    result = await runner.run(session, plugin_id, params or {})
    summary = result.as_summary()

    # Verrijk met QGIS-paden zodat de expert direct kan visualiseren
    if result.ok and result.outputs is not None:
        summary["qgis_layers"] = _annotate_qgis_layers(result.outputs.artifacts)
        summary["next_step"] = (
            "Laad bovenstaande lagen in QGIS, verifieer visueel, "
            "en bevestig met de expert vóór de volgende rangorde-stap."
        )
    return summary


@mcp.tool()
def lesa_skip_plugin(session_id: str, plugin_id: str, reason: str) -> dict:
    """Sla een rangorde-positie over zodat de volgende plugin kan draaien.

    Verplichte motivatie — bijv.:
    - "Geen grondwaterdata beschikbaar voor dit duingebied"
    - "Geologie-kaart ontbreekt voor dit schaalniveau; directe bodem-analyse"

    Args:
        session_id: Van lesa_create_session()
        plugin_id: Plugin-id (bijv. "bodem_bro") of rangorde-naam
                   (bijv. "geologie") als er nog geen plugin voor is.
        reason: Inhoudelijke motivatie (minimaal 10 tekens)
    """
    from lesa.domain.rangorde import RANGORDE
    from lesa.session.local_store import SessionNotFoundError
    from lesa.session.state import SkippedPlugin

    if len(reason.strip()) < 10:
        return {"error": "Geef een inhoudelijke reden op (minimaal 10 tekens)"}

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    registry = _get_registry()
    meta = registry.get_meta(plugin_id)
    if meta is not None:
        rangorde_pos = meta.rangorde_position
    else:
        # Fallback: plugin_id is een rangorde-naam (bijv. "geologie")
        name_to_pos = {name: pos for pos, name in RANGORDE.items()}
        rangorde_pos = name_to_pos.get(plugin_id)
        if rangorde_pos is None:
            return {"error": f"Plugin '{plugin_id}' niet gevonden in registry en geen bekende rangorde-naam"}

    session.skipped_plugins.append(
        SkippedPlugin(
            plugin_id=plugin_id,
            rangorde_position=rangorde_pos,
            reason=reason,
        )
    )
    store.save(session)
    return {"ok": True, "plugin_id": plugin_id, "rangorde": rangorde_pos}


@mcp.tool()
def lesa_get_session_state(session_id: str) -> dict:
    """Haal de volledige sessie-status op.

    Toont voortgang, claims, hypothesen, scope en kostenoverzicht.
    """
    from lesa.session.local_store import SessionNotFoundError

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    scope = session.session_scope()
    return {
        "session_id": session_id,
        "project_name": session.project_name,
        "scale_level": session.scale_level,
        "landscape_type": session.landscape_type,
        "voortgang": {
            "completed": [r.plugin_id for r in session.plugin_runs if r.status == "completed"],
            "failed": [r.plugin_id for r in session.plugin_runs if r.status == "failed"],
            "skipped": [s.plugin_id for s in session.skipped_plugins],
        },
        "claims": [
            {"topic": c.topic, "text": c.text, "uncertainty": c.uncertainty}
            for c in session.claims
        ],
        "hypothesen": [
            {
                "statement": h.statement,
                "mechanisme": h.proposed_mechanism,
                "confidence": h.confidence_level,
                "falsifier": h.falsifier,
                "weakest_link": h.weakest_link,
            }
            for h in session.hypotheses
        ],
        "scope": {
            "uncertainty_level": scope.uncertainty_level,
            "not_tested": scope.not_tested,
            "consequences": scope.consequences,
        },
        "artifacts_dir": str(_sessions_dir() / session_id / "data"),
    }


@mcp.tool()
def lesa_get_artifact_paths(
    session_id: str,
    plugin_id: str | None = None,
) -> dict:
    """Geef alle artifact-paden van een sessie met QGIS-instructies.

    Laat de expert visueel verifiëren wat er op schijf staat. Filter op
    plugin_id voor één specifieke run, of laat leeg voor alle plugins.

    Returnt per plugin een lijst van bestanden met:
    - name, path (absoluut), size_mb, layer_type, qgis_action
    """
    from lesa.session.local_store import SessionNotFoundError

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    runs_by_plugin: dict[str, list[dict[str, Any]]] = {}
    for run in session.plugin_runs:
        if plugin_id is not None and run.plugin_id != plugin_id:
            continue
        if run.status != "completed":
            continue
        runs_by_plugin.setdefault(run.plugin_id, []).extend(
            _annotate_qgis_layers(run.artifacts)
        )

    return {
        "session_id": session_id,
        "session_dir": str(_sessions_dir() / session_id),
        "plugins": runs_by_plugin,
        "qgis_tip": (
            "Open QGIS, sleep de bestanden in het canvas. "
            "Voor MCP-gebruik: stel ze beschikbaar via mcp__qgis-mcp__add_raster_layer "
            "of mcp__qgis-mcp__add_vector_layer."
        ),
    }


@mcp.tool()
def lesa_propose_hypothesis(
    session_id: str,
    proposed_mechanism: str,
    predicted_observation: str,
    confidence_level: str,
    falsifier: str,
    weakest_link: str,
    field_indicators: list[str] | None = None,
) -> dict:
    """Voeg een handmatige hypothese toe aan de sessie.

    Gebruik dit als je op basis van meerdere plugin-resultaten een
    overkoepelende hypothese wilt formuleren.

    Args:
        proposed_mechanism: Welk proces wordt verondersteld (oorzaak-gevolg)
        predicted_observation: Wat zou zichtbaar moeten zijn als de hypothese klopt
        confidence_level: "sterk_onderbouwd" | "plausibel" | "speculatief"
        falsifier: Observatie die de hypothese zou weerleggen
        weakest_link: De zwakste aanname in de redenering
        field_indicators: Optionele veldkenmerken om op te letten
    """
    import uuid

    from lesa.domain.hypothesis import FieldProtocolStub, Hypothesis
    from lesa.session.local_store import SessionNotFoundError

    store = _get_store()
    try:
        session = store.load(session_id)
    except SessionNotFoundError:
        return {"error": f"Sessie '{session_id}' niet gevonden"}

    field_protocol = None
    if field_indicators:
        field_protocol = FieldProtocolStub(
            location_description="Handmatig vastgesteld op basis van bureauanalyse",
            indicators_to_observe=field_indicators,
        )

    hyp = Hypothesis(
        id=str(uuid.uuid4()),
        plugin_id="manual",
        proposed_mechanism=proposed_mechanism,
        predicted_observation=predicted_observation,
        confidence_level=confidence_level,  # type: ignore[arg-type]
        falsifier=falsifier,
        weakest_link=weakest_link,
        field_protocol=field_protocol,
    )
    session.add_hypothesis(hyp)
    store.save(session)
    return {"ok": True, "hypothesis_id": hyp.id, "confidence": confidence_level}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
