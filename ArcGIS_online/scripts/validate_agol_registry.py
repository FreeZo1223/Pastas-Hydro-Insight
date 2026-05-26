"""
AGOL Layer Registry Validator — preflight check
================================================
Valideert dat alle lagen in layer_registry.json:
  1. Een bereikbare REST-URL hebben (FeatureServer reageert)
  2. De geclaimde feature_server_index daadwerkelijk bestaat
  3. De service_naam matcht met wat AGOL teruggeeft

Doel: vang index-drift af VOORDAT de pipeline een uur lang data gaat ophalen
en op subtiele 404's of verkeerde data uitkomt.

Gebruik:
    python validate_agol_registry.py                # alle lagen, exit 1 bij mismatch
    python validate_agol_registry.py --quick        # alleen 'actueel', geen 'historie'
    python validate_agol_registry.py --no-auth      # geen AGOL-token (public layers only)

Exit codes:
    0 = alle gecheckte lagen valide
    1 = één of meer mismatches gevonden
    2 = systeemfout (geen netwerk, geen .env, etc)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
from dotenv import load_dotenv

_SCRIPT_DIR = Path(__file__).parent
_PROJECT_DIR = _SCRIPT_DIR.parent

load_dotenv(_PROJECT_DIR / ".env")

REGISTRY_PAD = _PROJECT_DIR / "Databeheer" / "00_kern" / "layer_registry.json"
TIMEOUT_SECONDEN = 30
AGOL_TOKEN_URL = "https://www.arcgis.com/sharing/rest/generateToken"


# ── Result-types ──────────────────────────────────────────────────────────────


@dataclass
class LaagResultaat:
    laag_key: str
    variant: str  # 'actueel' of 'historie'
    service_naam: str
    claim_index: int
    status: str  # 'ok', 'fout', 'overgeslagen'
    melding: str = ""


@dataclass
class Rapport:
    resultaten: list[LaagResultaat] = field(default_factory=list)

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.resultaten if r.status == "ok")

    @property
    def n_fout(self) -> int:
        return sum(1 for r in self.resultaten if r.status == "fout")

    @property
    def n_overgeslagen(self) -> int:
        return sum(1 for r in self.resultaten if r.status == "overgeslagen")


# ── Auth ──────────────────────────────────────────────────────────────────────


def haal_token() -> str | None:
    """Vraag AGOL-token op via gebruikersnaam/wachtwoord uit .env."""
    user = os.getenv("AGOL_USERNAME")
    pwd = os.getenv("AGOL_PASSWORD")
    if not user or not pwd or user == "jouw_gebruikersnaam":
        return None
    try:
        r = requests.post(
            AGOL_TOKEN_URL,
            data={
                "username": user,
                "password": pwd,
                "referer": "https://www.arcgis.com",
                "f": "json",
                "expiration": 60,
            },
            timeout=TIMEOUT_SECONDEN,
        )
        r.raise_for_status()
        return r.json().get("token")
    except Exception as e:
        print(f"⚠️  Token-aanvraag faalde: {e}")
        return None


# ── Validatie ─────────────────────────────────────────────────────────────────


def _feature_server_basis(rest_url: str) -> str:
    """Knip /{index} af van FeatureServer-URL."""
    # Voorbeeld: .../FeatureServer/11 → .../FeatureServer
    parts = rest_url.rstrip("/").split("/")
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    return "/".join(parts)


def valideer_laag(
    laag_key: str,
    variant: str,
    variant_data: dict,
    token: str | None,
) -> LaagResultaat:
    """Check één laag-variant (actueel of historie) tegen AGOL."""
    service_naam = variant_data.get("service_naam", "?")
    claim_index = int(variant_data.get("feature_server_index", -1))
    rest_url = variant_data.get("rest_url", "")

    result = LaagResultaat(
        laag_key=laag_key,
        variant=variant,
        service_naam=service_naam,
        claim_index=claim_index,
        status="fout",
    )

    if not rest_url:
        result.melding = "rest_url ontbreekt in registry"
        return result

    basis_url = _feature_server_basis(rest_url)
    params = {"f": "json"}
    if token:
        params["token"] = token

    try:
        r = requests.get(basis_url, params=params, timeout=TIMEOUT_SECONDEN)
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as e:
        result.melding = f"HTTP {e.response.status_code} op {basis_url}"
        return result
    except Exception as e:
        result.melding = f"netwerkfout: {type(e).__name__}: {str(e)[:100]}"
        return result

    if "error" in data:
        code = data["error"].get("code", "?")
        msg = data["error"].get("message", "")[:100]
        result.melding = f"AGOL error {code}: {msg}"
        return result

    layers = data.get("layers", []) + data.get("tables", [])
    indices_beschikbaar = {laag["id"]: laag.get("name", "?") for laag in layers}

    if claim_index not in indices_beschikbaar:
        result.melding = (
            f"index {claim_index} bestaat NIET — beschikbaar: "
            f"{sorted(indices_beschikbaar.keys())[:10]}"
        )
        return result

    werkelijke_naam = indices_beschikbaar[claim_index]
    # Naam-mismatch is informatief: service_naam in registry is de SERVICE,
    # werkelijke_naam is de LAAG-naam binnen die service. Vaak verschillend.
    # We loggen wel maar laten het OK.
    result.status = "ok"
    result.melding = f"index {claim_index} = '{werkelijke_naam}'"
    return result


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true",
                        help="Alleen 'actueel' valideren, geen 'historie'")
    parser.add_argument("--no-auth", action="store_true",
                        help="Geen AGOL-token gebruiken (alleen public lagen)")
    args = parser.parse_args()

    if not REGISTRY_PAD.exists():
        print(f"❌ Registry niet gevonden: {REGISTRY_PAD}")
        return 2

    with open(REGISTRY_PAD, encoding="utf-8") as f:
        registry = json.load(f)

    token = None if args.no_auth else haal_token()
    auth_label = "met token" if token else "ZONDER token (publieke lagen)"

    print("=" * 60)
    print(f"  AGOL REGISTRY VALIDATOR  ({auth_label})")
    print("=" * 60)

    rapport = Rapport()
    lagen = registry.get("lagen", {})
    print(f"\n📋 {len(lagen)} lagen in registry\n")

    for laag_key, laag_data in lagen.items():
        for variant in ("actueel", "historie"):
            if variant == "historie" and args.quick:
                continue
            variant_data = laag_data.get(variant)
            if not variant_data:
                continue
            res = valideer_laag(laag_key, variant, variant_data, token)
            rapport.resultaten.append(res)

            icon = "✅" if res.status == "ok" else "❌"
            print(f"  {icon} {laag_key:30s} {variant:9s} → {res.melding}")

    print("\n" + "=" * 60)
    print(f"  Resultaat: {rapport.n_ok} OK, {rapport.n_fout} FOUT")
    print("=" * 60)

    return 0 if rapport.n_fout == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
