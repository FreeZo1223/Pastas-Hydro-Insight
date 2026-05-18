"""ScopeStatement — expliciete reikwijdte-verantwoording per plugin en sessie.

Elke plugin-run produceert een ScopeStatement. De sessie aggregeert ze
tot een overkoepelende sessie-scope. Dit volgt het LESA.INFO-voorschrift:
bureaustudie zonder veldwerk moet de consequenties verantwoorden.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScopeStatement(BaseModel):
    """Reikwijdte-verantwoording voor een plugin-run of gehele sessie."""

    scope: Literal["plugin", "session"]
    subject_id: str = Field(
        description="plugin_id bij scope='plugin', anders 'session'"
    )
    based_on: list[str] = Field(
        description="Databronnen die zijn gebruikt, incl. versielabel, "
                    "bv. ['AHN4 v2026 (5m)', 'BRO Bodemkaart 1:50000 2024']"
    )
    not_tested: list[str] = Field(
        description="Wat NIET is gedaan of getoetst, "
                    "bv. ['veldverificatie bodemtype', 'stationariteitstoets tijdreeks']"
    )
    uncertainty_level: Literal["laag", "middel", "hoog"]
    consequences: str = Field(
        description="Wat betekent deze scope-beperking voor de bruikbaarheid van de uitkomsten"
    )
    created_at: datetime = Field(default_factory=_utcnow)

    def as_markdown(self) -> str:
        """Formatteer als Markdown-sectie voor rapporten."""
        lines = [
            f"**Reikwijdte ({self.subject_id})**",
            "",
            f"*Onzekerheid: {self.uncertainty_level}*",
            "",
            "**Gebaseerd op:**",
        ]
        for src in self.based_on:
            lines.append(f"- {src}")
        lines += ["", "**Niet getoetst:**"]
        for item in self.not_tested:
            lines.append(f"- {item}")
        lines += ["", f"**Consequentie:** {self.consequences}"]
        return "\n".join(lines)


def aggregate_scope(statements: list[ScopeStatement], session_id: str) -> ScopeStatement:
    """Aggregeer plugin-scope-statements tot één sessie-overkoepelend statement."""
    all_based_on = []
    all_not_tested = []
    seen_based: set[str] = set()
    seen_not_tested: set[str] = set()

    for s in statements:
        for src in s.based_on:
            if src not in seen_based:
                all_based_on.append(src)
                seen_based.add(src)
        for item in s.not_tested:
            if item not in seen_not_tested:
                all_not_tested.append(item)
                seen_not_tested.add(item)

    # Hoogste onzekerheidsniveau wint
    order = {"laag": 0, "middel": 1, "hoog": 2}
    worst = max(statements, key=lambda s: order[s.uncertainty_level], default=None)
    uncertainty = worst.uncertainty_level if worst else "hoog"

    return ScopeStatement(
        scope="session",
        subject_id=session_id,
        based_on=all_based_on,
        not_tested=all_not_tested,
        uncertainty_level=uncertainty,
        consequences=(
            "Sessie is een bureaustudie op basis van openbare databronnen. "
            "Veldverificatie is vereist voor definitieve conclusies."
        ),
    )
