"""Provenance — schrijf een sidecar-JSON naast elke geo-output.

Legt vast: endpoint, parameters, feature_count, source_version,
timestamp (UTC), SHA256-hash van outputbestand.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_provenance(
    output_path: Path | str,
    *,
    source: str,
    params: dict[str, Any],
    feature_count: int | None = None,
    source_version: str | None = None,
    source_crs: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Schrijf een sidecar-JSON met herkomst-metadata naast ``output_path``."""
    output_path = Path(output_path)
    sidecar = output_path.with_suffix("").with_suffix(".provenance.json")

    record: dict[str, Any] = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "source_version": source_version,
        "source_crs": source_crs,
        "params": _serialize(params),
        "output_file": output_path.name,
        "feature_count": feature_count,
    }

    if output_path.exists():
        record["output_sha256"] = _sha256(output_path)
        record["output_size_bytes"] = output_path.stat().st_size

    if extra:
        record["extra"] = _serialize(extra)

    sidecar.write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return sidecar


def load_provenance(output_path: Path | str) -> dict[str, Any] | None:
    output_path = Path(output_path)
    sidecar = output_path.with_suffix("").with_suffix(".provenance.json")
    if not sidecar.exists():
        return None
    return json.loads(sidecar.read_text(encoding="utf-8"))


def _sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _serialize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)
