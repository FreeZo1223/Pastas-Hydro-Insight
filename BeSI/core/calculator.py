# core/calculator.py
# ============================================================
# Berekeningen: cutoffs, soortenrijkdom, gewogen rijkdom, classificatie
# ============================================================

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def apply_cutoffs(data: np.ndarray, metadata: pd.DataFrame) -> np.ndarray:
    """
    Zet kanswaardes (0–1) om naar binaire aanwezigheid per soort per cel.

    Per band wordt de cutoff uit de metadata-rij op die bandpositie gebruikt.
    Als cutoff_value NaN of 0 is, wordt de DEFAULT_CUTOFF uit settings toegepast.

    Parameters
    ----------
    data : np.ndarray
        Float32-array met shape (n_bands, rows, cols), waarden 0–1.
    metadata : pd.DataFrame
        Band-metadata in VRT-volgorde (één rij per band).

    Returns
    -------
    np.ndarray
        Bool-array met shape (n_bands, rows, cols).
        True = soort boven cutoff aanwezig, False = afwezig of buiten gebied.
    """
    from config import settings

    n_bands = data.shape[0]
    if len(metadata) != n_bands:
        raise ValueError(
            f"Aantal metadata-rijen ({len(metadata)}) ≠ aantal banden ({n_bands})"
        )

    cutoffs = metadata["cutoff_value"].fillna(settings.DEFAULT_CUTOFF).to_numpy(dtype=np.float32)
    cutoffs = np.where(cutoffs <= 0, settings.DEFAULT_CUTOFF, cutoffs)

    # Broadcast vergelijking: (n_bands,) vs (n_bands, rows, cols)
    binary = data >= cutoffs[:, np.newaxis, np.newaxis]

    n_present = binary.any(axis=(1, 2)).sum()
    logger.debug(f"Cutoffs toegepast: {n_present}/{n_bands} soorten ergens aanwezig")
    return binary


def species_richness(binary_data: np.ndarray) -> np.ndarray:
    """
    Tel het aantal aanwezige soorten per cel.

    Parameters
    ----------
    binary_data : np.ndarray
        Bool-array met shape (n_bands, rows, cols).

    Returns
    -------
    np.ndarray
        Integer-array met shape (rows, cols) met soortentellingen.
    """
    richness = binary_data.sum(axis=0).astype(np.int16)
    n_cells = (richness > 0).sum()
    logger.info(
        f"Soortenrijkdom: max {richness.max()} soorten/cel, "
        f"{n_cells} cellen met ≥1 soort"
    )
    return richness


def weighted_richness(binary_data: np.ndarray, metadata: pd.DataFrame) -> np.ndarray:
    """
    Bereken gewogen soortenrijkdom per cel op basis van beschermingsstatus.

    Elk aanwezig-gemarkeerde soort draagt zijn gewicht (uit metadata) bij
    aan de celwaarde. Gewichten zijn bepaald via STATUS_WEIGHTS in settings.py
    en opgeslagen in de metadata-kolom 'weight'.

    Parameters
    ----------
    binary_data : np.ndarray
        Bool-array met shape (n_bands, rows, cols).
    metadata : pd.DataFrame
        Band-metadata in VRT-volgorde, moet kolom 'weight' bevatten.

    Returns
    -------
    np.ndarray
        Float32-array met shape (rows, cols) met gewogen soortenrijkdom.
    """
    weights = metadata["weight"].fillna(1).to_numpy(dtype=np.float32)
    weighted = (binary_data.astype(np.float32) * weights[:, np.newaxis, np.newaxis]).sum(axis=0)

    logger.info(
        f"Gewogen rijkdom: max {weighted.max():.1f}, "
        f"gem {weighted[weighted > 0].mean():.1f} (binnen gebied)"
    )
    return weighted


def classify_raster(data: np.ndarray, n_classes: int = 5) -> np.ndarray:
    """
    Klassificeer rasterwaarden in n gelijke klassen (equal-interval).

    Cellen met waarde 0 (buiten gebied of geen soorten) blijven klasse 0.
    Klassen 1 t/m n_classes worden op basis van het bereik van de
    niet-nul waarden berekend.

    Parameters
    ----------
    data : np.ndarray
        2D float- of int-array.
    n_classes : int
        Aantal klassen (standaard 5).

    Returns
    -------
    np.ndarray
        Integer-array met klassen 0 (buiten/leeg) t/m n_classes.
    """
    result = np.zeros_like(data, dtype=np.uint8)
    valid_mask = data > 0

    if not valid_mask.any():
        logger.warning("Geen cellen met waarde > 0 gevonden voor classificatie")
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

    logger.debug(
        f"Classificatie: bereik [{vmin:.1f}, {vmax:.1f}] → {n_classes} klassen"
    )
    return result


def species_table(
    binary_data: np.ndarray,
    data_raw: np.ndarray,
    metadata: pd.DataFrame,
    nodata_mask: np.ndarray,
) -> pd.DataFrame:
    """
    Bouw een soortentabel voor het studiegebied.

    Per soort worden aanwezigheid, oppervlakte boven cutoff en kansstatistieken
    berekend op basis van de gemaskeerde rasterdata.

    Parameters
    ----------
    binary_data : np.ndarray
        Bool-array (n_bands, rows, cols) — aanwezigheid boven cutoff.
    data_raw : np.ndarray
        Float32-array (n_bands, rows, cols) — kanswaardes 0–1.
    metadata : pd.DataFrame
        Band-metadata in VRT-volgorde.
    nodata_mask : np.ndarray
        Bool-array (rows, cols), True = binnen studiegebied.

    Returns
    -------
    pd.DataFrame
        Soortentabel gesorteerd op weight DESC, area_ha DESC.
        Kolommen: dutch_name, scientific_name, species_group, broad_group,
        rl_category, habitat_directive, weight, present, area_ha,
        mean_score, max_score.
    """
    from config import settings

    records = []
    for i, (_, meta_row) in enumerate(metadata.iterrows()):
        presence_band = binary_data[i]         # (rows, cols) bool
        raw_band = data_raw[i]                  # (rows, cols) float32

        # Aanwezige cellen binnen het studiegebied
        present_cells = presence_band & nodata_mask
        n_cells = int(present_cells.sum())
        present = n_cells > 0

        area_ha = n_cells * settings.CEL_OPPERVLAKTE_HA

        if present:
            scores_in_area = raw_band[present_cells]
            mean_score = float(scores_in_area.mean())
            max_score = float(raw_band[nodata_mask].max())
        else:
            # Geen aanwezigheid: geef wel de maximale kans in het gebied terug
            mean_score = 0.0
            max_score = float(raw_band[nodata_mask].max()) if nodata_mask.any() else 0.0

        records.append(
            {
                "dutch_name": meta_row.get("dutch_name", ""),
                "scientific_name": meta_row.get("scientific_name", ""),
                "species_group": meta_row.get("species_group", ""),
                "broad_group": meta_row.get("broad_group", ""),
                "rl_category": meta_row.get("rl_category", "NE"),
                "habitat_directive": meta_row.get("habitat_directive", ""),
                "weight": int(meta_row.get("weight", 1)),
                "present": present,
                "area_ha": round(area_ha, 2),
                "mean_score": round(mean_score, 4),
                "max_score": round(max_score, 4),
            }
        )

    df = pd.DataFrame(records)
    df = df.sort_values(["weight", "area_ha"], ascending=[False, False]).reset_index(drop=True)

    n_present = df["present"].sum()
    logger.info(f"Soortentabel: {n_present}/{len(df)} soorten aanwezig in studiegebied")
    return df
