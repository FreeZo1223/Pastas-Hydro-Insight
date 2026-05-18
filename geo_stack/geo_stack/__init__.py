"""geo_stack — domein-neutrale geo data-fetch laag voor Nederland.

Subpakketten:
    core/    — geo_utils, cache, normalizer, discovery
    skills/  — datasource-specifieke fetchers (bgt, ahn, kadaster, gee, ...)

Top-level:
    fetch.fetch_features  — smart dispatcher (cloud-native first)
"""

from geo_stack import fetch

__version__ = "0.2.1"

__all__ = ["__version__", "fetch"]
