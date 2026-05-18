# core/spatial.py
# ============================================================
# Ruimtelijke I/O: GeoTIFF-schrijven en PNG-export
# ============================================================

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless rendering, geen GUI nodig
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.transform import Affine

logger = logging.getLogger(__name__)


def to_geotiff(
    data: np.ndarray,
    transform: Affine,
    crs: str,
    output_path: str,
    dtype: str | None = None,
    nodata: int | float = 0,
) -> None:
    """
    Schrijf een 2D numpy-array als single-band GeoTIFF.

    Parameters
    ----------
    data : np.ndarray
        2D-array met rasterwaarden.
    transform : Affine
        Rasterio Affine-transform.
    crs : str
        CRS als string (bijv. 'EPSG:28992').
    output_path : str
        Uitvoerpad voor de GeoTIFF.
    dtype : str | None
        Rasterio-dtype (bijv. 'int16', 'float32', 'uint8').
        Wordt afgeleid uit data.dtype als None.
    nodata : int | float
        Nodata-waarde (standaard 0).
    """
    if dtype is None:
        dtype = data.dtype.name

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=dtype,
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="lzw",
    ) as dst:
        dst.write(data.astype(dtype), 1)

    logger.debug(f"GeoTIFF geschreven: {output_path}")


def to_png(
    data: np.ndarray,
    output_path: str,
    colormap: str = "YlOrRd",
    title: str = "",
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    """
    Exporteer een 2D raster als PNG met matplotlib.

    Cellen met waarde 0 worden transparant weergegeven. De kleurschaal
    loopt van geel (laag) naar rood (hoog) bij de standaard colormap.
    Een colorbar en optionele titel worden toegevoegd.

    Parameters
    ----------
    data : np.ndarray
        2D-array met rasterwaarden.
    output_path : str
        Uitvoerpad voor de PNG.
    colormap : str
        Matplotlib-colormap naam (standaard 'YlOrRd').
    title : str
        Kaarttitel.
    vmin : float | None
        Minimum kleurschaalwaarde. Afgeleid van data als None.
    vmax : float | None
        Maximum kleurschaalwaarde. Afgeleid van data als None.
    """
    from config import settings

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Masker 0-waarden voor transparante achtergrond
    masked_data = np.ma.masked_where(data == 0, data.astype(float))

    valid = masked_data.compressed()
    if vmin is None:
        vmin = float(valid.min()) if len(valid) > 0 else 0
    if vmax is None:
        vmax = float(valid.max()) if len(valid) > 0 else 1

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_facecolor("white")

    cmap = plt.get_cmap(colormap).copy()
    cmap.set_bad(alpha=0.0)  # transparant voor gemaskeerde waarden

    im = ax.imshow(
        masked_data,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.ax.tick_params(labelsize=9)

    if title:
        ax.set_title(title, fontsize=12, pad=10)

    ax.set_xticks([])
    ax.set_yticks([])

    fig.tight_layout()
    fig.savefig(output_path, dpi=settings.PNG_DPI, bbox_inches="tight", transparent=True)
    plt.close(fig)

    logger.debug(f"PNG geschreven: {output_path}")
