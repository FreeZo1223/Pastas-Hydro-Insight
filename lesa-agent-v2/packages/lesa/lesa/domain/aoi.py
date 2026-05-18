"""AOI en SystemBoundary — de twee geografische grenzen in een LESA-sessie.

AOI           = bestuurlijke/opdrachtgrens (uit briefing of GeoJSON).
SystemBoundary = ecohydrologische systeemgrens (voorgesteld door agent,
                 geaccepteerd/bewerkt door expert).

Beide worden bewaard als GeoJSON-geometry dict in EPSG:28992.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AOI(BaseModel):
    """Gebied van interesse — bestuurlijke opdrachtgrens."""

    geometry: dict[str, Any] = Field(
        description="GeoJSON geometry object (Polygon of MultiPolygon) in EPSG:28992"
    )
    crs: str = Field(default="EPSG:28992")
    name: str | None = Field(default=None, description="Optionele projectnaam voor dit gebied")
    source: str = Field(
        description="Herkomst: 'user_geojson' | 'geocode:<query>' | 'drawn' | 'wkt'"
    )

    @model_validator(mode="after")
    def _validate_geometry_type(self) -> "AOI":
        allowed = {"Polygon", "MultiPolygon"}
        gtype = self.geometry.get("type")
        if gtype not in allowed:
            raise ValueError(
                f"AOI geometry moet Polygon of MultiPolygon zijn, kreeg {gtype!r}"
            )
        return self

    def to_shapely(self):
        """Converteert naar shapely geometry (lazy import)."""
        from shapely.geometry import shape
        return shape(self.geometry)

    def to_geodataframe(self):
        """Converteert naar geopandas GeoDataFrame in EPSG:28992."""
        import geopandas as gpd
        return gpd.GeoDataFrame(
            {"name": [self.name or "aoi"]},
            geometry=[self.to_shapely()],
            crs=self.crs,
        )

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(minx, miny, maxx, maxy) in EPSG:28992."""
        bounds = self.to_shapely().bounds
        return (bounds[0], bounds[1], bounds[2], bounds[3])

    @classmethod
    def from_geojson_file(cls, path: "Path | str", source: str = "user_geojson") -> "AOI":
        """Laad AOI uit een GeoJSON-bestand."""
        import json
        from pathlib import Path

        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("type") == "FeatureCollection":
            features = data.get("features", [])
            if not features:
                raise ValueError("FeatureCollection is leeg")
            geometry = features[0]["geometry"]
        elif data.get("type") == "Feature":
            geometry = data["geometry"]
        else:
            geometry = data  # al een geometry object

        return cls(geometry=geometry, source=source)

    @classmethod
    def from_wkt(cls, wkt: str, source: str = "wkt") -> "AOI":
        """Laad AOI uit een WKT-string (EPSG:28992 verwacht)."""
        import shapely.wkt
        geom = shapely.wkt.loads(wkt)
        return cls(geometry=geom.__geo_interface__, source=source)


class SystemBoundary(BaseModel):
    """Ecohydrologische systeemgrens — afgeleid van stroomgebied/geohydrologie.

    Wordt voorgesteld door de ``systeemgrens_voorstel``-plugin en
    geaccepteerd/bewerkt door de expert voordat andere plugins hierop vertrouwen.
    """

    geometry: dict[str, Any]
    crs: str = Field(default="EPSG:28992")
    derivation_method: str = Field(
        description="Hoe afgeleid: 'ahn_watershed' | 'nhi_model' | 'expert_drawn' | 'aoi_copy'"
    )
    expert_accepted: bool = Field(default=False)
    notes: str | None = None

    def to_shapely(self):
        from shapely.geometry import shape
        return shape(self.geometry)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        bounds = self.to_shapely().bounds
        return (bounds[0], bounds[1], bounds[2], bounds[3])
