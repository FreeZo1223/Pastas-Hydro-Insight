"""Tests voor grandfather-father-son retentie in snapshot.py."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from snapshot import Snapshot, bepaal_te_behouden


def _maak(snapshots: list[date]) -> list[Snapshot]:
    """Helper: maak Snapshot-objecten zonder echt pad nodig te hebben."""
    from pathlib import Path
    return [Snapshot(pad=Path(f"/tmp/{d.isoformat()}"), datum=d) for d in snapshots]


@pytest.mark.unit
def test_alle_snapshots_binnen_14_dagen_blijven_behouden():
    vandaag = date(2026, 5, 18)
    dagen = [vandaag - timedelta(days=i) for i in range(14)]
    snapshots = _maak(dagen)

    behouden = bepaal_te_behouden(snapshots, vandaag)

    assert len(behouden) == 14
    assert {s.pad for s in snapshots} == behouden


@pytest.mark.unit
def test_oudere_doordeweekse_snapshots_worden_verwijderd():
    vandaag = date(2026, 5, 18)  # maandag
    # Drie weken geleden op een dinsdag (weekday=1, geen zondag)
    oud = date(2026, 4, 28)
    assert oud.weekday() == 1  # dinsdag — geen zondag

    snapshots = _maak([oud])
    behouden = bepaal_te_behouden(snapshots, vandaag)

    assert behouden == set(), "Doordeweekse snapshot > 14 dagen oud moet weg"


@pytest.mark.unit
def test_zondag_snapshots_blijven_8_weken_behouden():
    vandaag = date(2026, 5, 18)  # maandag
    # 4 zondagen geleden — binnen 8 weken, dus behouden
    zondag_4w = date(2026, 4, 19)
    assert zondag_4w.weekday() == 6

    snapshots = _maak([zondag_4w])
    behouden = bepaal_te_behouden(snapshots, vandaag)

    assert len(behouden) == 1


@pytest.mark.unit
def test_eerste_van_maand_blijft_lang_behouden():
    vandaag = date(2026, 5, 18)
    # 6 maanden geleden, 1e van de maand
    eerste = date(2025, 11, 1)

    snapshots = _maak([eerste])
    behouden = bepaal_te_behouden(snapshots, vandaag)

    assert len(behouden) == 1, "1e-van-de-maand snapshot binnen 12m moet behouden blijven"


@pytest.mark.unit
def test_lege_input_geeft_lege_output():
    behouden = bepaal_te_behouden([], date.today())
    assert behouden == set()
