"""Domain model smoke-tests: AOI, Hypothesis, Rangorde, ScopeStatement."""

from __future__ import annotations

import pytest

from lesa.domain.aoi import AOI, SystemBoundary
from lesa.domain.hypothesis import Hypothesis
from lesa.domain.rangorde import RangordeViolation, can_run
from lesa.domain.scope import ScopeStatement, aggregate_scope


# ── AOI ───────────────────────────────────────────────────────────────────

class TestAOI:
    _poly = {
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [0.0, 0.0]]],
    }

    def test_valid_polygon(self):
        aoi = AOI(geometry=self._poly, source="test")
        assert aoi.crs == "EPSG:28992"

    def test_invalid_geometry_type(self):
        with pytest.raises(ValueError, match="Polygon of MultiPolygon"):
            AOI(geometry={"type": "Point", "coordinates": [0.0, 0.0]}, source="test")

    def test_bbox(self):
        aoi = AOI(geometry=self._poly, source="test")
        assert aoi.bbox == (0.0, 0.0, 100.0, 100.0)

    def test_from_wkt(self):
        wkt = "POLYGON ((0 0, 100 0, 100 100, 0 100, 0 0))"
        aoi = AOI.from_wkt(wkt)
        assert aoi.geometry["type"] == "Polygon"
        assert aoi.source == "wkt"

    def test_multipolygon_accepted(self):
        mp = {
            "type": "MultiPolygon",
            "coordinates": [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]],
        }
        aoi = AOI(geometry=mp, source="test")
        assert aoi.geometry["type"] == "MultiPolygon"


# ── Hypothesis ────────────────────────────────────────────────────────────

class TestHypothesis:
    def _base(self, **overrides) -> dict:
        data = {
            "id": "test-hyp-001",
            "plugin_id": "bodem_ahn",
            "proposed_mechanism": "Kweldruk verhoogt grondwaterstand",
            "predicted_observation": "Dotterbloem en moeraskartelblad in laagte",
            "falsifier": "Peilbuismeting toont geen grondwaterstand >60cm mv",
            "weakest_link": "Kwaliteit AHN-data in dit gebied",
            "confidence_level": "plausibel",
            "supporting_claims": [],
        }
        data.update(overrides)
        return data

    def test_valid_hypothesis(self):
        h = Hypothesis(**self._base())
        assert h.status == "voorgesteld"
        assert h.falsifier is not None

    def test_speculatief_without_falsifier_requires_reason(self):
        with pytest.raises(ValueError, match="reason_no_falsifier"):
            Hypothesis(**self._base(
                confidence_level="speculatief",
                falsifier=None,
                reason_no_falsifier=None,
            ))

    def test_speculatief_with_reason_allowed(self):
        h = Hypothesis(**self._base(
            confidence_level="speculatief",
            falsifier=None,
            weakest_link="onbekend",
            reason_no_falsifier="Onvoldoende data beschikbaar in oriëntatiefase",
        ))
        assert h.confidence_level == "speculatief"
        assert h.falsifier is None

    def test_non_speculatief_requires_falsifier(self):
        with pytest.raises(ValueError, match="falsifier is verplicht"):
            Hypothesis(**self._base(falsifier=None, confidence_level="sterk_onderbouwd"))

    def test_missing_weakest_link_raises(self):
        with pytest.raises(ValueError):
            Hypothesis(**self._base(weakest_link=None))


# ── Rangorde ──────────────────────────────────────────────────────────────

class TestRangorde:
    def test_first_plugin_always_allowed(self):
        ok, msg = can_run(1, completed_positions=set(), skipped_positions=set())
        assert ok
        assert msg == ""

    def test_blocked_if_higher_order_missing(self):
        ok, msg = can_run(3, completed_positions={1}, skipped_positions=set())
        assert not ok
        assert "geomorfologie" in msg

    def test_allowed_if_all_higher_completed(self):
        ok, _ = can_run(3, completed_positions={1, 2}, skipped_positions=set())
        assert ok

    def test_skipped_counts_as_done(self):
        ok, _ = can_run(3, completed_positions={1}, skipped_positions={2})
        assert ok

    def test_mix_completed_and_skipped(self):
        ok, _ = can_run(5, completed_positions={1, 2, 3}, skipped_positions={4})
        assert ok

    def test_partial_mix_still_blocked(self):
        ok, msg = can_run(4, completed_positions={1}, skipped_positions={2})
        assert not ok
        assert "bodem" in msg


# ── ScopeStatement ────────────────────────────────────────────────────────

class TestScopeStatement:
    def _make(self, uncertainty: str, subject: str = "plugin_x") -> ScopeStatement:
        return ScopeStatement(
            scope="plugin",
            subject_id=subject,
            based_on=["AHN4"],
            not_tested=["grondwater"],
            uncertainty_level=uncertainty,
            consequences="Beperkte uitspraken mogelijk.",
        )

    def test_as_markdown(self):
        s = self._make("middel")
        md = s.as_markdown()
        assert "Reikwijdte" in md
        assert "AHN4" in md

    def test_aggregate_highest_uncertainty_wins(self):
        scopes = [
            self._make("laag", "p1"),
            self._make("hoog", "p2"),
            self._make("middel", "p3"),
        ]
        agg = aggregate_scope(scopes, session_id="sess-1")
        assert agg.uncertainty_level == "hoog"
        assert agg.scope == "session"
        assert len(agg.based_on) >= 1

    def test_aggregate_empty_returns_high_uncertainty(self):
        agg = aggregate_scope([], session_id="sess-empty")
        assert agg.uncertainty_level == "hoog"
