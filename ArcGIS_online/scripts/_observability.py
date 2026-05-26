"""
Observability helpers — Sentry-init + structured logging hooks
================================================================

Optioneel: alleen actief als SENTRY_DSN in environment staat. Zonder DSN
is alles een no-op zodat scripts standalone blijven werken.

Gebruik (boven in elk pipeline-script):

    from _observability import init_observability
    init_observability(component="agol_ingest")

Bij een onverwachte exception in dat script wordt automatisch een event
naar Sentry gestuurd met tag `component=agol_ingest`.

Setup eenmalig:
    pip install sentry-sdk
    # In C:\\GIS_Projecten\\.env:
    SENTRY_DSN=https://xxx@sentry.io/yyy
    SENTRY_ENVIRONMENT=production    # of 'dev'
    SENTRY_TRACES_SAMPLE_RATE=0.1    # 10% van runs profileren
"""

from __future__ import annotations

import os
from typing import Literal


_GEACTIVEERD = False  # voorkomt dubbele init bij meerdere imports


def init_observability(
    component: str,
    environment: Literal["production", "dev", "test"] | None = None,
) -> bool:
    """Initialiseer Sentry indien DSN beschikbaar. Returnt True als actief.

    component: korte tag, bv. 'agol_ingest', 'gpkg_export', 'postgis_export'.
    Zichtbaar in Sentry-UI als filter.

    Veilig om altijd aan te roepen — doet niets als sentry-sdk ontbreekt
    of geen DSN gezet is. Geen verstoring van pipeline-runtime.
    """
    global _GEACTIVEERD
    if _GEACTIVEERD:
        return True

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        # sentry-sdk niet geïnstalleerd — silent skip, geen log-spam
        return False

    env = environment or os.getenv("SENTRY_ENVIRONMENT", "production")
    try:
        traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0"))
    except ValueError:
        traces_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        # Lage default — verhoog handmatig voor debugging
        traces_sample_rate=traces_rate,
        # Stuur géén local variables bij — kunnen credentials bevatten
        send_default_pii=False,
        include_local_variables=False,
        attach_stacktrace=True,
    )
    sentry_sdk.set_tag("component", component)
    sentry_sdk.set_tag("pipeline", "ewaarnemingen")

    _GEACTIVEERD = True
    return True


def capture_event(boodschap: str, severity: Literal["info", "warning", "error"] = "info",
                  **extra) -> None:
    """Stuur een expliciet event naar Sentry (alleen als geactiveerd)."""
    if not _GEACTIVEERD:
        return
    try:
        import sentry_sdk
        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_message(boodschap, level=severity)
    except Exception:
        # Observability mag NOOIT de pipeline laten falen
        pass
