# core/loader.py
# ============================================================
# Inladen van VRT, studiegebied, masking en band-metadata koppeling
# ============================================================

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask as rasterio_mask
from shapely.geometry import mapping

logger = logging.getLogger(__name__)

TARGET_CRS = "EPSG:28992"


def load_study_area(path: str) -> gpd.GeoDataFrame:
    """
    Laad een studiegebied uit shapefile of GeoPackage.

    Detecteert het bestandstype op extensie, valideert aanwezigheid van
    geometrieën en reprojecteert automatisch naar EPSG:28992 (RD New)
    als de CRS afwijkt.

    Parameters
    ----------
    path : str
        Pad naar shapefile (.shp) of GeoPackage (.gpkg).

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame in EPSG:28992.

    Raises
    ------
    FileNotFoundError
        Als het bestand niet bestaat.
    ValueError
        Als het bestand geen geometrieën bevat of een onbekende extensie heeft.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Gebiedsbestand niet gevonden: {path}")

    ext = p.suffix.lower()
    if ext not in (".shp", ".gpkg"):
        raise ValueError(f"Onbekend bestandstype '{ext}'. Gebruik .shp of .gpkg.")

    logger.info(f"Studiegebied laden: {path}")
    gdf = gpd.read_file(path)

    if gdf.empty or gdf.geometry.isnull().all():
        raise ValueError(f"Geen geldige geometrieën gevonden in {path}")

    gdf = gdf[~gdf.geometry.isnull()]

    if gdf.crs is None:
        logger.warning("CRS onbekend in gebiedsbestand, aanname EPSG:28992")
        gdf = gdf.set_crs(TARGET_CRS)
    elif gdf.crs.to_epsg() != 28992:
        logger.info(f"CRS {gdf.crs.to_epsg()} → reprojectie naar EPSG:28992")
        gdf = gdf.to_crs(TARGET_CRS)

    opp_ha = gdf.geometry.area.sum() / 10_000
    logger.info(f"Studiegebied geladen: {len(gdf)} feature(s), {opp_ha:.1f} ha")
    return gdf


def load_vrt(vrt_path: str) -> rasterio.DatasetReader:
    """
    Open de Master VRT voor BeSI-lagen.

    Valideert bestaan en CRS (moet EPSG:28992 zijn). De aanroeper is
    verantwoordelijk voor het sluiten van het dataset-object.

    Parameters
    ----------
    vrt_path : str
        Pad naar de .vrt-bestand.

    Returns
    -------
    rasterio.DatasetReader
        Open rasterio dataset.

    Raises
    ------
    FileNotFoundError
        Als het VRT-bestand niet bestaat.
    ValueError
        Als de CRS niet EPSG:28992 is.
    """
    p = Path(vrt_path)
    if not p.exists():
        raise FileNotFoundError(f"VRT-bestand niet gevonden: {vrt_path}")

    ds = rasterio.open(vrt_path)
    epsg = ds.crs.to_epsg() if ds.crs else None
    if epsg != 28992:
        ds.close()
        raise ValueError(
            f"VRT heeft CRS EPSG:{epsg}, maar EPSG:28992 (RD New) verwacht."
        )

    logger.debug(f"VRT geopend: {ds.count} banden, {ds.width}×{ds.height} px")
    return ds


def build_band_metadata_mapping(vrt_path: str, metadata: pd.DataFrame) -> pd.DataFrame:
    """
    Bepaal de bandvolgorde in de VRT en koppel elke band aan een metadatarij.

    De VRT-banden zijn alfabetisch geordend op soortnaam (COG-bestandsnaam),
    terwijl de metadata is geordend op soortengroep. Koppeling vindt plaats
    via meerdere strategieën (case-insensitief):
        1. directe stem-match op dutch_name
        2. tekst vóór haakjes op dutch_name (bv. "Brachycentrus subnubilus")
        3. tekst binnen haakjes op dutch_name (bv. "Witkuifje" uit "...(Witkuifje)")
        4. stem op scientific_name

    Bands zonder metadata-match worden **overgeslagen** (niet stilzwijgend
    voorzien van een default cutoff). Dit voorkomt dat soorten zonder
    metadata onterecht als 'aanwezig' worden gerapporteerd.

    Parameters
    ----------
    vrt_path : str
        Pad naar de VRT.
    metadata : pd.DataFrame
        Geladen species_metadata.csv met kolom 'dutch_name'.

    Returns
    -------
    pd.DataFrame
        DataFrame met één rij per **gematchte** VRT-band, met alle
        metadata-kolommen plus 'vrt_band' (1-gebaseerde bandindex).
        Het aantal rijen kan kleiner zijn dan het aantal VRT-banden.
    """
    tree = ET.parse(vrt_path)
    root = tree.getroot()

    meta_by_dutch: dict[str, pd.Series] = {
        str(row["dutch_name"]).strip().lower(): row
        for _, row in metadata.iterrows()
        if pd.notna(row.get("dutch_name"))
    }
    meta_by_sci: dict[str, pd.Series] = {
        str(row["scientific_name"]).strip().lower(): row
        for _, row in metadata.iterrows()
        if pd.notna(row.get("scientific_name")) and str(row["scientific_name"]).strip()
    }

    rows: list[pd.Series] = []
    skipped: list[tuple[int, str]] = []
    band_num = 0
    for band_el in root.findall("VRTRasterBand"):
        band_num += 1
        source_el = band_el.find(".//SourceFilename")
        if source_el is None or not source_el.text:
            skipped.append((band_num, "(geen bestandsnaam)"))
            continue

        filename = Path(source_el.text).name        # Athripsodes albifrons(Witkuifje)_cog.tif
        stem = filename.replace("_cog.tif", "")     # Athripsodes albifrons(Witkuifje)
        stem_lc = stem.strip().lower()
        before_paren = re.sub(r"\s*\([^)]*\)\s*$", "", stem).strip().lower()
        inside_match = re.search(r"\(([^)]+)\)", stem)
        inside = inside_match.group(1).strip().lower() if inside_match else None

        match: pd.Series | None = None
        if stem_lc in meta_by_dutch:
            match = meta_by_dutch[stem_lc]
        elif before_paren and before_paren in meta_by_dutch:
            match = meta_by_dutch[before_paren]
        elif inside and inside in meta_by_dutch:
            match = meta_by_dutch[inside]
        elif before_paren and before_paren in meta_by_sci:
            match = meta_by_sci[before_paren]

        if match is None:
            skipped.append((band_num, stem))
            continue

        row = match.copy()
        row["vrt_band"] = band_num
        rows.append(row)

    result = pd.DataFrame(rows).reset_index(drop=True)
    if skipped:
        logger.warning(
            f"{len(skipped)} van {band_num} VRT-banden hebben geen metadata-match "
            "en worden uitgesloten van de analyse"
        )
        voorbeelden = ", ".join(name for _, name in skipped[:8])
        logger.warning(f"  Voorbeelden: {voorbeelden}{'…' if len(skipped) > 8 else ''}")
        logger.warning(
            "  Voeg deze soorten toe aan config/species_metadata.csv om ze mee te nemen."
        )
    logger.info(f"Band-metadata koppeling: {len(result)}/{band_num} banden gekoppeld")
    return result


def mask_vrt_to_area(
    vrt_path: str,
    study_area: gpd.GeoDataFrame,
    band_indices: list[int] | None = None,
) -> tuple[np.ndarray, dict]:
    """
    Masker de VRT op het studiegebied en retourneer de gemaskte data.

    Gebruikt rasterio.mask.mask() voor exacte polygoonclipping. Nodata-waarden
    (0) worden naar 0 gezet (zijn al 0). Voor gebieden groter dan
    settings.CHUNK_THRESHOLD_HA wordt chunk-gewijze verwerking gebruikt.

    Parameters
    ----------
    vrt_path : str
        Pad naar de VRT.
    study_area : gpd.GeoDataFrame
        Studiegebied in EPSG:28992.
    band_indices : list[int] | None
        1-gebaseerde bandindices om te laden. None = alle banden.

    Returns
    -------
    tuple[np.ndarray, dict]
        - array : shape (n_bands, rows, cols), dtype float32, waarden 0–1.
          Buiten het studiegebied is de waarde 0.
        - transform_dict : dict met sleutels:
            - 'transform' : rasterio.Affine
            - 'crs'       : str (EPSG-code)
            - 'nodata_mask' : np.ndarray bool, True = binnen studiegebied
    """
    from config import settings

    geometries = [mapping(geom) for geom in study_area.geometry]

    logger.info("VRT masken op studiegebied…")

    with rasterio.open(vrt_path) as src:
        n_bands_total = src.count
        if band_indices is None:
            indexes = list(range(1, n_bands_total + 1))
        else:
            indexes = band_indices

        # Gebiedsoppervlakte bepalen voor chunkkeuze
        opp_ha = study_area.geometry.area.sum() / 10_000

        if opp_ha > settings.CHUNK_THRESHOLD_HA:
            logger.info(
                f"Groot gebied ({opp_ha:.0f} ha > {settings.CHUNK_THRESHOLD_HA:.0f} ha): "
                "chunk-gewijze verwerking"
            )
            out_image, out_transform = _mask_chunked(src, geometries, indexes)
        else:
            out_image, out_transform = rasterio_mask(
                src,
                geometries,
                crop=True,
                nodata=0,
                indexes=indexes,
                filled=True,
                all_touched=False,
            )

        crs_str = src.crs.to_string()

    # Normaliseer van Byte (0–255) naar kans (0–1)
    data = out_image.astype(np.float32) / settings.DATA_SCALE_FACTOR

    # Bouw nodata_mask: True waar het studiegebied de pixels dekt
    rows_px, cols_px = data.shape[1], data.shape[2]
    nodata_mask = ~geometry_mask(
        geometries=geometries,
        transform=out_transform,
        invert=False,
        out_shape=(rows_px, cols_px),
    )

    # Zet pixels buiten gebied op 0
    data[:, ~nodata_mask] = 0.0

    logger.info(
        f"{len(indexes)} banden geladen, rastergrootte {rows_px}×{cols_px} px, "
        f"gebied {nodata_mask.sum() * 0.0625:.1f} ha (raster)"
    )

    transform_dict = {
        "transform": out_transform,
        "crs": crs_str,
        "nodata_mask": nodata_mask,
    }
    return data, transform_dict


def _mask_chunked(
    src: rasterio.DatasetReader,
    geometries: list,
    indexes: list[int],
    chunk_size: int = 512,
) -> tuple[np.ndarray, object]:
    """
    Lees de gemaskeerde data in verticale chunks van chunk_size rijen.

    Wordt intern aangeroepen door mask_vrt_to_area voor grote gebieden.
    Bepaalt eerst het source-window dat het studiegebied dekt en leest
    daarna chunks via dat window — niet via output-coördinaten.
    """
    from shapely.geometry import shape
    from rasterio.windows import from_bounds, Window
    from rasterio.features import geometry_mask as geo_mask

    union_geom = gpd.GeoSeries(
        [shape(g) for g in geometries], crs=TARGET_CRS
    ).unary_union
    minx, miny, maxx, maxy = union_geom.bounds

    src_window = from_bounds(
        minx, miny, maxx, maxy, transform=src.transform
    ).round_offsets().round_lengths()
    src_window = src_window.intersection(
        Window(0, 0, src.width, src.height)
    )
    rows_total = int(src_window.height)
    cols_total = int(src_window.width)
    out_transform = src.window_transform(src_window)
    col_off = int(src_window.col_off)
    row_off = int(src_window.row_off)

    out = np.zeros((len(indexes), rows_total, cols_total), dtype=np.uint8)

    for start_row in range(0, rows_total, chunk_size):
        end_row = min(start_row + chunk_size, rows_total)
        chunk_win = Window(
            col_off, row_off + start_row,
            cols_total, end_row - start_row,
        )
        for b_pos, b_idx in enumerate(indexes):
            out[b_pos, start_row:end_row, :] = src.read(b_idx, window=chunk_win)

    area_mask = ~geo_mask(
        geometries=geometries,
        transform=out_transform,
        invert=False,
        out_shape=(rows_total, cols_total),
    )
    out[:, ~area_mask] = 0

    return out, out_transform
