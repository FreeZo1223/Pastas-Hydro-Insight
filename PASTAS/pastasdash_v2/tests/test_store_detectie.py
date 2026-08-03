"""Tests voor formaat-detectie bij het laden van een store.

Een native PasConnector-store is een *map* met een ``.pastastore``-descriptor,
geen ZIP. Dat is het formaat dat ``pastastore`` zelf op schijf schrijft, dus
zowel het descriptor-bestand als de map eromheen moet herkend worden.
"""

from __future__ import annotations

import json

import pytest

from pastasdash_v2.core.store import _find_pas_descriptor


def _maak_pas_store(basis, naam: str = "B42C0133"):
    """Bouw de mapstructuur die PasConnector op schijf achterlaat."""
    store_dir = basis / naam
    store_dir.mkdir(parents=True)
    for lib in ("oseries", "stresses", "models", "oseries_models"):
        (store_dir / lib).mkdir()
    descriptor = store_dir / f"{naam}.pastastore"
    descriptor.write_text(
        json.dumps({"connector_type": "pas", "name": naam, "path": str(basis)}),
        encoding="utf-8",
    )
    return store_dir, descriptor


@pytest.mark.unit
class TestPasDescriptorDetectie:
    def test_vindt_descriptor_via_bestand(self, tmp_path):
        _, descriptor = _maak_pas_store(tmp_path)
        assert _find_pas_descriptor(descriptor) == descriptor

    def test_vindt_descriptor_via_map(self, tmp_path):
        store_dir, descriptor = _maak_pas_store(tmp_path)
        assert _find_pas_descriptor(store_dir) == descriptor

    def test_vindt_descriptor_ook_bij_afwijkende_mapnaam(self, tmp_path):
        """Na hernoemen van de map heet de descriptor nog steeds anders."""
        store_dir, descriptor = _maak_pas_store(tmp_path, naam="Meetnet")
        hernoemd = store_dir.parent / "andere_naam"
        store_dir.rename(hernoemd)
        gevonden = _find_pas_descriptor(hernoemd)
        assert gevonden is not None
        assert gevonden.name == "Meetnet.pastastore"

    def test_gewone_map_is_geen_pas_store(self, tmp_path):
        (tmp_path / "zomaar").mkdir()
        assert _find_pas_descriptor(tmp_path / "zomaar") is None

    def test_zip_is_geen_pas_store(self, tmp_path):
        zipje = tmp_path / "store.zip"
        zipje.write_bytes(b"PK\x03\x04dummy")
        assert _find_pas_descriptor(zipje) is None

    def test_niet_bestaand_pad(self, tmp_path):
        assert _find_pas_descriptor(tmp_path / "bestaat_niet") is None
