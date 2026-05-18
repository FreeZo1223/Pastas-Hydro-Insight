"""CLI: BRO Loket ZIP -> PastaStore ZIP (klaar voor pastasdash-upload).

Usage:
    lesa-bro-to-pastastore INPUT.zip [--output OUT.zip] [--knmi-station 260]
                                     [--fit-models] [--rfunc Gamma]

Workflow:
1. Parse BRO Loket-export (GMW XML's + GLD CSV's)
2. Resample uurwaarden naar dagelijkse gemiddelden
3. Vind dichtstbijzijnde KNMI-klimaatstation (centroid van peilbuizen)
4. Haal KNMI neerslag + verdamping (via hydropandas)
5. Bouw PastaStore met screen_top/bottom/ground_level metadata
6. Optioneel: PASTAS RechargeModel per oseries
7. Exporteer als ZIP voor pastasdash-upload
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
from pathlib import Path

# UTF-8 console op Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

log = logging.getLogger("lesa.bro_loket_cli")


def main() -> None:
    p = argparse.ArgumentParser(prog="lesa-bro-to-pastastore", description=__doc__)
    p.add_argument("input", help="Pad naar BRO Loket export ZIP")
    p.add_argument("--output", help="Output ZIP (default: <input>_pastastore.zip)")
    p.add_argument(
        "--knmi-station", default=None,
        help="KNMI-station-ID (bv. 260). Leeg = automatisch dichtstbijzijnde.",
    )
    p.add_argument("--tmin", default="2000-01-01", help="Begin-datum KNMI")
    p.add_argument("--tmax", default=None, help="Eind-datum KNMI (leeg = vandaag)")
    p.add_argument(
        "--fit-models", action="store_true",
        help="Fit een PASTAS RechargeModel per oseries (kost ~10s/buis)",
    )
    p.add_argument("--rfunc", default="Gamma", help="PASTAS responsfunctie")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s | %(message)s",
    )

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        sys.exit(f"FOUT: input ZIP bestaat niet: {in_path}")
    out_path = Path(args.output) if args.output else in_path.with_name(
        in_path.stem + "_pastastore.zip"
    )

    _build_pastastore_from_bro_loket(
        zip_in=in_path,
        zip_out=out_path,
        knmi_station=args.knmi_station,
        tmin=args.tmin,
        tmax=args.tmax,
        fit_models=args.fit_models,
        rfunc=args.rfunc,
    )


def _build_pastastore_from_bro_loket(
    *,
    zip_in: Path,
    zip_out: Path,
    knmi_station: str | None,
    tmin: str,
    tmax: str | None,
    fit_models: bool,
    rfunc: str,
) -> None:
    import pandas as pd
    import pyproj
    import pastastore as pst

    from geo_stack.skills.bro.bro_loket import (
        daily_mean, parse_bro_loket_zip, parse_gld_csv,
    )
    from geo_stack.skills.knmi import (
        fetch_recharge_inputs, list_climate_stations, nearest_climate_station,
    )
    from pastas_adapter.fit import FitConfig, fit_oseries
    from pastas_adapter.store import PastaStoreAdapter, StoreLocation

    print(f"[1/5] Parse BRO Loket export: {zip_in.name}")
    records = parse_bro_loket_zip(zip_in)
    records_with_xy = [r for r in records if r.x is not None and r.y is not None]
    print(f"  -> {len(records)} GMW's, {len(records_with_xy)} met geldige RD-locatie")

    if not records_with_xy:
        sys.exit("FOUT: geen peilbuizen met locatie gevonden")

    # Centroid voor KNMI-station-zoekactie
    xs = [r.x for r in records_with_xy]
    ys = [r.y for r in records_with_xy]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    transformer = pyproj.Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(cx, cy)

    if knmi_station:
        stations = list_climate_stations()
        stn_id = knmi_station
        stn_name = stations.get(stn_id, ("?", "?", "(handmatig)"))[2]
        stn_dist = None
    else:
        stn_id, stn_dist, stn_name = nearest_climate_station(lat, lon)
    print(f"[2/5] KNMI-station: {stn_id} ({stn_name})"
          + (f", {stn_dist:.1f} km van centroid" if stn_dist else ""))

    print(f"[3/5] KNMI fetch ({tmin} - {tmax or 'heden'}) via hydropandas...")
    try:
        prec, evap = fetch_recharge_inputs(stn_id, start=tmin, end=tmax)
        # Hernoem zodat ze matchen met PastaStore-keys
        prec = prec.rename("neerslag_KNMI")
        evap = evap.rename("verdamping_KNMI")
        print(f"  -> {len(prec)} neerslag, {len(evap)} verdamping dagwaarden")
    except Exception as exc:
        sys.exit(f"FOUT: KNMI-fetch faalde: {exc}")

    print(f"[4/5] PastaStore opbouwen...")
    work_dir = zip_out.parent / (zip_out.stem + "_work")
    work_dir.mkdir(parents=True, exist_ok=True)
    adapter = PastaStoreAdapter(
        location=StoreLocation(backend="pas", path=work_dir, name="lesa_store"),
    )
    adapter.add_stress(
        name="neerslag_KNMI", series=prec, kind="prec",
        metadata={"x": float(cx), "y": float(cy), "station": stn_id, "naam": stn_name},
    )
    adapter.add_stress(
        name="verdamping_KNMI", series=evap, kind="evap",
        metadata={"x": float(cx), "y": float(cy), "station": stn_id, "naam": stn_name},
    )

    # Per GMW: per (gld_id, csv) een oseries
    added_oseries: list[str] = []
    for rec in records_with_xy:
        for gld_id, csv_text in rec.gld_csvs:
            s_hourly, tube_nr_csv = parse_gld_csv(csv_text)
            if s_hourly.empty:
                continue
            s_daily = daily_mean(s_hourly)
            if s_daily.empty:
                continue

            tube_nr = tube_nr_csv if tube_nr_csv is not None else (
                next(iter(rec.tubes.keys()), 1)
            )
            tube_meta = rec.tubes.get(tube_nr)
            # Oseries-naam = GMW_tube_GLD (uniek, herkenbaar)
            os_name = f"{rec.gmw_id}_{tube_nr}"
            if os_name in added_oseries:
                os_name = f"{rec.gmw_id}_{tube_nr}_{gld_id}"
            added_oseries.append(os_name)

            os_meta: dict = {
                "x": float(rec.x), "y": float(rec.y),
                "ground_level": rec.ground_level,
                "tube_nr": tube_nr,
                "well_code": rec.well_code,
                "nitg_code": rec.nitg_code,
                "gld_id": gld_id,
                "unit": "m NAP",
                "bron": "BRO Loket",
            }
            if tube_meta:
                os_meta["screen_top"] = tube_meta.screen_top
                os_meta["screen_bottom"] = tube_meta.screen_bottom
                os_meta["tube_top"] = tube_meta.tube_top
            os_meta.setdefault("screen_top", float("nan"))
            os_meta.setdefault("screen_bottom", float("nan"))

            # Strip None-values (pastastore stoort daar over)
            os_meta = {k: v for k, v in os_meta.items() if v is not None}
            s_daily.name = os_name
            try:
                adapter.add_oseries(name=os_name, series=s_daily, metadata=os_meta)
            except Exception as exc:
                log.warning("add_oseries %s faalde: %s", os_name, exc)

    print(f"  -> {len(added_oseries)} oseries toegevoegd")

    # PASTAS-fits
    if fit_models and added_oseries:
        print(f"[5a/5] PASTAS RechargeModel per oseries (rfunc={rfunc})...")
        store = adapter.open()
        n_ok = 0
        for name in added_oseries:
            oseries = store.get_oseries(name)
            if len(oseries) < 100:
                print(f"  - skip {name}: <100 metingen")
                continue
            cfg = FitConfig(name=name, rfunc=rfunc, noise_model=True)
            try:
                result, ml = fit_oseries(
                    oseries=oseries,
                    stresses={"neerslag": prec, "verdamping": evap},
                    config=cfg,
                )
                if result.success:
                    adapter.add_model(name=name, ml=ml)
                    n_ok += 1
                    print(f"  + {name}: R^2={result.rsq:.3f}")
                else:
                    print(f"  - {name}: fit niet succesvol ({result.error or ''})")
            except Exception as exc:
                print(f"  - {name}: crashte ({exc})")
        print(f"  -> {n_ok}/{len(added_oseries)} modellen gefit")

    # ZIP exporteren
    print(f"[5/5] ZIP exporteren naar {zip_out}")
    store = adapter.open()
    if zip_out.exists():
        zip_out.unlink()
    store.to_zip(str(zip_out))
    size_kb = zip_out.stat().st_size / 1024
    print(f"\nKlaar! {zip_out} ({size_kb:.1f} KB)")
    print(f"Upload dit bestand in pastasdash (http://127.0.0.1:8050).")


if __name__ == "__main__":
    main()
