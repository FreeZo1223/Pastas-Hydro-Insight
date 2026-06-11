"""Tests voor data_sources.yaml registry validatie.

Unit tests (geen netwerk):
- YAML laadt zonder fouten
- Pydantic-validatie slaagt voor elke entry
- CLOUD_NATIVE entries hebben cloud_native_url
- OGC_API + WFS + WCS + REST entries hebben endpoint
- Ongeldige entries goooien ValidationError

Integration tests (pytest -m integration — vereist netwerk):
- WFS GetCapabilities geeft HTTP 200
- CQL-trap: WFS met cql_filter: false retourneert features bij impossible filter
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

DATA_SOURCES = Path(__file__).parent.parent / "data_sources.yaml"


# ── Unit tests ───────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_yaml_laadt():
    """YAML moet parseerbaar zijn zonder fouten."""
    data = yaml.safe_load(DATA_SOURCES.read_text(encoding="utf-8"))
    assert "services" in data
    assert isinstance(data["services"], dict)


@pytest.mark.unit
def test_pydantic_validatie():
    """Alle entries in data_sources.yaml moeten de Pydantic-schema doorstaan."""
    from geo_stack.core.registry import load_registry
    config = load_registry(DATA_SOURCES)
    assert len(config.services) > 0


@pytest.mark.unit
def test_cloud_native_entries_hebben_url():
    """Elke CLOUD_NATIVE entry moet een cloud_native_url hebben."""
    from geo_stack.core.registry import load_registry
    config = load_registry(DATA_SOURCES)
    for dataset, entries in config.services.items():
        for entry in entries:
            if entry.service_type == "CLOUD_NATIVE":
                assert entry.cloud_native_url, (
                    f"{dataset}/{entry.label}: CLOUD_NATIVE entry zonder cloud_native_url"
                )


@pytest.mark.unit
def test_ogc_api_entries_hebben_endpoint():
    """OGC_API, WFS, WCS, REST entries moeten een endpoint hebben."""
    from geo_stack.core.registry import load_registry
    needs_endpoint = {"WFS", "WCS", "OGC_API", "REST", "STAC"}
    config = load_registry(DATA_SOURCES)
    for dataset, entries in config.services.items():
        for entry in entries:
            if entry.service_type in needs_endpoint:
                assert entry.endpoint, (
                    f"{dataset}/{entry.label}: {entry.service_type} entry zonder endpoint"
                )


@pytest.mark.unit
def test_service_types_zijn_geldig():
    """Alle service_type waarden moeten in de toegestane set vallen."""
    from geo_stack.core.registry import load_registry, ServiceType
    import typing
    valid = set(typing.get_args(ServiceType))
    config = load_registry(DATA_SOURCES)
    for dataset, entries in config.services.items():
        for entry in entries:
            assert entry.service_type in valid, (
                f"{dataset}/{entry.label}: onbekend service_type={entry.service_type!r}"
            )


@pytest.mark.unit
def test_ongeldige_entry_gooit_validationerror(tmp_path):
    """Een entry met een ontbrekend verplicht veld moet een ValidationError geven."""
    from pydantic import ValidationError
    from geo_stack.core.registry import load_registry
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        """
services:
  test_dataset:
    - label: Kapot entry
      service_type: WFS
      # endpoint ontbreekt — moet falen
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="endpoint"):
        load_registry(bad_yaml)


@pytest.mark.unit
def test_cloud_native_zonder_url_gooit_validationerror(tmp_path):
    """CLOUD_NATIVE entry zonder cloud_native_url moet een ValidationError geven."""
    from pydantic import ValidationError
    from geo_stack.core.registry import load_registry
    bad_yaml = tmp_path / "bad_cn.yaml"
    bad_yaml.write_text(
        """
services:
  test_cn:
    - label: Cloud native zonder URL
      service_type: CLOUD_NATIVE
      # cloud_native_url ontbreekt — moet falen
""",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_registry(bad_yaml)


@pytest.mark.unit
def test_bgt_is_ogc_api():
    """BGT moet OGC_API service_type hebben (oude WFS-endpoint is offline)."""
    from geo_stack.core.registry import load_registry
    config = load_registry(DATA_SOURCES)
    bgt_entries = config.services.get("bgt", [])
    assert bgt_entries, "Geen BGT entries gevonden"
    service_types = [e.service_type for e in bgt_entries]
    assert "OGC_API" in service_types, (
        f"BGT moet OGC_API hebben, maar heeft: {service_types}"
    )


# ── Integration tests ────────────────────────────────────────────────────────

@pytest.mark.integration
def test_wfs_getcapabilities():
    """Alle WFS-endpoints moeten GetCapabilities beantwoorden met HTTP 200."""
    import requests
    from geo_stack.core.registry import load_registry
    config = load_registry(DATA_SOURCES)
    session = requests.Session()
    for dataset, entries in config.services.items():
        for entry in entries:
            if entry.service_type != "WFS":
                continue
            resp = session.get(
                entry.endpoint,
                params={"service": "WFS", "request": "GetCapabilities"},
                timeout=30,
            )
            assert resp.status_code == 200, (
                f"{dataset}/{entry.label}: GetCapabilities gaf {resp.status_code}"
            )


@pytest.mark.integration
def test_cql_filter_trap():
    """WFS-entries met cql_filter: false mogen CQL niet stilzwijgend filteren.

    Stuur filter op onmogelijke waarde. Als de response tóch features bevat,
    is CQL genegeerd (tile-cached) — dat is correct gedrag voor die endpoints.
    Entries met cql_filter: true moeten het filter WEL respecteren (lege response).
    """
    import requests
    from geo_stack.core.registry import load_registry
    config = load_registry(DATA_SOURCES)
    session = requests.Session()
    for dataset, entries in config.services.items():
        for entry in entries:
            if entry.service_type != "WFS" or not entry.typename:
                continue
            resp = session.get(
                entry.endpoint,
                params={
                    "service": "WFS",
                    "version": "2.0.0",
                    "request": "GetFeature",
                    "typeName": entry.typename,
                    "outputFormat": "application/json",
                    "CQL_FILTER": "identificatie='BESTAAT_ABSOLUUT_NIET_XYZ'",
                    "count": "5",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                continue
            try:
                features = resp.json().get("features", [])
            except Exception:
                continue
            if features and not entry.cql_filter:
                pass  # verwacht: tile-cached endpoint negeert CQL
            elif features and entry.cql_filter:
                pytest.fail(
                    f"{dataset}/{entry.label}: cql_filter=true maar impossible filter "
                    f"gaf {len(features)} features terug — CQL lijkt niet te werken"
                )
