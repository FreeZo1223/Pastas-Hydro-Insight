"""Rangordemodel (Bakker 1979) — top-down volgorde voor LESA-modules.

Geologie → geomorfologie → bodem → hydrologie → vegetatie → fauna → mens.

Plugins declareren hun positie via ``rangorde_position`` in plugin.yaml.
De orchestrator en CLI dwingen de volgorde af via ``can_run()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    pass

RangordePosition = Literal[1, 2, 3, 4, 5, 6, 7]

RANGORDE: dict[RangordePosition, str] = {
    1: "geologie",
    2: "geomorfologie",
    3: "bodem",
    4: "hydrologie",
    5: "vegetatie",
    6: "fauna",
    7: "mens",
}


class RangordeViolation(Exception):
    """Raised als een plugin-run de top-down volgorde zou schenden."""


def can_run(
    plugin_position: RangordePosition,
    completed_positions: set[RangordePosition],
    skipped_positions: set[RangordePosition],
) -> tuple[bool, str]:
    """Controleer of een plugin-run toegestaan is.

    Parameters
    ----------
    plugin_position
        Rangorde-positie van de te draaien plugin (1–7).
    completed_positions
        Posities die al succesvol zijn afgerond.
    skipped_positions
        Posities die expliciet zijn overgeslagen met motivatie.

    Returns
    -------
    tuple[bool, str]
        (True, "") als de run mag; (False, uitleg) als niet.
    """
    done_or_skipped = completed_positions | skipped_positions
    higher_order = {pos for pos in RANGORDE if pos < plugin_position}
    missing = higher_order - done_or_skipped

    if not missing:
        return True, ""

    missing_names = [RANGORDE[pos] for pos in sorted(missing)]
    return False, (
        f"Hogere-orde modules nog niet gedraaid of overgeslagen: "
        f"{', '.join(missing_names)}. "
        f"Voer ze eerst uit, of sla ze expliciet over met een motivatie via "
        f"skip_plugin(plugin_id, reason='...')."
    )


def rangorde_label(position: RangordePosition) -> str:
    """Geef de naam van een rangordeniveau terug."""
    return RANGORDE.get(position, f"onbekend ({position})")
