#!/usr/bin/env python3
# main.py
# ============================================================
# BeSI Analyse Tool — hoofdscript
#
# Gebruik:
#   python main.py --gebied "C:/pad/naar/gebied.gpkg" --versie 2 --naam "Projectnaam"
#   python main.py --gebied "C:/pad/naar/gebied.shp" --versie 1 --groep "Vogels"
# ============================================================

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Zorg dat de projectmap in het pad zit, ook bij aanroep buiten de map
sys.path.insert(0, str(Path(__file__).parent))


def _setup_logging(log_level: str, log_dir: Path | None = None) -> None:
    """Configureer logging naar console en optioneel logbestand."""
    from config import settings

    level = getattr(logging, log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if settings.LOG_TO_FILE and log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "run.log", encoding="utf-8")
        fh.setLevel(level)
        handlers.append(fh)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BeSI Analyse Tool — soortenrijkdom en ecologische waarde",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Voorbeelden:\n"
            "  python main.py --gebied gebied.gpkg --versie 1\n"
            "  python main.py --gebied gebied.shp  --versie 2 --naam MijnProject\n"
            "  python main.py --gebied gebied.gpkg --versie 1 --groep Vogels\n"
        ),
    )
    parser.add_argument(
        "--gebied",
        required=True,
        metavar="PAD",
        help="Pad naar shapefile (.shp) of GeoPackage (.gpkg)",
    )
    parser.add_argument(
        "--versie",
        type=int,
        choices=[1, 2],
        required=True,
        help="1 = soortenrijkdom, 2 = gewogen rijkdom (inclusief versie 1)",
    )
    parser.add_argument(
        "--naam",
        default=None,
        metavar="NAAM",
        help="Projectnaam voor de output-map (standaard: gebiedsnaam + datum)",
    )
    parser.add_argument(
        "--groep",
        default=None,
        metavar="GROEP",
        help="Filter op soortengroep, bijv. 'Vogels', 'Reptielen', 'Vaatplanten'",
    )
    return parser.parse_args()


def _collect_package_versions() -> dict[str, str]:
    """Haal versies op van relevante packages via importlib.metadata."""
    import importlib.metadata

    packages = ["rasterio", "geopandas", "numpy", "pandas", "shapely", "matplotlib"]
    versions: dict[str, str] = {}
    for pkg in packages:
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = "onbekend"
    return versions


def _save_run_metadata(
    output_dir: Path,
    args: argparse.Namespace,
    gebied_opp_ha: float,
    n_banden: int,
    band_metadata_df,
) -> None:
    """Sla run-informatie op als run_metadata.json."""
    from config import settings

    groep_filter = args.groep
    meta = {
        "run_datum": datetime.now().isoformat(timespec="seconds"),
        "project_naam": args.naam,
        "versie_analyse": args.versie,
        "gebied_bestand": str(Path(args.gebied).resolve()),
        "gebied_opp_ha": round(gebied_opp_ha, 2),
        "vrt_bestand": str(settings.VRT_PATH),
        "n_banden_geladen": n_banden,
        "groep_filter": groep_filter,
        "parameters": {
            "n_klassen": settings.N_KLASSEN,
            "cutoff_methode": "metadata",
            "data_scale_factor": settings.DATA_SCALE_FACTOR,
        },
        "output_map": str(output_dir),
        "python_versie": sys.version.split()[0],
        "package_versies": _collect_package_versions(),
    }

    meta_path = output_dir / "run_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    logging.getLogger(__name__).info(f"Run-metadata opgeslagen: {meta_path.name}")


