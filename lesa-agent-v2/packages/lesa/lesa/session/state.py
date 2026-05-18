"""SessionState — centrale toestand van een LESA-sessie.

Bevat alles: AOI, systeemgrens, plugin-runs, claims, hypothesen en
scope-statements. Wordt geserialiseerd naar state.json door de SessionStore.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from lesa.domain.aoi import AOI, SystemBoundary
from lesa.domain.claim import Claim
from lesa.domain.hypothesis import Hypothesis
from lesa.domain.rangorde import RangordePosition
from lesa.domain.scope import ScopeStatement, aggregate_scope

OutputStrategyId = Literal[
    "veldwerkprotocol",
    "bureau_lesa",
    "qgis_project",
    "markdown_report",
    "word_report",
    "hypothesis_export",
]

LandscapeType = Literal["duinen", "beekdal", "veen", "zandlandschap", "klei"]


def _new_id() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CostInfo(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_eur: float = 0.0

    def add(self, input_tokens: int, output_tokens: int) -> "CostInfo":
        # Ruwe schatting: Sonnet ~€0.003/1k input, €0.015/1k output
        added_eur = (input_tokens / 1000 * 0.003) + (output_tokens / 1000 * 0.015)
        return CostInfo(
            input_tokens=self.input_tokens + input_tokens,
            output_tokens=self.output_tokens + output_tokens,
            estimated_eur=round(self.estimated_eur + added_eur, 4),
        )


class PluginRun(BaseModel):
    """Registratie van één plugin-uitvoering."""

    plugin_id: str
    plugin_version: str
    status: Literal["queued", "running", "completed", "failed", "skipped"]
    inputs_snapshot: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="output-naam → pad (als string voor JSON-serialisatie)",
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    provenance_path: str | None = None

    @property
    def duration_s(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def rangorde_position(self) -> RangordePosition | None:
        """Wordt runtime ingevuld vanuit registry — niet opgeslagen in state."""
        return None


class SkippedPlugin(BaseModel):
    plugin_id: str
    rangorde_position: RangordePosition
    reason: str
    skipped_at: datetime = Field(default_factory=_utcnow)


class AgentTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


class SessionState(BaseModel):
    """Volledige toestand van een LESA-sessie."""

    # Identiteit
    session_id: str = Field(default_factory=_new_id)
    project_name: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # Geografie
    aoi: AOI
    system_boundary: SystemBoundary | None = None
    aoi_source: str = Field(default="user_geojson")

    # Methodologie
    scale_level: Literal[1, 2, 3]
    landscape_type: LandscapeType | None = None
    chosen_outputs: list[OutputStrategyId] = Field(default_factory=list)

    # Planning + uitvoering
    plugin_runs: list[PluginRun] = Field(default_factory=list)
    skipped_plugins: list[SkippedPlugin] = Field(default_factory=list)

    # Inhoudelijke output
    claims: list[Claim] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    scope_statements: list[ScopeStatement] = Field(default_factory=list)

    # Operationeel
    agent_history: list[AgentTurn] = Field(default_factory=list)
    cost: CostInfo = Field(default_factory=CostInfo)
    data_sources_hash: str | None = Field(
        default=None,
        description="SHA256 van data_sources.yaml bij sessie-start (reproduceerbaarheid)",
    )

    # ── Hulpmethoden ──────────────────────────────────────────────────────────

    def completed_positions(self) -> set[RangordePosition]:
        """Rangorde-posities die succesvol zijn afgerond."""
        from lesa.plugins._registry import get_registry
        registry = get_registry()
        completed = set()
        for run in self.plugin_runs:
            if run.status == "completed":
                meta = registry.get_meta(run.plugin_id)
                if meta:
                    completed.add(meta.rangorde_position)
        return completed

    def skipped_positions(self) -> set[RangordePosition]:
        return {sp.rangorde_position for sp in self.skipped_plugins}

    def add_claim(self, claim: Claim) -> None:
        self.claims.append(claim)
        self.updated_at = _utcnow()

    def add_hypothesis(self, hypothesis: Hypothesis) -> None:
        self.hypotheses.append(hypothesis)
        self.updated_at = _utcnow()

    def add_scope(self, scope: ScopeStatement) -> None:
        self.scope_statements.append(scope)
        self.updated_at = _utcnow()

    def session_scope(self) -> ScopeStatement:
        """Aggregeer alle plugin-scope-statements tot sessie-niveau."""
        plugin_scopes = [s for s in self.scope_statements if s.scope == "plugin"]
        if not plugin_scopes:
            return ScopeStatement(
                scope="session",
                subject_id=self.session_id,
                based_on=[],
                not_tested=["nog geen plugins gedraaid"],
                uncertainty_level="hoog",
                consequences="Sessie is nog leeg — geen uitkomsten beschikbaar.",
            )
        return aggregate_scope(plugin_scopes, self.session_id)

    def summary(self) -> dict[str, Any]:
        """Beknopt overzicht voor CLI-weergave."""
        return {
            "session_id": self.session_id[:8],
            "project": self.project_name,
            "scale_level": self.scale_level,
            "landscape_type": self.landscape_type,
            "plugins_completed": sum(1 for r in self.plugin_runs if r.status == "completed"),
            "plugins_failed": sum(1 for r in self.plugin_runs if r.status == "failed"),
            "claims": len(self.claims),
            "hypotheses": len(self.hypotheses),
            "cost_eur": self.cost.estimated_eur,
        }
