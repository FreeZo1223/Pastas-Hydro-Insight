"""besi_fetcher — BeSI Beschermde Soorten Indicator analyse voor een geometrie.

Refactored van BeSI Analyse Tool (C:/GIS_Projecten/BeSI/).
Databron: BeSI Kansenkaarten 2025 (Sierdsema et al. 2026, Sovon-rapport 2025/78).

Gebruik:
    from geo_stack.skills.besi_fetcher import fetch_besi_for_geometry, BesiResult

    result = fetch_besi_for_geometry(
        geom=my_polygon,          # shapely BaseGeometry in EPSG:28992
        species_group="Vogels",   # optioneel filter
        vrt_path=Path("BESI_Master.vrt"),
    )
    print(result.species_table[result.species_table["present"]].head())

Configuratie:
    vrt_path       → parameter, of env BESI_VRT_PATH
    metadata_path  → parameter, of env BESI_METADATA_PATH,
                     of <besi_fetcher.py>/../../../BeSI/config/species_metadata.csv
"""

from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask as rasterio_mask
from rasterio.transform import Affine
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constanten (identiek aan BeSI/config/settings.py)
# ---------------------------------------------------------------------------

_DATA_SCALE_FACTOR: float = 255.0
_DEFAULT_CUTOFF: float = 0.3
_N_KLASSEN: int = 5
_CEL_OPPERVLAKTE_HA: float = 0.0625   # 25×25 m = 625 m² = 0.0625 ha
_CHUNK_THRESHOLD_HA: float = 1_000.0

_STATUS_WEIGHTS: dict[str, int] = {
    "EX": 0, "RE": 0,
    "CR": 5, "EN": 4, "VU": 3, "NT": 2,
    "LC": 1, "DD": 1, "NE": 1,
    "HR_I": 2, "HR_II": 2, "HR_IV": 3, "HR_II_IV": 4, "HR_V": 1,
}

# Pad naar de meegeleverde metadata CSV in de BeSI-repo (fallback als er geen
# env-var of parameter is opgegeven).
_BESI_REPO_METADATA = (
    Path(__file__).parent.parent.parent.parent  # …/geo_stack/
    / "BeSI" / "config" / "species_metadata.csv"
)


# ---------------------------------------------------------------------------
# Publieke types
# ---------------------------------------------------------------------------


class BesiFetchError(RuntimeError):
    """Fout bij ophalen of verwerken van BeSI-kansenkaarten."""


@dataclass(frozen=True)
class BesiResult:
    """Resultaat van een BeSI-analyse voor één geometrie.

    Velden
    ------
    species_table
        DataFrame met één rij per soort. Kolommen:
        dutch_name, scientific_name, species_group, broad_group,
        rl_category, habitat_directive, weight, cutoff_value,
        present, area_ha, mean_score, max_score.
        ``cutoff_value`` geeft aan hoe conservatief de aanwezigheidsdrempel
        is — gebruik dit als onzekerheidsmarker in de UI.
    richness_array
        (rows, cols) int16 — aantal verwachte soorten per 25×25 m cel.
    priority_array
        (rows, cols) uint8 — 5-klassen prioriteringskaart (0=buiten gebied,
        1=laag … 5=hoog).
    weighted_richness_array
        (rows, cols) float32 — gewogen ecologische waarde per cel
        (som van beschermingsgewichten). Gebruikt als BeSI-component in
        EcoScore.
    transform
        rasterio.transform.Affine voor georeferentie van de rasters.
    crs
        CRS-string van de uitvoer (altijd "EPSG:28992").
    nodata_mask
        (rows, cols) bool — True = pixel valt binnen het studiegebied.
    area_ha
        Totale oppervlakte studiegebied in ha.
    n_species_present
        Aantal soorten boven cutoff in ten minste één cel.
    data_confidence
        Altijd ``"model_based_probability"``. Gebruik dit veld als
        expliciete onzekerheidsindicator: de kansenkaarten zijn modellen,
        geen bevestigde waarnemingen.
    """

    species_table: pd.DataFrame
    richness_array: np.ndarray
    priority_array: np.ndarray
    weighted_richness_array: np.ndarray
    transform: Affine
    crs: str
    nodata_mask: np.ndarray
    area_ha: float
    n_species_present: int
    data_confidence: str = field(default="model_based_probability")


# ---------------------------------------------------------------------------
# Publieke functie
# ---------------------------------------------------------------------------


