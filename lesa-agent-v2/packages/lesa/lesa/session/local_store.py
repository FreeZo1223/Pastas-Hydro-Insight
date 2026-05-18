"""LocalSessionStore — sessie-persistentie op lokale schijf.

Structuur per sessie:
    sessions/<session_id>/
        state.json              ← geserialiseerde SessionState
        data/<plugin_id>/       ← artifacts (gpkg/tif/parquet) per plugin
        provenance/             ← sidecar JSON per artifact
        qgis/                   ← QGIS-projectbestand
        report/                 ← gegenereerde rapporten
        styles/                 ← gebundelde .qml stijlen
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from lesa.session.state import SessionState


class SessionNotFoundError(KeyError):
    pass


class LocalSessionStore:
    """Sla sessies op als JSON + bestanden in een lokale map."""

    def __init__(self, base_dir: Path | str = Path("sessions")) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── Basismethoden ──────────────────────────────────────────────────────

    def save(self, state: SessionState) -> None:
        session_dir = self._session_dir(state.session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        state_path = session_dir / "state.json"
        state_path.write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> SessionState:
        state_path = self._session_dir(session_id) / "state.json"
        if not state_path.exists():
            raise SessionNotFoundError(
                f"Sessie '{session_id}' niet gevonden in {self.base_dir}"
            )
        return SessionState.model_validate_json(state_path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[dict]:
        sessions = []
        for session_dir in sorted(self.base_dir.iterdir()):
            state_path = session_dir / "state.json"
            if not state_path.exists():
                continue
            try:
                # Lees alleen de velden die nodig zijn voor de lijst
                data = json.loads(state_path.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data["session_id"],
                    "project_name": data.get("project_name", ""),
                    "scale_level": data.get("scale_level"),
                    "landscape_type": data.get("landscape_type"),
                    "updated_at": data.get("updated_at"),
                    "plugins_completed": sum(
                        1 for r in data.get("plugin_runs", [])
                        if r.get("status") == "completed"
                    ),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def delete(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            raise SessionNotFoundError(session_id)
        shutil.rmtree(session_dir)

    # ── Pad-helpers ────────────────────────────────────────────────────────

    def artifact_path(self, session_id: str, plugin_id: str, filename: str) -> Path:
        path = self._session_dir(session_id) / "data" / plugin_id / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def provenance_path(self, session_id: str, plugin_id: str) -> Path:
        path = self._session_dir(session_id) / "provenance"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def qgis_path(self, session_id: str) -> Path:
        path = self._session_dir(session_id) / "qgis"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def report_path(self, session_id: str) -> Path:
        path = self._session_dir(session_id) / "report"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def styles_path(self, session_id: str) -> Path:
        path = self._session_dir(session_id) / "styles"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id
