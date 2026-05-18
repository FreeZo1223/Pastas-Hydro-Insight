"""FetchReport — mensleesbare samenvatting na elke geo-fetch."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import geopandas as gpd

_WIDTH = 51
_BAR = "═" * _WIDTH


class FetchReport:
    """Context-manager die na elke fetch een vast blok print."""

    def __init__(
        self,
        label: str,
        *,
        bbox: tuple | None = None,
        source: str | None = None,
        cache_hit: bool | None = None,
        extra: dict[str, Any] | None = None,
        silent: bool = False,
    ) -> None:
        self.label = label
        self.bbox = bbox
        self.source = source
        self.cache_hit = cache_hit
        self.extra = extra or {}
        self.silent = silent
        self._start = time.perf_counter()
        self._lines: list[tuple[str, Any]] = []

    def __enter__(self) -> "FetchReport":
        return self

    def __exit__(self, *_: Any) -> None:
        self.print()

    def finish(self, result: gpd.GeoDataFrame | Path | None = None) -> None:
        if isinstance(result, gpd.GeoDataFrame):
            self._lines.append(("Features", len(result)))
            if not result.empty and result.crs:
                self._lines.append(("CRS", result.crs.to_string()))
                self._lines.append(("BBOX (RD)", tuple(result.total_bounds.round(0).tolist())))
        elif isinstance(result, Path):
            size_mb = result.stat().st_size / 1024 / 1024 if result.exists() else 0
            self._lines.append(("Output", f"{result.name} ({size_mb:.1f} MB)"))

    def add(self, key: str, value: Any) -> None:
        self._lines.append((key, value))

    def print(self) -> None:
        if self.silent:
            return
        elapsed = time.perf_counter() - self._start
        lines: list[tuple[str, Any]] = list(self._lines)
        if self.bbox is not None:
            lines.insert(0, ("Aangevraagde BBOX", self.bbox))
        if self.source:
            lines.append(("Bron", _truncate(self.source, 38)))
        if self.cache_hit is not None:
            lines.append(("Cache", "HIT" if self.cache_hit else "MISS → opgeslagen"))
        for k, v in self.extra.items():
            lines.append((k, v))
        lines.append(("Duur", f"{elapsed:.1f} s"))

        print(f"\n  {_BAR}")
        print(f"    FETCH  {self.label}")
        print(f"  {_BAR}")
        for key, val in lines:
            print(f"    {key:<18} {val}")
        print(f"  {_BAR}\n")


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-(n - 1):]
