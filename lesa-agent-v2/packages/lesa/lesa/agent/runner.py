"""Plugin runner — server-side execution helper for the agent.

Encapsulates the plugin lifecycle:
1. Rangorde-check via ``can_run()``.
2. Pydantic validation of params against the plugin's PARAMS_CLASS.
3. PluginInputs construction with prior-claim/hypothesis context.
4. Async ``fetch_data()`` then sync ``analyze()``.
5. Persistence: append PluginRun, claims, hypotheses, scope to session;
   save artifacts to ``store.artifact_path()``.
6. Failure handling: PluginRun marked ``failed`` with error message,
   session saved to disk so progress is never lost on a crash.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from lesa.domain.rangorde import can_run
from lesa.plugins._base import PluginInputs, PluginOutputs
from lesa.plugins._registry import PluginRegistry
from lesa.session.local_store import LocalSessionStore
from lesa.session.state import PluginRun, SessionState

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PluginRunResult:
    """Resultaat van één run — succes of falen, beide gepersisteerd."""

    __slots__ = ("plugin_id", "ok", "outputs", "error", "skipped_reason")

    def __init__(
        self,
        plugin_id: str,
        ok: bool,
        outputs: PluginOutputs | None = None,
        error: str | None = None,
        skipped_reason: str | None = None,
    ) -> None:
        self.plugin_id = plugin_id
        self.ok = ok
        self.outputs = outputs
        self.error = error
        self.skipped_reason = skipped_reason

    def as_summary(self) -> dict[str, Any]:
        """JSON-vriendelijke samenvatting voor terugkoppeling aan Claude."""
        if self.skipped_reason:
            return {
                "plugin_id": self.plugin_id,
                "status": "blocked",
                "reason": self.skipped_reason,
            }
        if not self.ok:
            return {
                "plugin_id": self.plugin_id,
                "status": "failed",
                "error": self.error,
            }
        outputs = self.outputs
        assert outputs is not None
        return {
            "plugin_id": self.plugin_id,
            "status": "completed",
            "claims": [
                {"id": c.id, "topic": c.topic, "text": c.text, "uncertainty": c.uncertainty}
                for c in outputs.claims
            ],
            "hypotheses": [
                {
                    "id": h.id,
                    "mechanism": h.proposed_mechanism,
                    "confidence": h.confidence_level,
                    "falsifier": h.falsifier,
                }
                for h in outputs.hypotheses
            ],
            "scope": {
                "uncertainty_level": outputs.scope.uncertainty_level,
                "based_on": outputs.scope.based_on,
                "not_tested": outputs.scope.not_tested,
            },
            "artifacts": list(outputs.artifacts.keys()),
            "duration_s": outputs.duration_s,
            "summary": outputs.summary,
        }


class PluginRunner:
    """Voert één plugin uit binnen een sessie en muteert de SessionState."""

    def __init__(
        self,
        registry: PluginRegistry,
        store: LocalSessionStore,
    ) -> None:
        self.registry = registry
        self.store = store

    async def run(
        self,
        session: SessionState,
        plugin_id: str,
        params: dict[str, Any],
    ) -> PluginRunResult:
        """Voer ``plugin_id`` uit met ``params``. Persisteert state altijd."""
        meta = self.registry.get_meta(plugin_id)
        if meta is None:
            return PluginRunResult(plugin_id, ok=False, error=f"Plugin '{plugin_id}' niet gevonden in registry")

        # Rangorde-check
        ok, msg = can_run(
            meta.rangorde_position,
            session.completed_positions(),
            session.skipped_positions(),
        )
        if not ok:
            return PluginRunResult(plugin_id, ok=False, skipped_reason=msg)

        # Landschapstype-check
        if (
            session.landscape_type is not None
            and "all" not in meta.landscape_types
            and session.landscape_type not in meta.landscape_types
        ):
            return PluginRunResult(
                plugin_id,
                ok=False,
                skipped_reason=(
                    f"Plugin '{plugin_id}' niet beschikbaar voor landschapstype "
                    f"'{session.landscape_type}'. Ondersteund: {meta.landscape_types}"
                ),
            )

        # Pydantic-validatie van params
        instance = self.registry.get_instance(plugin_id)
        params_cls = getattr(instance, "PARAMS_CLASS", None)
        if params_cls is not None:
            try:
                validated = params_cls.model_validate(params)
                params = validated.model_dump()
            except ValidationError as exc:
                return PluginRunResult(
                    plugin_id,
                    ok=False,
                    error=f"Ongeldige params voor '{plugin_id}': {exc}",
                )

        # PluginRun aanmaken vóór uitvoering — verlies geen state bij crash
        run = PluginRun(
            plugin_id=plugin_id,
            plugin_version=meta.version,
            status="running",
            inputs_snapshot=params,
            started_at=_utcnow(),
        )
        session.plugin_runs.append(run)
        self.store.save(session)

        # PluginInputs samenstellen
        artifact_dir = self.store.artifact_path(session.session_id, plugin_id, "_").parent
        inputs = PluginInputs(
            session_id=session.session_id,
            project_name=session.project_name,
            scale_level=session.scale_level,
            landscape_type=session.landscape_type,
            aoi_geojson=session.aoi.geometry,
            system_boundary_geojson=(
                session.system_boundary.geometry if session.system_boundary else None
            ),
            prior_claims=list(session.claims),
            prior_hypotheses=list(session.hypotheses),
            params=params,
            artifact_dir=str(artifact_dir),
        )

        # Uitvoering
        try:
            instance.validate_inputs(inputs)
            raw = await instance.fetch_data(inputs)
            outputs = instance.analyze(inputs, raw)
        except Exception as exc:  # noqa: BLE001 — we want to capture every failure
            logger.exception("Plugin '%s' faalde tijdens uitvoering", plugin_id)
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
            run.completed_at = _utcnow()
            session.updated_at = _utcnow()
            self.store.save(session)
            return PluginRunResult(plugin_id, ok=False, error=run.error)

        # Outputs naar sessie
        run.status = "completed"
        run.completed_at = _utcnow()
        run.artifacts = dict(outputs.artifacts)
        outputs.duration_s = (run.completed_at - run.started_at).total_seconds()

        for claim in outputs.claims:
            session.claims.append(claim)
        for hyp in outputs.hypotheses:
            session.hypotheses.append(hyp)
        session.scope_statements.append(outputs.scope)
        session.updated_at = _utcnow()
        self.store.save(session)

        return PluginRunResult(plugin_id, ok=True, outputs=outputs)
