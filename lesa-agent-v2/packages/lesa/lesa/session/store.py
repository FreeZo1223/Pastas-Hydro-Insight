"""SessionStore Protocol — abstracte interface voor sessie-persistentie.

Twee implementaties:
- LocalSessionStore  : JSON + GPKG/TIF/Parquet op lokale schijf (default)
- PostgisSessionStore: opt-in voor team/multi-user (later)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from lesa.session.state import SessionState


@runtime_checkable
class SessionStore(Protocol):
    """Protocol voor sessie-opslag. Beide implementaties voldoen hieraan."""

    def save(self, state: SessionState) -> None:
        """Sla de volledige SessionState op."""
        ...

    def load(self, session_id: str) -> SessionState:
        """Laad een SessionState op basis van session_id."""
        ...

    def list_sessions(self) -> list[dict]:
        """Geef een lijst van beschikbare sessies (id, project_name, updated_at)."""
        ...

    def delete(self, session_id: str) -> None:
        """Verwijder een sessie en alle bijbehorende artifacts."""
        ...

    def artifact_path(self, session_id: str, plugin_id: str, filename: str) -> Path:
        """Geef het pad terug waar een plugin-artifact opgeslagen wordt."""
        ...
