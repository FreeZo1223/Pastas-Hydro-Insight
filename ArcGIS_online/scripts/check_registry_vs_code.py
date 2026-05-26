"""
Registry vs hardcoded code: drift-detectie
============================================

layer_registry.json is bedoeld als source of truth, maar wordt nu nog niet
gelezen door de pipeline (zie ROADMAP). Hardcoded AGOL_LAGEN in
agol_naar_duckdb_v2.py is de feitelijke bron.

Dit script vergelijkt beide en rapporteert verschillen — voorkomt dat
registry en code stiekem uit elkaar drijven.

Gebruik:
    python check_registry_vs_code.py             # rapport, exit 1 bij drift
    python check_registry_vs_code.py --json      # machine-leesbare output
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent
REGISTRY_PAD = _PROJECT_DIR / "Databeheer" / "00_kern" / "layer_registry.json"

# Maak scripts/ importeerbaar om AGOL_LAGEN op te halen.
sys.path.insert(0, str(_SCRIPT_DIR))


@dataclass
class Drift:
    alleen_in_code: list[str] = field(default_factory=list)
    alleen_in_registry: list[str] = field(default_factory=list)
    url_verschillen: list[tuple[str, str, str]] = field(default_factory=list)
    index_verschillen: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def heeft_drift(self) -> bool:
        return bool(
            self.alleen_in_code
            or self.alleen_in_registry
            or self.url_verschillen
            or self.index_verschillen
        )


def extract_registry_urls(registry: dict) -> dict[str, dict]:
    """Plat dict: {service_naam: {"url": ..., "index": ..., "variant": ...}}."""
    out = {}
    for laag_key, laag_data in registry.get("lagen", {}).items():
        for variant in ("actueel", "historie"):
            v = laag_data.get(variant)
            if not v:
                continue
            service = v.get("service_naam")
            if not service:
                continue
            out[f"{laag_key}.{variant}"] = {
                "service_naam": service,
                "rest_url": v.get("rest_url", ""),
                "index": v.get("feature_server_index"),
            }
    return out


def extract_code_urls() -> dict[str, dict]:
    """Plat dict: {laagnaam_in_code: {"rest_url": ..., "service_naam": ..., "index": ...}}."""
    # Import met side-effects toegestaan — de module heeft een safe read-only guard.
    from agol_naar_duckdb_v2 import AGOL_LAGEN

    out = {}
    for naam, url in AGOL_LAGEN.items():
        # URL-vorm: .../services/SERVICE/FeatureServer/INDEX
        parts = url.rstrip("/").split("/")
        index = None
        service = "?"
        if len(parts) >= 2 and parts[-1].isdigit():
            index = int(parts[-1])
        if len(parts) >= 4:
            # Pak het stuk vóór FeatureServer
            try:
                fs_idx = parts.index("FeatureServer")
                service = parts[fs_idx - 1]
            except ValueError:
                pass
        out[naam] = {"service_naam": service, "rest_url": url, "index": index}
    return out


def _normaliseer_servicenaam(naam: str) -> str:
    """Case- en accent-insensitief vergelijken.

    Strategie:
      1. URL-decode  (registry heeft soms 'Amfibi%C3%ABn_2024' ipv 'Amfibieën_2024')
      2. NFKD normaliseer  (ë als single codepoint of e+combining diaeresis)
      3. Strip combining marks
      4. lowercase
    """
    url_gedecodeerd = urllib.parse.unquote(naam)
    decomposed = unicodedata.normalize("NFKD", url_gedecodeerd)
    zonder_accent = "".join(c for c in decomposed if not unicodedata.combining(c))
    return zonder_accent.lower()


def vergelijk(code_lagen: dict, registry_lagen: dict) -> Drift:
    """Match op service_naam + index, niet op exacte naam — die verschilt."""
    drift = Drift()

    # Index op (genormaliseerde service_naam, index) — meest robuust
    def sleutel(d):
        return (_normaliseer_servicenaam(d["service_naam"]), d["index"])

    code_index = {sleutel(d): naam for naam, d in code_lagen.items()}
    reg_index = {sleutel(d): naam for naam, d in registry_lagen.items()}

    code_keys = set(code_index)
    reg_keys = set(reg_index)

    drift.alleen_in_code = sorted(code_index[k] for k in (code_keys - reg_keys))
    drift.alleen_in_registry = sorted(reg_index[k] for k in (reg_keys - code_keys))

    # Voor gedeelde keys: check of de URL exact gelijk is
    gedeeld = code_keys & reg_keys
    for k in sorted(gedeeld):
        code_url = code_lagen[code_index[k]]["rest_url"]
        reg_url = registry_lagen[reg_index[k]]["rest_url"]
        if code_url != reg_url:
            drift.url_verschillen.append((code_index[k], code_url, reg_url))

    return drift


def print_rapport(drift: Drift) -> None:
    print("=" * 60)
    print("  REGISTRY vs CODE — DRIFT-DETECTIE")
    print("=" * 60)

    if not drift.heeft_drift:
        print("\n✅ Geen drift gevonden — registry en code zijn consistent.")
        return

    if drift.alleen_in_code:
        print(f"\n⚠️  In code maar NIET in registry ({len(drift.alleen_in_code)}):")
        for naam in drift.alleen_in_code:
            print(f"   - {naam}")

    if drift.alleen_in_registry:
        print(f"\n⚠️  In registry maar NIET in code ({len(drift.alleen_in_registry)}):")
        for naam in drift.alleen_in_registry:
            print(f"   - {naam}")

    if drift.url_verschillen:
        print(f"\n❌ URL-verschil voor lagen die in beide staan ({len(drift.url_verschillen)}):")
        for naam, c, r in drift.url_verschillen:
            print(f"   {naam}")
            print(f"     code     : {c}")
            print(f"     registry : {r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="Output als JSON ipv mens-leesbaar rapport")
    args = parser.parse_args()

    if not REGISTRY_PAD.exists():
        print(f"❌ Registry niet gevonden: {REGISTRY_PAD}")
        return 2

    with open(REGISTRY_PAD, encoding="utf-8") as f:
        registry = json.load(f)

    reg_lagen = extract_registry_urls(registry)
    code_lagen = extract_code_urls()

    drift = vergelijk(code_lagen, reg_lagen)

    if args.json:
        print(json.dumps({
            "alleen_in_code":      drift.alleen_in_code,
            "alleen_in_registry":  drift.alleen_in_registry,
            "url_verschillen":     [
                {"naam": n, "code_url": c, "registry_url": r}
                for n, c, r in drift.url_verschillen
            ],
        }, indent=2))
    else:
        print_rapport(drift)

    return 1 if drift.heeft_drift else 0


if __name__ == "__main__":
    sys.exit(main())