def fetch_besi_for_geometry(
    geom: BaseGeometry,
    species_group: str | None = None,
    vrt_path: Path | str | None = None,
    metadata_path: Path | str | None = None,
) -> BesiResult:
    """Voer een volledige BeSI-analyse uit voor een shapely-geometrie.

    Parameters
    ----------
    geom
        Polygoon of MultiPolygoon in EPSG:28992.
    species_group
        Optioneel filter op soortengroep (bijv. ``"Vogels"``, ``"Zoogdieren"``).
        ``None`` = alle 235 soorten.
    vrt_path
        Pad naar ``BESI_Master.vrt``. Valt terug op env ``BESI_VRT_PATH``.
    metadata_path
        Pad naar ``species_metadata.csv``. Valt terug op env
        ``BESI_METADATA_PATH`` of de meegeleverde CSV in de BeSI-repo.

    Returns
    -------
    BesiResult
        Versie 1 + versie 2 resultaten in één object.

    Raises
    ------
    BesiFetchError
        VRT niet gevonden, geometrie ongeldig of berekening mislukt.
    """
    vrt_path, metadata_path = _resolve_paths(vrt_path, metadata_path)

    metadata = _load_metadata(metadata_path)
    band_mapping = _build_band_mapping(vrt_path, metadata)

    band_indices: list[int] | None = None
    if species_group is not None:
        selected = band_mapping[band_mapping["species_group"] == species_group]
        if selected.empty:
            known = sorted(band_mapping["species_group"].unique())
            raise BesiFetchError(
                f"Soortengroep {species_group!r} niet gevonden. "
                f"Beschikbare groepen: {known}"
            )
        band_mapping = selected.reset_index(drop=True)
        band_indices = selected["vrt_band"].tolist()

    data, transform, crs, nodata_mask = _mask_vrt(vrt_path, geom, band_indices)
    area_ha = float(nodata_mask.sum() * _CEL_OPPERVLAKTE_HA)

    binary = _apply_cutoffs(data, band_mapping)
    richness = _species_richness(binary)
    priority = _classify(richness)
    weighted = _weighted_richness(binary, band_mapping)
    table = _build_species_table(binary, data, band_mapping, nodata_mask)

    n_present = int(table["present"].sum())
    log.info(
        "BeSI klaar: %d/%d soorten aanwezig, max %d soorten/cel, %.1f ha",
        n_present, len(band_mapping), int(richness.max()), area_ha,
    )

    return BesiResult(
        species_table=table,
        richness_array=richness,
        priority_array=priority,
        weighted_richness_array=weighted,
        transform=transform,
        crs=crs,
        nodata_mask=nodata_mask,
        area_ha=area_ha,
        n_species_present=n_present,
    )


# ---------------------------------------------------------------------------
# Privé helpers — config
# ---------------------------------------------------------------------------


def _resolve_paths(
    vrt_path: Path | str | None,
    metadata_path: Path | str | None,
) -> tuple[Path, Path]:
    """Bepaal paden via parameter → env-var → bekende fallback."""
    if vrt_path is None:
        env = os.environ.get("BESI_VRT_PATH")
        if not env:
            raise BesiFetchError(
                "VRT-pad niet opgegeven. Geef vrt_path mee of stel "
                "BESI_VRT_PATH in als omgevingsvariabele."
            )
        vrt_path = Path(env)
    vrt_path = Path(vrt_path)
    if not vrt_path.exists():
        raise BesiFetchError(f"VRT-bestand niet gevonden: {vrt_path}")

    if metadata_path is None:
        env_meta = os.environ.get("BESI_METADATA_PATH")
        if env_meta:
            metadata_path = Path(env_meta)
        elif _BESI_REPO_METADATA.exists():
            metadata_path = _BESI_REPO_METADATA
        else:
            raise BesiFetchError(
                "Metadata-pad niet opgegeven en BeSI-repo niet gevonden op "
                f"{_BESI_REPO_METADATA}. Geef metadata_path mee of stel "
                "BESI_METADATA_PATH in als omgevingsvariabele."
            )
    metadata_path = Path(metadata_path)
    if not metadata_path.exists():
        raise BesiFetchError(f"Metadata-bestand niet gevonden: {metadata_path}")

    return vrt_path, metadata_path


# ---------------------------------------------------------------------------
# Privé helpers — data laden (geport van BeSI/core/loader.py)
# ---------------------------------------------------------------------------


def _load_metadata(metadata_path: Path) -> pd.DataFrame:
    df = pd.read_csv(metadata_path, encoding="utf-8")
    required = {"dutch_name", "cutoff_value", "weight", "species_group"}
    missing = required - set(df.columns)
    if missing:
        raise BesiFetchError(f"Metadata mist kolommen: {missing}")
    log.debug("Metadata geladen: %d soorten uit %s", len(df), metadata_path.name)
    return df


