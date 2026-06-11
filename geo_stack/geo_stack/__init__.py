"""geo_stack — domein-neutrale geo data-fetch laag voor Nederland.

Subpakketten:
    core/    — geo_utils, cache, normalizer, discovery, registry
    skills/  — datasource-specifieke fetchers (bgt, ahn, kadaster, gee, ...)
    drivers/ — generieke protocol-drivers (WFS, OGC_API, CLOUD_NATIVE)

Top-level:
    fetch.fetch_features  — smart dispatcher (cloud-native first)
    bundle.fetch_bundle   — parallel fetch van meerdere datasets
"""

from geo_stack import fetch
from geo_stack.bundle import fetch_bundle, async_fetch_bundle

__version__ = "0.3.0"

__all__ = ["__version__", "fetch", "fetch_bundle", "async_fetch_bundle"]