def main() -> None:
    """Hoofdfunctie: orkestreer de volledige BeSI-analyse."""
    args = _parse_args()

    # Vroege import om logging-instellingen beschikbaar te hebben
    from config import settings
    import pandas as pd
    import numpy as np

    # Bepaal projectnaam en output-map
    gebied_naam = Path(args.gebied).stem
    datum_str = datetime.now().strftime("%Y%m%d")
    project_naam = args.naam if args.naam else f"{gebied_naam}_{datum_str}"
    output_dir = settings.OUTPUT_BASE_DIR / f"{project_naam}_{datum_str}"
    output_dir.mkdir(parents=True, exist_ok=True)

    _setup_logging(settings.LOG_LEVEL, log_dir=output_dir)
    logger = logging.getLogger(__name__)
    logger.info(f"=== BeSI Analyse Tool | project: {project_naam} | versie: {args.versie} ===")

    # Importeer modules na logging-setup
    from core.loader import load_study_area, build_band_metadata_mapping, mask_vrt_to_area
    from core.calculator import (
        apply_cutoffs,
        species_richness,
        weighted_richness,
        classify_raster,
        species_table,
    )
    from output.maps import export_richness_maps, export_weighted_maps
    from output.tables import export_species_table, export_summary_stats

    # 1. Metadata laden
    logger.info("Soortmetadata laden…")
    metadata = pd.read_csv(settings.METADATA_PATH)
    logger.info(f"{len(metadata)} soorten in metadata")

    # 2. Studiegebied laden
    try:
        study_area = load_study_area(args.gebied)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    gebied_opp_ha = study_area.geometry.area.sum() / 10_000

    # 3. Band–metadata koppeling bouwen (VRT-volgorde)
    try:
        band_meta = build_band_metadata_mapping(str(settings.VRT_PATH), metadata)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    # 4. Optioneel: filter op soortengroep
    band_indices: list[int] | None = None
    if args.groep:
        mask_groep = band_meta["species_group"].str.lower() == args.groep.lower()
        if not mask_groep.any():
            beschikbaar = sorted(band_meta["species_group"].unique())
            logger.error(
                f"Soortengroep '{args.groep}' niet gevonden. "
                f"Beschikbare groepen: {', '.join(beschikbaar)}"
            )
            sys.exit(1)
        band_indices = [int(b) for b in band_meta.loc[mask_groep, "vrt_band"]]
        band_meta = band_meta[mask_groep].reset_index(drop=True)
        logger.info(f"Filter op groep '{args.groep}': {len(band_meta)} banden geselecteerd")

    # 5. VRT masken op studiegebied
    try:
        data, transform_dict = mask_vrt_to_area(
            str(settings.VRT_PATH), study_area, band_indices=band_indices
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fout bij inlezen VRT: {e}")
        logger.debug("Details:", exc_info=True)
        sys.exit(1)

    transform = transform_dict["transform"]
    crs = transform_dict["crs"]
    nodata_mask = transform_dict["nodata_mask"]
    n_banden = data.shape[0]

    # 6. Run-metadata opslaan
    _save_run_metadata(output_dir, args, gebied_opp_ha, n_banden, band_meta)

    # 7. Cutoffs toepassen
    logger.info("Cutoffs toepassen…")
    binary = apply_cutoffs(data, band_meta)

    # 8. Soortenrijkdom berekenen
    logger.info("Soortenrijkdom berekenen (versie 1)…")
    richness = species_richness(binary)

    # Hoge prioriteit: cellen boven drempelpercentage van max soortenrijkdom
    max_richness = int(richness.max())
    drempel = max_richness * settings.HOGE_PRIORITEIT_DREMPEL
    opp_hoog_prio = int((richness >= drempel).sum()) * settings.CEL_OPPERVLAKTE_HA

    # Prioriteitsklassen
    priority = classify_raster(richness.astype(float), settings.N_KLASSEN)

    # 9. Soortentabel
    logger.info("Soortentabel opbouwen…")
    soorten_df = species_table(binary, data, band_meta, nodata_mask)

    # Basisstatistieken
    valid_richness = richness[nodata_mask]
    rl_niet_lc = {"CR", "EN", "VU", "NT", "RE", "EX"}
    hrl_aanwezig = soorten_df[soorten_df["present"] & (soorten_df["habitat_directive"] != "")]
    stats: dict = {
        "n_soorten": int(soorten_df["present"].sum()),
        "n_soorten_rl": int(
            soorten_df[soorten_df["present"] & soorten_df["rl_category"].isin(rl_niet_lc)].shape[0]
        ),
        "n_soorten_hrl": int(len(hrl_aanwezig)),
        "opp_hoog_prio_ha": round(opp_hoog_prio, 1),
        "gem_rijkdom": round(float(valid_richness.mean()) if len(valid_richness) > 0 else 0, 1),
        "max_rijkdom": int(max_richness),
    }

    # 10. Versie 1 outputs
    logger.info("Versie 1 outputs exporteren…")
    export_richness_maps(richness, priority, transform, crs, str(output_dir), project_naam)
    export_species_table(soorten_df, str(output_dir), project_naam)

    # 11. Versie 2: gewogen rijkdom
    if args.versie == 2:
        logger.info("Gewogen rijkdom berekenen (versie 2)…")
        weighted = weighted_richness(binary, band_meta)
        eco_value = classify_raster(weighted, settings.N_KLASSEN)

        valid_weighted = weighted[nodata_mask]
        stats["gem_gewogen"] = round(float(valid_weighted.mean()) if len(valid_weighted) > 0 else 0, 1)
        stats["max_gewogen"] = round(float(valid_weighted.max()), 1)

        logger.info("Versie 2 outputs exporteren…")
        export_weighted_maps(weighted, eco_value, transform, crs, str(output_dir), project_naam)

    # 12. Statistieken
    export_summary_stats(stats, str(output_dir), project_naam)

    logger.info(f"=== Analyse klaar. Output: {output_dir} ===")
    logger.info(
        f"Samenvatting: {stats['n_soorten']} soorten aanwezig, "
        f"max {stats['max_rijkdom']} soorten/cel, "
        f"{stats['opp_hoog_prio_ha']} ha hoge prioriteit"
    )


if __name__ == "__main__":
    main()
