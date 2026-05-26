"""Eenmalige conversie ESRI_Backups snapshot -> GeoParquet + content-addressed attachments + manifests.

Bron : C:/GIS_Projecten/ArcGIS_online/ESRI_Backups/bku_20260518_200013/
Doel : C:/GIS_Projecten/ArcGIS_online/Databeheer/04_snapshots/agol_backup_20260518/

Structuur output:
    layers/<itemid>__<safe_item>/<safe_layer>.parquet
    attachments/<sha2[:2]>/<sha2>.<ext>
    info/<itemid>/<original_info>.json    (klein, voor referentie)
    manifest_items.parquet
    manifest_layers.parquet
    manifest_attachments.parquet
    convert.log

Usage:
    python scripts/convert_esri_backup.py                # alles
    python scripts/convert_esri_backup.py --sample 10    # eerste 10 items (validatie)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

SRC = Path(r"C:/GIS_Projecten/ArcGIS_online/ESRI_Backups/bku_20260518_200013")
DST = Path(r"C:/GIS_Projecten/ArcGIS_online/Databeheer/04_snapshots/agol_backup_20260518")

LAYERS_DIR = DST / "layers"
ATT_DIR = DST / "attachments"
INFO_DIR = DST / "info"
LOG_PATH = DST / "convert.log"

SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe(name: str, maxlen: int = 80) -> str:
    s = SAFE_RE.sub("_", name).strip("_")
    return s[:maxlen] if len(s) > maxlen else s


def setup_logging() -> logging.Logger:
    DST.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("convert")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def parse_item_folder(name: str) -> tuple[str, str]:
    """Folder = '<title>_<32hex itemid>'. Return (title, itemid). If no match -> ('', name)."""
    if len(name) > 33 and name[-33] == "_" and re.fullmatch(r"[0-9a-f]{32}", name[-32:]):
        return name[:-33], name[-32:]
    return name, ""


def convert_layer_json(data_json: Path, out_path: Path, logger: logging.Logger) -> dict | None:
    """Convert one ESRI feature service data.json to GeoParquet. Returns stats dict or None on failure."""
    try:
        src_bytes = data_json.stat().st_size
        # geopandas reads ESRI JSON via pyogrio (preferred) of fiona
        gdf = gpd.read_file(data_json)
        n = len(gdf)
        if n == 0:
            # geen rijen — sla over
            logger.info(f"  leeg: {data_json.name}")
            return {"rows": 0, "src_bytes": src_bytes, "dst_bytes": 0, "geom_type": None, "crs": None, "path": ""}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Sommige ESRI velden zijn epoch-ms integers — laat staan, vlak voor schrijven
        try:
            gdf.to_parquet(out_path, compression="zstd", index=False)
        except Exception:
            # geen geometrie -> fallback naar gewone parquet
            df = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name], errors="ignore"))
            df.to_parquet(out_path, compression="zstd", index=False)
        dst_bytes = out_path.stat().st_size
        geom_type = str(gdf.geom_type.iloc[0]) if gdf.geometry.notna().any() else None
        crs = str(gdf.crs) if gdf.crs else None
        return {
            "rows": n,
            "src_bytes": src_bytes,
            "dst_bytes": dst_bytes,
            "geom_type": geom_type,
            "crs": crs,
            "path": str(out_path.relative_to(DST)).replace("\\", "/"),
        }
    except Exception as e:
        logger.warning(f"  FAIL {data_json.name}: {e}")
        return None


def handle_attachment(src: Path, logger: logging.Logger, seen: dict[str, str]) -> tuple[str, str, int] | None:
    """Hash + copy to content-addressed store. Returns (sha256, dst_rel, bytes)."""
    try:
        size = src.stat().st_size
        sha = sha256_file(src)
        if sha in seen:
            return sha, seen[sha], size
        sub = sha[:2]
        ext = src.suffix.lower()
        dst = ATT_DIR / sub / f"{sha}{ext}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy2(src, dst)
        rel = str(dst.relative_to(DST)).replace("\\", "/")
        seen[sha] = rel
        return sha, rel, size
    except Exception as e:
        logger.warning(f"  ATT-FAIL {src.name}: {e}")
        return None


def process_item(item_dir: Path, logger: logging.Logger, seen_att: dict[str, str]) -> dict:
    title, itemid = parse_item_folder(item_dir.name)
    item_key = safe(title)
    if itemid:
        item_out = LAYERS_DIR / f"{itemid}__{item_key}"
    else:
        item_out = LAYERS_DIR / item_key

    # info json's bewaren (klein, ~10KB)
    info_out = INFO_DIR / (itemid or item_key)
    info_out.mkdir(parents=True, exist_ok=True)

    layer_records: list[dict] = []
    att_records: list[dict] = []

    # 1. lagen
    data_jsons = sorted(item_dir.glob("*_data.json"))
    for dj in data_jsons:
        layer_name = dj.name[: -len("_data.json")]
        # ESRI prefixt vaak '<idx>_' bij layer name; behoud voor uniciteit
        safe_layer = safe(layer_name)
        out = item_out / f"{safe_layer}.parquet"
        stats = convert_layer_json(dj, out, logger)
        rec = {
            "itemid": itemid,
            "item_title": title,
            "layer_name": layer_name,
            "src_name": dj.name,
            "ok": stats is not None,
        }
        if stats:
            rec.update(stats)
        layer_records.append(rec)

    # 2. info jsons kopieren (klein, behoud voor metadata)
    for ij in item_dir.glob("*_info.json"):
        try:
            shutil.copy2(ij, info_out / ij.name)
        except Exception as e:
            logger.warning(f"  info-copy fail {ij.name}: {e}")
    # ook root item-json (metadata van item zelf)
    for rj in item_dir.glob(f"*{itemid}.json") if itemid else []:
        try:
            shutil.copy2(rj, info_out / rj.name)
        except Exception:
            pass

    # 3. attachments
    att_root = item_dir / "0_attachments"
    if att_root.exists():
        for f in att_root.rglob("*"):
            if f.is_file():
                res = handle_attachment(f, logger, seen_att)
                if res:
                    sha, rel, size = res
                    att_records.append({
                        "itemid": itemid,
                        "item_title": title,
                        "src_rel": str(f.relative_to(item_dir)).replace("\\", "/"),
                        "sha256": sha,
                        "dst_rel": rel,
                        "bytes": size,
                    })

    return {
        "itemid": itemid,
        "item_title": title,
        "item_dir": item_dir.name,
        "n_layers": len(layer_records),
        "n_layers_ok": sum(1 for r in layer_records if r["ok"]),
        "n_attachments": len(att_records),
        "layers": layer_records,
        "attachments": att_records,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="Beperkt tot eerste N items (validatie).")
    ap.add_argument("--skip-attachments", action="store_true")
    args = ap.parse_args()

    logger = setup_logging()
    logger.info(f"START. src={SRC} dst={DST} sample={args.sample}")
    t0 = time.time()

    items = [d for d in sorted(SRC.iterdir()) if d.is_dir()]
    if args.sample:
        items = items[: args.sample]
    logger.info(f"Items te verwerken: {len(items)}")

    LAYERS_DIR.mkdir(parents=True, exist_ok=True)
    ATT_DIR.mkdir(parents=True, exist_ok=True)
    INFO_DIR.mkdir(parents=True, exist_ok=True)

    seen_att: dict[str, str] = {}
    item_summaries: list[dict] = []
    all_layers: list[dict] = []
    all_atts: list[dict] = []

    for i, item in enumerate(items, 1):
        t_item = time.time()
        logger.info(f"[{i}/{len(items)}] {item.name}")
        res = process_item(item, logger, seen_att)
        item_summaries.append({k: v for k, v in res.items() if k not in ("layers", "attachments")})
        all_layers.extend(res["layers"])
        all_atts.extend(res["attachments"])
        logger.info(
            f"  done in {time.time() - t_item:.1f}s | layers ok {res['n_layers_ok']}/{res['n_layers']} "
            f"| attachments {res['n_attachments']}"
        )

    # Manifests
    logger.info("Manifests schrijven...")
    pd.DataFrame(item_summaries).to_parquet(DST / "manifest_items.parquet", compression="zstd", index=False)
    pd.DataFrame(all_layers).to_parquet(DST / "manifest_layers.parquet", compression="zstd", index=False)
    pd.DataFrame(all_atts).to_parquet(DST / "manifest_attachments.parquet", compression="zstd", index=False)

    # Summary
    total_layers = len(all_layers)
    ok_layers = sum(1 for r in all_layers if r.get("ok"))
    src_bytes = sum(r.get("src_bytes", 0) for r in all_layers if r.get("ok"))
    dst_bytes = sum(r.get("dst_bytes", 0) for r in all_layers if r.get("ok"))
    unique_att = len(seen_att)
    raw_att = len(all_atts)
    logger.info("=" * 60)
    logger.info(f"KLAAR in {time.time() - t0:.1f}s")
    logger.info(f"Items                 : {len(items)}")
    logger.info(f"Lagen verwerkt        : {ok_layers}/{total_layers}")
    logger.info(f"JSON bytes  -> Parquet: {src_bytes / 1e9:.2f} GB -> {dst_bytes / 1e9:.2f} GB "
                f"({(1 - dst_bytes / src_bytes) * 100:.1f}% kleiner)" if src_bytes else "geen lagen omgezet")
    logger.info(f"Attachments references: {raw_att} | unieke files: {unique_att} "
                f"(dedup factor {raw_att / unique_att:.2f}x)" if unique_att else "geen attachments")


if __name__ == "__main__":
    main()
