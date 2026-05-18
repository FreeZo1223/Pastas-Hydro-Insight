"""Hypothesis — een toetsbare veronderstelling over het ecosysteem.

Een Hypothesis is een first-class object: niet vrije tekst in een rapport,
maar een gestructureerde entiteit met falsifier, zwakste schakel en status.
De expert toetst in het veld of in aanvullende bureaustudie.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


HypothesisStatus = Literal[
    "voorgesteld",
    "actief",
    "getoetst_bevestigd",
    "getoetst_verworpen",
    "bijgesteld",
]

ConfidenceLevel = Literal["sterk_onderbouwd", "plausibel", "speculatief"]


class FieldProtocolStub(BaseModel):
    """Koppeling naar een veldmeetlocatie voor toetsing van deze hypothese."""

    location_description: str
    indicators_to_observe: list[str] = Field(
        description="Wat moet de expert in het veld waarnemen/meten"
    )
    predicted_values: dict[str, str] = Field(
        default_factory=dict,
        description="Voorspelde waarneming per indicator als hypothese klopt, "
                    "bv. {'grondwaterstand': '< -80 cm MV', 'vegetatie': 'Pijpenstrootje dominant'}",
    )


class Hypothesis(BaseModel):
    """Toetsbare veronderstelling met falsifier en zwakste schakel."""

    id: str
    plugin_id: str = Field(description="Plugin die deze hypothese heeft voorgesteld")
    proposed_mechanism: str = Field(
        description="Welk proces wordt verondersteld (oorzaak-gevolg)"
    )
    predicted_observation: str = Field(
        description="Wat zou in het veld / in aanvullende data zichtbaar moeten zijn "
                    "als de hypothese klopt"
    )
    falsifier: str | None = Field(
        default=None,
        description="Wat zou de hypothese ontkrachten. "
                    "Verplicht tenzij confidence_level='speculatief'.",
    )
    reason_no_falsifier: str | None = Field(
        default=None,
        description="Verplicht als falsifier=None: waarom is een falsifier niet formuleerbaar",
    )
    confidence_level: ConfidenceLevel
    weakest_link: str = Field(
        description="Zwakste schakel in de onderbouwende bewijsketen"
    )
    supporting_claims: list[str] = Field(
        default_factory=list,
        description="Lijst van Claim-IDs die deze hypothese ondersteunen",
    )
    status: HypothesisStatus = Field(default="voorgesteld")
    field_protocol: FieldProtocolStub | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @model_validator(mode="after")
    def _validate_falsifier(self) -> "Hypothesis":
        if self.falsifier is None and self.confidence_level != "speculatief":
            raise ValueError(
                "falsifier is verplicht tenzij confidence_level='speculatief'. "
                "Vul falsifier in, of zet confidence_level op 'speculatief' en "
                "geef reason_no_falsifier op."
            )
        if self.falsifier is None and self.confidence_level == "speculatief":
            if not self.reason_no_falsifier:
                raise ValueError(
                    "Als falsifier=None en confidence_level='speculatief', "
                    "dan is reason_no_falsifier verplicht."
                )
        return self

    def mark_status(self, new_status: HypothesisStatus, notes: str = "") -> "Hypothesis":
        """Retourneert een bijgewerkte kopie (immutable update)."""
        return self.model_copy(
            update={"status": new_status, "updated_at": datetime.now(timezone.utc)}
        )

    def __str__(self) -> str:
        return f"[{self.confidence_level}/{self.status}] {self.proposed_mechanism}"
