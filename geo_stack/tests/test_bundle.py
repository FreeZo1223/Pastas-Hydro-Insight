"""Tests voor fetch_bundle en async_fetch_bundle (geen netwerk)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pytest
from shapely.geometry import box


def _make_gdf(n: int = 3) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": list(range(n))},
        geometry=[box(125_000 + i * 100, 460_000, 125_200 + i * 100, 460_200) for i in range(n)],
        crs="EPSG:28992",
    )


BBOX = (125_000, 460_000, 145_000, 480_000)


@pytest.fixture
def mock_fetch():
    """Patch fetch_features zodat elke dataset 3 dummy-features retourneert."""
    with patch("geo_stack.bundle._fetch_one") as m:
        async def _fake(dataset, bbox, dsyaml, prefer_cn, **kw):
            return dataset, _make_gdf()
        m.side_effect = _fake
        yield m


# ── Unit tests ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_fetch_bundle_retourneert_alle_datasets(mock_fetch, tmp_path):
    from geo_stack.bundle import fetch_bundle
    result = fetch_bundle(
        ["bgt", "bag_3d", "bro_bodemkaart"],
        BBOX,
        cache_dir=str(tmp_path / "cache"),
    )
    assert set(result.keys()) == {"bgt", "bag_3d", "bro_bodemkaart"}
    for gdf in result.values():
        assert isinstance(gdf, gpd.GeoDataFrame)
        assert len(gdf) == 3


@pytest.mark.unit
def test_fetch_bundle_leeg_bij_fout(tmp_path):
    """Een fout in één dataset breekt de rest niet — geeft lege GDF terug."""
    async def _soms_fout(dataset, bbox, dsyaml, prefer_cn, **kw):
        if dataset == "kapot":
            raise RuntimeError("simulated failure")
        return dataset, _make_gdf()

    with patch("geo_stack.bundle._fetch_one", side_effect=_soms_fout):
        from geo_stack.bundle import fetch_bundle
        result = fetch_bundle(
            ["goed", "kapot"],
            BBOX,
            cache_dir=str(tmp_path / "cache"),
        )
    assert "kapot" in result
    assert result["kapot"].empty
    assert not result["goed"].empty


@pytest.mark.unit
def test_fetch_bundle_cache_hit(tmp_path):
    """Tweede aanroep met zelfde args moet uit cache komen, niet opnieuw fetchen."""
    call_count = 0

    async def _count(dataset, bbox, dsyaml, prefer_cn, **kw):
        nonlocal call_count
        call_count += 1
        return dataset, _make_gdf()

    with patch("geo_stack.bundle._fetch_one", side_effect=_count):
        from geo_stack.bundle import fetch_bundle
        cache = str(tmp_path / "cache")
        fetch_bundle(["bgt"], BBOX, cache_dir=cache)
        first_count = call_count
        fetch_bundle(["bgt"], BBOX, cache_dir=cache)  # moet cache raken
        second_count = call_count

    assert first_count == 1
    assert second_count == first_count, "Tweede aanroep mag _fetch_one niet opnieuw roepen"


@pytest.mark.unit
def test_fetch_bundle_ttl_expired(tmp_path):
    """Bundle-cache met verlopen TTL triggert een nieuwe fetch."""
    call_count = 0

    async def _count(dataset, bbox, dsyaml, prefer_cn, **kw):
        nonlocal call_count
        call_count += 1
        return dataset, _make_gdf()

    with patch("geo_stack.bundle._fetch_one", side_effect=_count):
        from geo_stack.bundle import fetch_bundle
        cache = str(tmp_path / "cache")
        fetch_bundle(["bgt"], BBOX, cache_dir=cache, ttl_seconds=0.001)
        import time; time.sleep(0.01)
        fetch_bundle(["bgt"], BBOX, cache_dir=cache, ttl_seconds=0.001)

    assert call_count == 2, "TTL verlopen → twee fetches verwacht"


@pytest.mark.unit
def test_fetch_bundle_cache_uitschakelen(tmp_path):
    """cache_dir='' schakelt de cache uit — altijd opnieuw fetchen."""
    call_count = 0

    async def _count(dataset, bbox, dsyaml, prefer_cn, **kw):
        nonlocal call_count
        call_count += 1
        return dataset, _make_gdf()

    with patch("geo_stack.bundle._fetch_one", side_effect=_count):
        from geo_stack.bundle import fetch_bundle
        fetch_bundle(["bgt"], BBOX, cache_dir="")
        fetch_bundle(["bgt"], BBOX, cache_dir="")

    assert call_count == 2


@pytest.mark.unit
def test_list_bundle_cache_lege_dir(tmp_path):
    """list_bundle_cache op lege of niet-bestaande dir geeft lege lijst."""
    from geo_stack.bundle import list_bundle_cache
    assert list_bundle_cache(tmp_path / "bestaat_niet") == []


@pytest.mark.unit
def test_bundle_hash_volgorde_onafhankelijk():
    """De bundle-hash mag niet afhangen van de volgorde van de dataset-lijst."""
    from geo_stack.bundle import _bundle_hash
    h1 = _bundle_hash(["bgt", "bag_3d"], BBOX, {})
    h2 = _bundle_hash(["bag_3d", "bgt"], BBOX, {})
    assert h1 == h2