def _build_band_mapping(vrt_path: Path, metadata: pd.DataFrame) -> pd.DataFrame:
    """Koppel VRT-banden aan metadatarijen via soortnaam in COG-bestandsnaam."""
    tree = ET.parse(vrt_path)
    root = tree.getroot()

    meta_lookup: dict[str, pd.Series] = {
        str(row["dutch_name"]).strip(): row
        for _, row in metadata.iterrows()
    }

    rows: list[pd.Series] = []
    band_num = 0
    for band_el in root.findall("VRTRasterBand"):
        band_num += 1
        source_el = band_el.find(".//SourceFilename")
        raw_name: str | None = None

        if source_el is not None and source_el.text:
            filename = Path(source_el.text).name
            stem = filename.replace("_cog.tif", "")
            raw_name = re.sub(r"\s*\([^)]*\)\s*$", "", stem).strip()

        if raw_name and raw_name in meta_lookup:
            row = meta_lookup[raw_name].copy()
            row["vrt_band"] = band_num
            rows.append(row)
        else:
            log.debug(
                "Band %d (%r) niet in metadata — standaardwaarden toegepast",
                band_num, raw_name,
            )
            rows.append(pd.Series({
                "dutch_name":         raw_name or f"Band_{band_num}",
                "scientific_name":    "",
                "species_group":      "Onbekend",
                "broad_group":        "Onbekend",
                "rl_category":        "NE",
                "habitat_directive":  "",
                "cutoff_value":       _DEFAULT_CUTOFF,
                "weight":             1,
                "national_coverage_pct": None,
                "notes":              "Niet in metadata",
                "vrt_band":           band_num,
            }))

    result = pd.DataFrame(rows).reset_index(drop=True)
    log.info("Band-metadata koppeling: %d VRT-banden verwerkt", band_num)
    return result


def _mask_vrt(
    vrt_path: Path,
    geom: BaseGeometry,
    band_indices: list[int] | None,
) -> tuple[np.ndarray, Affine, str, np.ndarray]:
    """Mask de VRT op de geometrie en retourneer (data, transform, crs, nodata_mask).

    Returns
    -------
    data
        float32 array (n_bands, rows, cols), waarden 0–1.
    transform
        Affine transform van het uitgeknipte raster.
    crs
        CRS-string (bijv. "EPSG:28992").
    nodata_mask
        bool array (rows, cols), True = pixel binnen geometrie.
    """
    geometries = [mapping(geom)]

    with rasterio.open(vrt_path) as src:
        epsg = src.crs.to_epsg() if src.crs else None
        if epsg != 28992:
            raise BesiFetchError(
                f"VRT heeft CRS EPSG:{epsg}, EPSG:28992 verwacht."
            )

        indexes = band_indices if band_indices is not None else list(range(1, src.count + 1))
        opp_ha = float(geom.area) / 10_000

        if opp_ha > _CHUNK_THRESHOLD_HA:
            log.info(
                "Groot gebied (%.0f ha > %.0f ha): chunk-gewijze verwerking",
                opp_ha, _CHUNK_THRESHOLD_HA,
            )
            out_image, out_transform = _mask_chunked(src, geometries, indexes)
        else:
            out_image, out_transform = rasterio_mask(
                src, geometries,
                crop=True, nodata=0, indexes=indexes,
                filled=True, all_touched=False,
            )

        crs_str = src.crs.to_string()

    data = out_image.astype(np.float32) / _DATA_SCALE_FACTOR

    rows_px, cols_px = data.shape[1], data.shape[2]
    nodata_mask = ~geometry_mask(
        geometries=geometries,
        transform=out_transform,
        invert=False,
        out_shape=(rows_px, cols_px),
    )
    data[:, ~nodata_mask] = 0.0

    log.info(
        "%d banden geladen, %d×%d px, %.1f ha (raster)",
        len(indexes), rows_px, cols_px, nodata_mask.sum() * _CEL_OPPERVLAKTE_HA,
    )
    return data, out_transform, crs_str, nodata_mask


def _mask_chunked(
    src: rasterio.DatasetReader,
    geometries: list,
    indexes: list[int],
    chunk_size: int = 512,
) -> tuple[np.ndarray, Affine]:
    """Lees gemaskeerde data in verticale chunks (geheugenefficiënt voor grote gebieden)."""
    first_chunk, out_transform = rasterio_mask(
        src, geometries, crop=True, nodata=0, indexes=indexes[:1], filled=True
    )
    rows_total = first_chunk.shape[1]
    cols_total = first_chunk.shape[2]

    out = np.zeros((len(indexes), rows_total, cols_total), dtype=np.uint8)

    for start_row in range(0, rows_total, chunk_size):
        end_row = min(start_row + chunk_size, rows_total)
        window = rasterio.windows.Window(0, start_row, cols_total, end_row - start_row)
        for b_pos, b_idx in enumerate(indexes):
            out[b_pos, start_row:end_row, :] = src.read(b_idx, window=window)

    area_mask = ~geometry_mask(
        geometries=geometries,
        transform=out_transform,
        invert=False,
        out_shape=(rows_total, cols_total),
    )
    out[:, ~area_mask] = 0
    return out, out_transform


