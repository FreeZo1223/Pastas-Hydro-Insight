"""Smoke-tests voor geo_stack.core.normalizer."""

import geopandas as gpd
import pytest
from shapely.geometry import box, MultiPolygon

from geo_stack.core.geo_utils import CRSValidationError
from geo_stack.core.normalizer import _snake_case, normalize_to_geoparquet


def test_normalize_ok(rd_gdf, tmp_path):
    out = tmp_path / "out.parquet"
    result = normalize_to_geoparquet(rd_gdf, out)
    assert result["feature_count"] == 1
    assert result["dropped"] == 0
    assert out.exists()


def test_normalize_reproject(wgs84_gdf, tmp_path):
    out = tmp_path / "out.parquet"
    result = normalize_to_geoparquet(wgs84_gdf, out, reproject=True)
    assert result["feature_count"] == 1
    loaded = gpd.read_parquet(out)
    assert loaded.crs.to_epsg() == 28992


def test_normalize_no_reproject_raises(wgs84_gdf, tmp_path):
    with pytest.raises(CRSValidationError):
        normalize_to_geoparquet(wgs84_gdf, tmp_path / "out.parquet", reproject=False)


def test_normalize_empty(tmp_path):
    gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:28992")
    result = normalize_to_geoparquet(gdf, tmp_path / "out.parquet")
    assert result["feature_count"] == 0


def test_normalize_drops_invalid(tmp_path):
    import shapely
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2]},
        geometry=[box(100_000, 400_000, 110_000, 410_000), None],
        crs="EPSG:28992",
    )
    result = normalize_to_geoparquet(gdf, tmp_path / "out.parquet")
    assert result["feature_count"] == 1
    assert result["dropped"] == 1


@pytest.mark.parametrize("input,expected", [
    ("geometry", "geometry"),
    ("FeatureType", "feature_type"),
    ("BGTIdentificatie", "bgt_identificatie"),  # opeenvolgende caps tellen als één woord
    ("naam-veld", "naam_veld"),
    ("Área", "area"),  # accenten worden getranslitereerd, niet gestript
    ("", "col"),
])
def test_snake_case(input, expected):
    assert _snake_case(input) == expected


# ── Optimalisatie-tests (Hilbert/Z-order, bbox-kolom, zstd) ───────────────────

def test_normalize_zstd_default(rd_gdf, tmp_path):
    """Default compressie moet ZSTD zijn, niet snappy."""
    import pyarrow.parquet as pq

    out = tmp_path / "out.parquet"
    normalize_to_geoparquet(rd_gdf, out)
    pf = pq.ParquetFile(out)
    # alle column-chunks zouden zstd moeten gebruiken
    compressions = {
        pf.metadata.row_group(rg).column(c).compression
        for rg in range(pf.metadata.num_row_groups)
        for c in range(pf.metadata.num_columns)
    }
    assert "ZSTD" in compressions or "zstd" in {c.lower() for c in compressions}


def test_normalize_writes_covering_bbox(rd_gdf, tmp_path):
    """Default schrijft een covering-bbox kolom (vereist geopandas ≥1.0)."""
    out = tmp_path / "out.parquet"
    result = normalize_to_geoparquet(rd_gdf, out)
    assert result["has_covering_bbox"] is True


def test_normalize_compression_override(rd_gdf, tmp_path):
    """Compressie moet override-baar zijn."""
    import pyarrow.parquet as pq

    out = tmp_path / "out.parquet"
    normalize_to_geoparquet(rd_gdf, out, compression="snappy")
    pf = pq.ParquetFile(out)
    compressions = {
        pf.metadata.row_group(rg).column(c).compression.lower()
        for rg in range(pf.metadata.num_row_groups)
        for c in range(pf.metadata.num_columns)
    }
    assert "snappy" in compressions


def test_spatial_sort_clusters_nearby(tmp_path):
    """Z-order sort moet ruimtelijk nabije rijen bij elkaar zetten."""
    import numpy as np
    from shapely.geometry import Point

    rng = np.random.default_rng(42)
    n = 200
    xs = rng.uniform(120_000, 130_000, n)
    ys = rng.uniform(450_000, 460_000, n)
    gdf = gpd.GeoDataFrame(
        {"id": range(n)},
        geometry=[Point(x, y) for x, y in zip(xs, ys)],
        crs="EPSG:28992",
    )
    out = tmp_path / "sorted.parquet"
    result = normalize_to_geoparquet(gdf, out, spatial_sort=True)
    assert result["spatially_sorted"] is True

    loaded = gpd.read_parquet(out)
    # Na Z-order: gemiddelde afstand tussen opeenvolgende centroids moet
    # significant kleiner zijn dan de globale gemiddelde paarafstand.
    centroids = loaded.geometry
    seq_dist = np.mean([
        centroids.iloc[i].distance(centroids.iloc[i + 1])
        for i in range(len(centroids) - 1)
    ])
    # Globale gemiddelde verwacht: ~5000m bij random uniform 10kx10k
    # Z-order nabuur-afstand: typisch <1000m
    assert seq_dist < 2000, f"Z-order gaf gemiddelde nabuur-afstand {seq_dist:.0f}m"


def test_spatial_sort_disabled_for_small_set(rd_gdf, tmp_path):
    """Sort moet overgeslagen worden voor sets <100 rijen."""
    out = tmp_path / "small.parquet"
    result = normalize_to_geoparquet(rd_gdf, out, spatial_sort=True)
    assert result["spatially_sorted"] is False  # 1 rij is < 100


def test_spatial_sort_can_be_disabled(rd_gdf, tmp_path):
    """spatial_sort=False moet altijd zonder sort schrijven."""
    out = tmp_path / "nosort.parquet"
    result = normalize_to_geoparquet(rd_gdf, out, spatial_sort=False)
    assert result["spatially_sorted"] is False


def test_z_order_deterministic(tmp_path):
    """Z-order sort moet deterministisch zijn."""
    from geo_stack.core.normalizer import _z_order_sort
    from shapely.geometry import Point
    import numpy as np

    rng = np.random.default_rng(0)
    n = 150
    gdf = gpd.GeoDataFrame(
        {"id": range(n)},
        geometry=[Point(rng.uniform(0, 1000), rng.uniform(0, 1000)) for _ in range(n)],
        crs="EPSG:28992",
    )
    sorted1 = _z_order_sort(gdf)["id"].tolist()
    sorted2 = _z_order_sort(gdf)["id"].tolist()
    assert sorted1 == sorted2
    # En verschilt van origineel
    assert sorted1 != list(range(n))
