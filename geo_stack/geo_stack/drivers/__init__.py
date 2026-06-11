"""geo_stack driver-registry.

Elke driver implementeert ``BaseDriver.fetch(bbox, **kw) → GeoDataFrame``.
De ``DRIVERS``-dict koppelt service_type-strings (uit data_sources.yaml)
aan de bijbehorende driver-klasse.
"""

from geo_stack.drivers.base import BaseDriver
from geo_stack.drivers.cloud_native_driver import CloudNativeDriver
from geo_stack.drivers.ogc_api import OGCAPIDriver
from geo_stack.drivers.wfs import WFSDriver

DRIVERS: dict[str, type[BaseDriver]] = {
    "WFS": WFSDriver,
    "OGC_API": OGCAPIDriver,
    "CLOUD_NATIVE": CloudNativeDriver,
}

__all__ = ["BaseDriver", "CloudNativeDriver", "OGCAPIDriver", "WFSDriver", "DRIVERS"]
