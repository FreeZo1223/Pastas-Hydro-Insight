"""Pydantic-schema voor data_sources.yaml.

Gebruik ``load_registry()`` om de YAML te laden én te valideren.
Fouten in het YAML-bestand (onbekend service_type, ontbrekend endpoint)
resulteren in een ``pydantic.ValidationError`` met een beschrijvende melding.

Gebruik::

    from geo_stack.core.registry import load_registry, validate_registry

    config = load_registry()          # laadt + valideert data_sources.yaml
    warnings = validate_registry()    # returnt lijst van zachte waarschuwingen
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

log = logging.getLogger(__name__)

_DEFAULT_YAML = Path(
    os.environ.get(
        "GEO_STACK_DATA_SOURCES",
        str(Path(__file__).parent.parent.parent / "data_sources.yaml"),
    )
)

ServiceType = Literal[
    "WFS", "WCS", "WMS", "OGC_API", "STAC", "REST",
    "CLOUD_NATIVE", "COMPOSITE", "GEE",
]


class ServiceEntry(BaseModel):
    """Één service-entry in data_sources.yaml."""

    label: str
    service_type: ServiceType
    endpoint: str | None = None
    cloud_native_url: str | None = None
    module: str | None = None
    cql_filter: bool = False
    default_crs: str = "EPSG:28992"
    typename: str | None = None
    warning: str | None = None
    note: str | None = None
    source_version: str | None = None
    update_cadence: str | None = None
    auth_required: bool = False

    model_config = {"extra": "allow"}

    @field_validator("endpoint", "cloud_native_url", mode="before")
    @classmethod
    def must_be_url_or_none(cls, v: Any) -> Any:
        if v is None:
            return v
        v = str(v)
        if not (
            v.startswith("http://")
            or v.startswith("https://")
            or v.startswith("GOOGLE/")   # GEE asset-paden
        ):
            raise ValueError(f"Verwacht http(s):// URL, kreeg: {v!r}")
        return v

    @model_validator(mode="after")
    def check_required_fields(self) -> "ServiceEntry":
        if self.service_type == "CLOUD_NATIVE" and not self.cloud_native_url:
            raise ValueError(
                f"Entry {self.label!r} heeft service_type=CLOUD_NATIVE "
                f"maar geen cloud_native_url."
            )
        if self.service_type in ("WFS", "WCS", "OGC_API", "STAC", "REST") and not self.endpoint:
            raise ValueError(
                f"Entry {self.label!r} heeft service_type={self.service_type} "
                f"maar geen endpoint."
            )
        return self


class DataSourcesConfig(BaseModel):
    """Root-model voor data_sources.yaml."""

    services: dict[str, list[ServiceEntry]]


def load_registry(path: Path | str | None = None) -> DataSourcesConfig:
    """Laad en valideer data_sources.yaml via Pydantic.

    Parameters
    ----------
    path
        Pad naar het yaml-bestand. ``None`` = gebruik de standaard locatie
        (``geo_stack/data_sources.yaml``).

    Returns
    -------
    DataSourcesConfig
        Gevalideerd config-object.

    Raises
    ------
    FileNotFoundError
        Als het yaml-bestand niet bestaat.
    pydantic.ValidationError
        Als het yaml-bestand ongeldige velden bevat.
    """
    yaml_path = Path(path) if path else _DEFAULT_YAML
    if not yaml_path.exists():
        raise FileNotFoundError(f"data_sources.yaml niet gevonden: {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    return DataSourcesConfig.model_validate(raw)


def validate_registry(path: Path | str | None = None) -> list[str]:
    """Valideer de registry en return zachte waarschuwingen.

    Naast de harde Pydantic-validatie (die een exception gooit) controleert
    deze functie ook:
    - WFS-entries zonder typename (kunnen niet generiek worden gedispatcht)
    - ``module:``-paden die niet importeerbaar zijn (optioneel: skip bij ontbrekend package)

    Returns
    -------
    list[str]
        Lijst van waarschuwingsteksten. Lege lijst = alles in orde.
    """
    config = load_registry(path)
    warnings: list[str] = []

    for dataset, entries in config.services.items():
        for entry in entries:
            if entry.service_type == "WFS" and not entry.typename:
                warnings.append(
                    f"{dataset}/{entry.label}: WFS-entry heeft geen typename — "
                    f"vereist feature_type-kwarg bij fetch_features()"
                )
            if entry.module:
                module_path, _, func_name = entry.module.rpartition(".")
                try:
                    import importlib
                    mod = importlib.import_module(module_path)
                    if not hasattr(mod, func_name):
                        warnings.append(
                            f"{dataset}/{entry.label}: module {entry.module!r} "
                            f"bestaat maar functie {func_name!r} niet gevonden"
                        )
                except ImportError as exc:
                    warnings.append(
                        f"{dataset}/{entry.label}: module {entry.module!r} "
                        f"niet importeerbaar: {exc}"
                    )

    return warnings
