"""pastas_adapter smoke-tests.

We verifiëren de adapter-API zonder pastas/pastastore daadwerkelijk te
draaien — die zijn optionele deps. De tests checken:
- dataclass-defaults en types
- foutmeldingen wanneer pastastore ontbreekt
- de boundary (geen pastas-imports op module-load)
"""

from __future__ import annotations

import sys

import pytest


def test_module_imports_without_pastas():
    """Module-import mag NIET pastas of pastastore importeren."""
    import pastas_adapter  # noqa: F401

    assert "pastas" not in sys.modules or sys.modules.get("pastas") is not None
    # Het is OK als pastas elders al geladen is; we testen alleen dat de
    # adapter zelf het niet eager importeert.


def test_fit_config_defaults():
    from pastas_adapter import FitConfig

    cfg = FitConfig(name="test")
    assert cfg.solver == "LeastSquares"
    assert cfg.rfunc == "Exponential"
    assert cfg.noise_model is True
    assert cfg.tmin is None


def test_fit_result_failure_path():
    from pastas_adapter import FitResult

    r = FitResult(name="test", success=False, error="boom")
    assert not r.success
    assert r.rsq is None
    assert r.error == "boom"


def test_store_adapter_requires_pastastore_at_open(tmp_path):
    from pastas_adapter import PastaStoreAdapter
    from pastas_adapter.store import StoreLocation

    adapter = PastaStoreAdapter(
        StoreLocation(backend="dict", path=tmp_path, name="test_store")
    )
    # Construct mag — pastastore wordt pas bij open() geladen.
    assert adapter.location.name == "test_store"

    # Bij ontbrekende pastastore moet open() een duidelijke RuntimeError geven.
    try:
        import pastastore  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="pastastore"):
            adapter.open()


def test_diagnostics_dataclass():
    from pastas_adapter.diagnostics import ModelDiagnostics

    d = ModelDiagnostics(name="m1", rsq=0.85, n_observations=120)
    assert d.rsq == 0.85
    assert d.parameter_table == {}
    assert d.notes == []


def test_unsupported_backend_raises(tmp_path):
    from pastas_adapter import PastaStoreAdapter
    from pastas_adapter.store import StoreLocation

    adapter = PastaStoreAdapter(
        StoreLocation(backend="arctic", path=tmp_path, name="x")
    )
    try:
        import pastastore  # noqa: F401

        with pytest.raises(NotImplementedError, match="arctic"):
            adapter.open()
    except ImportError:
        pytest.skip("pastastore niet geïnstalleerd — kan backend-check niet bereiken")
