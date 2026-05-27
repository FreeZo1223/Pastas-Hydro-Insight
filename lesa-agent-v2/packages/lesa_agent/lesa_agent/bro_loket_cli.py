"""CLI + reusable function: BRO Loket ZIP -> PastaStore.

CLI:
    lesa-bro-to-pastastore INPUT.zip [--output OUT.zip] [--knmi-station 260]
                                     [--fit-models] [--rfunc Gamma]

Library:
    from lesa_agent.bro_loket_cli import bro_loket_zip_to_pastastore
    store = bro_loket_zip_to_pastastore(zip_path, work_dir=...)
"""

from __future__ import annotations

import argparse
import io
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pastastore as pst  # noqa: F401

# UTF-8 console op Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

log = logging.getLogger("lesa.bro_loket_cli")


def bro_loket_zip_to_pastastore(
    zip_path: Path | str,
    *,
    work_dir: Path | str | None = None,
    knmi_station: str | None = None,
    tmin: str = "2000-01-01",
    tmax: str | None = None,
    fit_models: bool = False,
    rfunc: str = "Gamma",
    verbose: bool = False,
) -> "pst.PastaStore":
    """Bouw een PastaStore uit een BRO Loket export-ZIP.

    Parameters
    ----------
    zip_path
        Pad naar BRO Loket-ZIP (bevat ``BRO_Grondwatermonitoring/``).
    work_dir
        Werkmap voor de PasConnector. Leeg = tijdelijke map (geheugen-only
        beschouwd; wordt automatisch opgeruimd zodra het PastaStore-object
        garbage-collected wordt).
    knmi_station
        Forceer een specifiek KNMI-stationsnummer. Leeg = dichtstbijzijnde
        klimaatstation op basis van centroid van peilbuizen.
    tmin, tmax
        Periode voor KNMI-fetch.
    fit_models
        Bouw een PASTAS RechargeModel per oseries met >100 metingen.
    rfunc
        Naam van PASTAS-responsfunctie.

    Returns
    -------
    pastastore.PastaStore
        In-memory store (PasConnector op disk). Gebruik
        ``store.to_zip(path)`` om naar ZIP te exporteren.
    """
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

    def _say(msg: str) -> None:
        if verbose:
            print(msg)

    zip_path = Path(zip_path)
    _say(f"[1/5] Parse BRO Loket export: {zip_path.name}")
    if zip_path.is_dir():
        from geo_stack.skills.bro.bro_loket import parse_bro_loket_dir
        records = parse_bro_loket_dir(zip_path)
    else:
        records = parse_bro_loket_zip(zip_path)
    records_with_xy = [r for r in records if r.x is not None and r.y is not None]
    _say(f"  -> {len(records)} GMW's, {len(records_with_xy)} met geldige RD-locatie")

    if not records_with_xy:
        raise ValueError("Geen peilbuizen met locatie gevonden in BRO Loket-ZIP")

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
    _say(f"[2/5] KNMI-station: {stn_id} ({stn_name})"
         + (f", {stn_dist:.1f} km van centroid" if stn_dist else ""))

    _say(f"[3/5] KNMI fetch ({tmin} - {tmax or 'heden'}) via hydropandas...")
    prec, evap = fetch_recharge_inputs(stn_id, start=tmin, end=tmax)
    prec = prec.rename("neerslag_KNMI")
    evap = evap.rename("verdamping_KNMI")
    _say(f"  -> {len(prec)} neerslag, {len(evap)} verdamping dagwaarden")

    _say("[4/5] PastaStore opbouwen...")
    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="lesa_bro_"))
    work.mkdir(parents=True, exist_ok=True)
    adapter = PastaStoreAdapter(
        location=StoreLocation(backend="pas", path=work, name="lesa_store"),
    )
    adapter.add_stress(
        name="neerslag_KNMI", series=prec, kind="prec",
        metadata={"x": float(cx), "y": float(cy), "station": stn_id, "naam": stn_name},
    )
    adapter.add_stress(
        name="verdamping_KNMI", series=evap, kind="evap",
        metadata={"x": float(cx), "y": float(cy), "station": stn_id, "naam": stn_name},
    )

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
            os_meta = {k: v for k, v in os_meta.items() if v is not None}
            s_daily.name = os_name
            try:
                adapter.add_oseries(name=os_name, series=s_daily, metadata=os_meta)
            except Exception as exc:  # noqa: BLE001
                log.warning("add_oseries %s faalde: %s", os_name, exc)

    _say(f"  -> {len(added_oseries)} oseries toegevoegd")

    if fit_models and added_oseries:
        _say(f"[5a/5] PASTAS RechargeModel per oseries (rfunc={rfunc})...")
        store = adapter.open()
        n_ok = 0
        for name in added_oseries:
            oseries = store.get_oseries(name)
            if len(oseries) < 100:
                _say(f"  - skip {name}: <100 metingen")
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
                    _say(f"  + {name}: R^2={result.rsq:.3f}")
                else:
                    _say(f"  - {name}: fit niet succesvol ({result.error or ''})")
            except Exception as exc:  # noqa: BLE001
                _say(f"  - {name}: crashte ({exc})")
        _say(f"  -> {n_ok}/{len(added_oseries)} modellen gefit")

    return adapter.open()


def main() -> None:
    p = argparse.ArgumentParser(prog="lesa-bro-to-pastastore", description=__doc__)
    p.add_argument("input", help="Pad naar BRO Loket export ZIP")
    p.add_argument("--output", help="Output ZIP (default: <input>_pastastore.zip)")
    p.add_argument("--knmi-station", default=None, help="KNMI-stationsnummer")
    p.add_argument("--tmin", default="2000-01-01")
    p.add_argument("--tmax", default=None)
    p.add_argument("--fit-models", action="store_true")
    p.add_argument("--rfunc", default="Gamma")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    in_path = Path(args.input).resolve()
    if not in_path.exists():
        sys.exit(f"FOUT: input ZIP bestaat niet: {in_path}")
    out_path = Path(args.output) if args.output else in_path.with_name(
        in_path.stem + "_pastastore.zip"
    )
    work_dir = out_path.parent / (out_path.stem + "_work")
    if work_dir.exists():
        shutil.rmtree(work_dir)

    store = bro_loket_zip_to_pastastore(
        in_path,
        work_dir=work_dir,
        knmi_station=args.knmi_station,
        tmin=args.tmin,
        tmax=args.tmax,
        fit_models=args.fit_models,
        rfunc=args.rfunc,
        verbose=True,
    )
    print(f"[5/5] ZIP exporteren naar {out_path}")
    if out_path.exists():
        out_path.unlink()
    store.to_zip(str(out_path))
    print(f"\nKlaar! {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
    print("Upload dit bestand in pastasdash (http://127.0.0.1:8050).")


if __name__ == "__main__":
    main()
