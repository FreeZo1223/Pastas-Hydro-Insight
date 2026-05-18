"""Session smoke-tests: SessionState, LocalSessionStore."""

from __future__ import annotations

import pytest

from lesa.domain.claim import Claim
from lesa.domain.hypothesis import Hypothesis
from lesa.session.local_store import LocalSessionStore, SessionNotFoundError
from lesa.session.state import PluginRun, SessionState


# ── SessionState ──────────────────────────────────────────────────────────

class TestSessionState:
    def test_summary_keys(self, minimal_session: SessionState):
        s = minimal_session.summary()
        assert "session_id" in s
        assert "project" in s
        assert s["plugins_completed"] == 0

    def test_add_claim_updates_timestamp(self, minimal_session: SessionState):
        before = minimal_session.updated_at
        claim = Claim(
            id="c-001",
            plugin_id="test",
            topic="reliëf",
            text="Het gebied heeft een lage ligging.",
            based_on=["AHN4"],
            uncertainty="laag",
            substantiation="AHN toont maaiveld <0.5m NAP",
        )
        minimal_session.add_claim(claim)
        assert len(minimal_session.claims) == 1
        assert minimal_session.updated_at >= before

    def test_session_scope_empty(self, minimal_session: SessionState):
        scope = minimal_session.session_scope()
        assert scope.scope == "session"
        assert scope.uncertainty_level == "hoog"

    def test_model_roundtrip(self, minimal_session: SessionState):
        json_str = minimal_session.model_dump_json()
        restored = SessionState.model_validate_json(json_str)
        assert restored.session_id == minimal_session.session_id
        assert restored.project_name == minimal_session.project_name
        assert restored.aoi.geometry == minimal_session.aoi.geometry


# ── LocalSessionStore ─────────────────────────────────────────────────────

class TestLocalSessionStore:
    def test_save_and_load(self, tmp_path, minimal_session: SessionState):
        store = LocalSessionStore(base_dir=tmp_path)
        store.save(minimal_session)
        loaded = store.load(minimal_session.session_id)
        assert loaded.session_id == minimal_session.session_id
        assert loaded.project_name == minimal_session.project_name

    def test_load_missing_raises(self, tmp_path):
        store = LocalSessionStore(base_dir=tmp_path)
        with pytest.raises(SessionNotFoundError):
            store.load("niet-bestaande-sessie")

    def test_list_sessions(self, tmp_path, minimal_session: SessionState):
        store = LocalSessionStore(base_dir=tmp_path)
        store.save(minimal_session)
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == minimal_session.session_id
        assert sessions[0]["project_name"] == minimal_session.project_name

    def test_delete(self, tmp_path, minimal_session: SessionState):
        store = LocalSessionStore(base_dir=tmp_path)
        store.save(minimal_session)
        store.delete(minimal_session.session_id)
        with pytest.raises(SessionNotFoundError):
            store.load(minimal_session.session_id)

    def test_delete_missing_raises(self, tmp_path):
        store = LocalSessionStore(base_dir=tmp_path)
        with pytest.raises(SessionNotFoundError):
            store.delete("bestaat-niet")

    def test_artifact_path_creates_dir(self, tmp_path, minimal_session: SessionState):
        store = LocalSessionStore(base_dir=tmp_path)
        path = store.artifact_path(minimal_session.session_id, "bodem_ahn", "bodem.gpkg")
        assert path.parent.exists()
        assert path.name == "bodem.gpkg"

    def test_state_json_contains_plugin_runs_count(self, tmp_path, minimal_session: SessionState):
        from datetime import datetime, timezone

        run = PluginRun(
            plugin_id="bodem_ahn",
            plugin_version="0.1.0",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        minimal_session.plugin_runs.append(run)
        store = LocalSessionStore(base_dir=tmp_path)
        store.save(minimal_session)

        sessions = store.list_sessions()
        assert sessions[0]["plugins_completed"] == 1