# ---------------------------------------------------------------------------
# Privé helpers — berekeningen (geport van BeSI/core/calculator.py)
# ---------------------------------------------------------------------------


def _apply_cutoffs(data: np.ndarray, band_mapping: pd.DataFrame) -> np.ndarray:
    """Zet float-kansen (0–1) om naar binaire aanwezigheid per soort per cel."""
    n_bands = data.shape[0]
    if len(band_mapping) != n_bands:
        raise BesiFetchError(
            f"band_mapping heeft {len(band_mapping)} rijen maar data heeft {n_bands} banden."
        )
    cutoffs = (
        band_mapping["cutoff_value"]
        .fillna(_DEFAULT_CUTOFF)
        .to_numpy(dtype=np.float32)
    )
    cutoffs = np.where(cutoffs <= 0, _DEFAULT_CUTOFF, cutoffs)
    return data >= cutoffs[:, np.newaxis, np.newaxis]


def _species_richness(binary: np.ndarray) -> np.ndarray:
    """Tel aanwezige soorten per cel → int16 raster."""
    richness = binary.sum(axis=0).astype(np.int16)
    log.debug(
        "Soortenrijkdom: max %d soorten/cel, %d cellen met ≥1 soort",
        int(richness.max()), int((richness > 0).sum()),
    )
    return richness


def _weighted_richness(binary: np.ndarray, band_mapping: pd.DataFrame) -> np.ndarray:
    """Bereken gewogen soortenrijkdom per cel (som beschermingsgewichten)."""
    weights = band_mapping["weight"].fillna(1).to_numpy(dtype=np.float32)
    return (binary.astype(np.float32) * weights[:, np.newaxis, np.newaxis]).sum(axis=0)


def _classify(data: np.ndarray, n_classes: int = _N_KLASSEN) -> np.ndarray:
    """Gelijke-interval classificatie in n_classes klassen (0 = buiten gebied)."""
    result = np.zeros_like(data, dtype=np.uint8)
    valid_mask = data > 0
    if not valid_mask.any():
        return result

    valid_values = data[valid_mask]
    vmin = float(valid_values.min())
    vmax = float(valid_values.max())

    if vmin == vmax:
        result[valid_mask] = n_classes
        return result

    edges = np.linspace(vmin, vmax + 1e-9, n_classes + 1)
    for cls in range(n_classes):
        in_class = valid_mask & (data >= edges[cls]) & (data < edges[cls + 1])
        result[in_class] = cls + 1

    return result


def _build_species_table(
    binary: np.ndarray,
    data: np.ndarray,
    band_mapping: pd.DataFrame,
    nodata_mask: np.ndarray,
) -> pd.DataFrame:
    """Bouw soortentabel met aanwezigheid, oppervlakte en kansstatistieken.

    De kolom ``cutoff_value`` is de soortspecifieke drempelwaarde — een lage
    cutoff betekent dat de aanwezigheid op zwakker bewijs gebaseerd is en
    daarmee minder zeker. Gebruik dit in de UI als onzekerheidsmarker.
    """
    records = []
    for i, (_, meta) in enumerate(band_mapping.iterrows()):
        present_cells = binary[i] & nodata_mask
        n_cells = int(present_cells.sum())
        present = n_cells > 0
        area_ha = round(n_cells * _CEL_OPPERVLAKTE_HA, 2)

        if present:
            mean_score = round(float(data[i][present_cells].mean()), 4)
        else:
            mean_score = 0.0

        max_score = round(
            float(data[i][nodata_mask].max()) if nodata_mask.any() else 0.0, 4
        )

        records.append({
            "dutch_name":        meta.get("dutch_name", ""),
            "scientific_name":   meta.get("scientific_name", ""),
            "species_group":     meta.get("species_group", ""),
            "broad_group":       meta.get("broad_group", ""),
            "rl_category":       meta.get("rl_category", "NE"),
            "habitat_directive": meta.get("habitat_directive", ""),
            "weight":            int(meta.get("weight", 1)),
            "cutoff_value":      float(meta.get("cutoff_value", _DEFAULT_CUTOFF)),
            "present":           present,
            "area_ha":           area_ha,
            "mean_score":        mean_score,
            "max_score":         max_score,
        })

    df = pd.DataFrame(records)
    return df.sort_values(
        ["weight", "area_ha"], ascending=[False, False]
    ).reset_index(drop=True)
