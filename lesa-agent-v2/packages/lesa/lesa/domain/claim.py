"""Claim — een feitelijke uitspraak met bron en onzekerheidsniveau.

Een Claim is deterministisch afgeleid uit data door een plugin.
De expert verifieert, betwist of accepteert claims.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Claim(BaseModel):
    """Feitelijke uitspraak afgeleid uit ruimtelijke data."""

    id: str = Field(description="Uniek ID (ULID of UUID)")
    plugin_id: str = Field(description="Plugin die deze claim heeft gegenereerd")
    topic: str = Field(description="Korte aanduiding: 'reliëf' | 'bodem' | 'hydrologie' | ...")
    text: str = Field(description="Volledige uitspraak in leesbare zin")

    based_on: list[str] = Field(
        description="Databronnen waarop de uitspraak gebaseerd is, "
                    "bv. ['AHN4 v2026', 'BRO Bodemkaart 1:50000']"
    )
    uncertainty: Literal["laag", "middel", "hoog"] = Field(
        description="Onzekerheidsniveau van de uitspraak"
    )
    substantiation: str = Field(
        description="Korte onderbouwing: wat in de data leidt tot deze uitspraak"
    )

    created_at: datetime = Field(default_factory=_utcnow)

    def __str__(self) -> str:
        return f"[{self.uncertainty.upper()}] {self.text}"
