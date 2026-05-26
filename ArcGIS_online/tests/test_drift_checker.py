"""Tests voor check_registry_vs_code — vooral de normalisatie-edge cases."""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_normaliseer_basis_accenten():
    from check_registry_vs_code import _normaliseer_servicenaam

    assert _normaliseer_servicenaam("Amfibieën") == "amfibieen"
    assert _normaliseer_servicenaam("AMFIBIEËN_2024") == "amfibieen_2024"


@pytest.mark.unit
def test_normaliseer_url_encoded_input():
    """Registry slaat soms URL-encoded service-namen op (bug elders, maar
    de checker moet er tegen kunnen)."""
    from check_registry_vs_code import _normaliseer_servicenaam

    a = _normaliseer_servicenaam("Amfibi%C3%ABn_2024")    # URL-encoded ë
    b = _normaliseer_servicenaam("Amfibiën_2024")          # letterlijk ë
    assert a == b == "amfibien_2024"


@pytest.mark.unit
def test_normaliseer_onderscheidt_echt_verschillende_namen():
    """Amfibieën (9 chars) en Amfibiën (8 chars) zijn EXPRES verschillend —
    dat is een echte typo-bug die de checker moet kunnen onderscheiden."""
    from check_registry_vs_code import _normaliseer_servicenaam

    correct = _normaliseer_servicenaam("Amfibieën_2024")
    typo = _normaliseer_servicenaam("Amfibi%C3%ABn_2024")

    assert correct != typo, "Drift-checker moet echte typos zien — niet alles glad strijken"
    assert correct == "amfibieen_2024"
    assert typo == "amfibien_2024"


@pytest.mark.unit
def test_vergelijk_geen_drift_bij_identieke_input():
    from check_registry_vs_code import vergelijk

    lagen = {"x": {"service_naam": "Foo_2024", "rest_url": "http://x/Foo_2024/FS/1", "index": 1}}
    drift = vergelijk(lagen, lagen)

    assert not drift.heeft_drift


@pytest.mark.unit
def test_vergelijk_signaleert_alleen_in_code():
    from check_registry_vs_code import vergelijk

    code = {
        "A": {"service_naam": "A_svc", "rest_url": "http://x/A_svc/FS/1", "index": 1},
        "B": {"service_naam": "B_svc", "rest_url": "http://x/B_svc/FS/2", "index": 2},
    }
    reg = {
        "a.actueel": {"service_naam": "A_svc", "rest_url": "http://x/A_svc/FS/1", "index": 1},
    }
    drift = vergelijk(code, reg)

    assert drift.alleen_in_code == ["B"]
    assert drift.alleen_in_registry == []


@pytest.mark.unit
def test_vergelijk_signaleert_url_verschil():
    from check_registry_vs_code import vergelijk

    code = {"X": {"service_naam": "Foo", "rest_url": "http://A", "index": 1}}
    reg = {"x.actueel": {"service_naam": "Foo", "rest_url": "http://B", "index": 1}}
    drift = vergelijk(code, reg)

    assert drift.url_verschillen == [("X", "http://A", "http://B")]
