"""
Incrementeel AGOL → DuckDB met triple-validatie
=================================================

Strategy:
  1. Haal AGOL-records op met where=EditDate > laatst_gefetcht
  2. Merge in DuckDB via DELETE+INSERT op primary key
  3. Triple-validatie:
     a. AGOL totaal-count vs DuckDB totaal-count na merge
     b. Random sample-check (5 records — bestaat in beide?)
     c. PK-integriteit (geen duplicate global_id's)
  4. Bij ANY mismatch: state markeren als 'corrupt' zodat volgende run
     full-fetch doet — geen silent data loss.

Opt-in per laag via INCREMENTAL_CONFIG. Standaard leeg = alle lagen
gebruiken bestaande full-fetch pad.

Gebruik (vanuit agol_naar_duckdb_v2.py):
    from incrementeel import (
        is_incrementeel_actief, haal_laag_incrementeel,
        DeltaState, laad_delta_state, sla_delta_state,
    )
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


# ─────────────────────────────────────────────
# CONFIG — per-laag opt-in
# ─────────────────────────────────────────────

# Voeg lagen toe na succesvol testen. Veld 'field' = AGOL-veld dat
# wijzigingen markeert (meestal 'EditDate', Unix-ms). 'pk' = primary key
# kolomnaam in DuckDB-tabel (meestal 'global_id').
INCREMENTAL_CONFIG: dict[str, dict[str, str]] = {
    # Voorbeeld:
    # "Vogels_hist": {"field": "EditDate", "pk": "global_id"},
}

# Tolerantie voor count-mismatch (rij-verschil = max dit aantal of pct%)
TOLERANTIE_PCT = 0.0   # 0 = exacte match vereist
SAMPLE_GROOTTE = 5     # aantal random records voor sample-check


# ─────────────────────────────────────────────
# STATE PERSISTENCE
# ─────────────────────────────────────────────


@dataclass
class DeltaState:
    """Per-laag bijgehouden state voor incrementeel ophalen."""

    laagnaam: str
    last_edit_date_unix_ms: int | None = None
    last_full_fetch_iso: str | None = None
    last_incremental_iso: str | None = None
    last_method: str = "geen"   # 'full' | 'incremental' | 'no_changes' | 'fallback'
    validated_count: int | None = None
    laatste_validatie_iso: str | None = None
    aantal_consecutive_mismatches: int = 0
    notitie: str = ""


def laad_delta_state(pad: Path) -> dict[str, DeltaState]:
    """Lees alle delta-states uit JSON. Lege dict als bestand niet bestaat."""
    if not pad.exists():
        return {}
    try:
        raw = json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: dict[str, DeltaState] = {}
    for naam, data in raw.items():
        # Filter onbekende keys — robuust tegen schema-uitbreiding
        velden = {f.name for f in DeltaState.__dataclass_fields__.values()}
        data_clean = {k: v for k, v in data.items() if k in velden}
        out[naam] = DeltaState(laagnaam=naam, **{k: v for k, v in data_clean.items()
                                                   if k != "laagnaam"})
    return out


def sla_delta_state(pad: Path, state: dict[str, DeltaState]) -> None:
    """Schrijf alle delta-states atomisch naar JSON."""
    serialized = {naam: asdict(s) for naam, s in state.items()}
    tmp = pad.with_suffix(pad.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(serialized, indent=2, default=str), encoding="utf-8")
    tmp.replace(pad)


# ─────────────────────────────────────────────
# CONFIG-CHECKS
# ─────────────────────────────────────────────


def is_incrementeel_actief(laagnaam: str) -> bool:
    return laagnaam in INCREMENTAL_CONFIG


def config_voor(laagnaam: str) -> dict[str, str]:
    if not is_incrementeel_actief(laagnaam):
        raise KeyError(f"{laagnaam} heeft geen incrementeel-config")
    return INCREMENTAL_CONFIG[laagnaam]


# ─────────────────────────────────────────────
# VALIDATIE
# ─────────────────────────────────────────────


@dataclass
class ValidatieResultaat:
    geslaagd: bool
    count_lokaal: int
    count_agol: int
    pk_duplicaten: int
    sample_mismatches: int
    melding: str = ""


def valideer_post_merge(
    con: duckdb.DuckDBPyConnection,
    tabel: str,
    pk_col: str,
    agol_count: int,
    sample_pks_agol: set[Any] | None = None,
) -> ValidatieResultaat:
    """Triple-check na een merge: count + PK-integriteit + sample.

    sample_pks_agol: set van PK-waarden waarvan we WETEN dat ze in AGOL
    bestaan. We checken of ze ook in DuckDB staan. Mag None zijn — dan
    skip-pen we de sample-check.
    """
    count_lokaal = con.execute(f"SELECT COUNT(*) FROM {tabel}").fetchone()[0]

    pk_duplicaten = con.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT {pk_col} FROM {tabel} "
        f"  WHERE {pk_col} IS NOT NULL "
        f"  GROUP BY {pk_col} HAVING COUNT(*) > 1"
        f")"
    ).fetchone()[0]

    sample_mismatches = 0
    if sample_pks_agol:
        # Hoeveel van de AGOL-sample-PK's ontbreken in DuckDB?
        placeholders = ", ".join(["?"] * len(sample_pks_agol))
        gevonden = con.execute(
            f"SELECT COUNT(DISTINCT {pk_col}) FROM {tabel} "
            f"WHERE {pk_col} IN ({placeholders})",
            list(sample_pks_agol),
        ).fetchone()[0]
        sample_mismatches = len(sample_pks_agol) - gevonden

    # Tolerantie
    verschil = abs(count_lokaal - agol_count)
    tolerantie_abs = max(0, int(agol_count * TOLERANTIE_PCT / 100))
    count_ok = verschil <= tolerantie_abs

    geslaagd = count_ok and pk_duplicaten == 0 and sample_mismatches == 0

    meldingen = []
    if not count_ok:
        meldingen.append(f"count-mismatch: {count_lokaal} lokaal vs {agol_count} AGOL")
    if pk_duplicaten:
        meldingen.append(f"{pk_duplicaten} duplicate PK's")
    if sample_mismatches:
        meldingen.append(f"{sample_mismatches}/{len(sample_pks_agol or [])} sample-records ontbreken")

    return ValidatieResultaat(
        geslaagd=geslaagd,
        count_lokaal=count_lokaal,
        count_agol=agol_count,
        pk_duplicaten=pk_duplicaten,
        sample_mismatches=sample_mismatches,
        melding="; ".join(meldingen) or "OK",
    )


# ─────────────────────────────────────────────
# MERGE LOGICA (DuckDB-side)
# ─────────────────────────────────────────────


def merge_dataframe(
    con: duckdb.DuckDBPyConnection,
    tabel: str,
    nieuwe_df: pd.DataFrame,
    pk_col: str,
) -> tuple[int, int]:
    """DELETE+INSERT merge op pk_col. Bestaande tabel blijft staan.

    Returns: (n_vervangen, n_nieuw_toegevoegd)
    """
    if nieuwe_df.empty:
        return 0, 0

    if pk_col not in nieuwe_df.columns:
        raise ValueError(f"Primary key '{pk_col}' ontbreekt in nieuwe DataFrame")

    nieuwe_pks = nieuwe_df[pk_col].dropna().unique().tolist()
    if not nieuwe_pks:
        # Niets om te mergen — incoming heeft alleen NULL PK's (verdacht)
        return 0, 0

    # Tel hoeveel van de nieuwe PK's al bestaan
    placeholders = ", ".join(["?"] * len(nieuwe_pks))
    bestaand = con.execute(
        f"SELECT COUNT(*) FROM {tabel} WHERE {pk_col} IN ({placeholders})",
        nieuwe_pks,
    ).fetchone()[0]

    # DELETE bestaande rijen met deze PK's
    if bestaand > 0:
        con.execute(
            f"DELETE FROM {tabel} WHERE {pk_col} IN ({placeholders})",
            nieuwe_pks,
        )

    # INSERT nieuwe rijen via tijdelijke view (memory-safe)
    con.register("_incremental_buffer", nieuwe_df)
    try:
        con.execute(f"INSERT INTO {tabel} SELECT * FROM _incremental_buffer")
    finally:
        con.unregister("_incremental_buffer")

    n_vervangen = bestaand
    n_nieuw = len(nieuwe_df) - bestaand
    return n_vervangen, n_nieuw


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────


def nieuwste_edit_date_ms(df: pd.DataFrame, veld: str) -> int | None:
    """Bepaal max EditDate uit een DataFrame. Returnt Unix-ms of None."""
    if veld not in df.columns or df.empty:
        return None
    waarden = pd.to_numeric(df[veld], errors="coerce").dropna()
    if waarden.empty:
        return None
    return int(waarden.max())


def kies_sample_pks(pks: list[Any], k: int = SAMPLE_GROOTTE,
                     seed: int | None = None) -> set[Any]:
    """Kies k random PK's uit lijst voor sample-check. Deterministisch met seed."""
    if not pks:
        return set()
    rng = random.Random(seed)
    return set(rng.sample(pks, min(k, len(pks))))


def nu_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
