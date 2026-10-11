"""Het project: een PastaStore-map, in hetzelfde formaat als de desktop.

De browser kan niet rechtstreeks op schijf schrijven. De store staat daarom
in het geheugen van de pagina; ``gewijzigd()`` vertelt na elke handeling
welke bestanden veranderd zijn, en de pagina zet die in de map op schijf.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import zipfile
from pathlib import Path

import pastastore as pst

from pastasdash_v2.core.cache import invalidate_store
from pastasdash_v2.core.store import STORE
from pastasdash_v2.core.timeseries import timeseries_stats
from pastasdash_v3 import bro

# Vingerafdruk per bestand zoals de map op schijf er nu uitziet.
_op_schijf: dict[str, str] = {}


def _nette_naam(naam: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", naam).strip("_") or "project"


def nieuw(basis: str | Path, naam: str) -> None:
    """Maak een lege store ``<basis>/<naam>`` en open hem."""
    naam = _nette_naam(naam)
    doel = Path(basis) / naam
    if doel.exists():
        shutil.rmtree(doel)
    pst.PasConnector(name=naam, path=str(basis), verbose=False)
    open_map(doel)


def open_map(pad: str | Path) -> None:
    STORE.load_from_path(pad)
    invalidate_store(STORE.store_key)


def uit_zip(zip_pad: str | Path, basis: str | Path) -> None:
    """Open een zip: een ingepakte store-map of een export van pastastore."""
    basis = Path(basis)
    with zipfile.ZipFile(zip_pad) as z:
        beschrijvingen = [n for n in z.namelist() if n.endswith(".pastastore")]
        if beschrijvingen:
            beschrijving = beschrijvingen[0]
            voorvoegsel = beschrijving.rsplit("/", 1)[0] + "/" if "/" in beschrijving else ""
            doel = basis / Path(beschrijving).stem
            if doel.exists():
                shutil.rmtree(doel)
            for lid in z.infolist():
                if lid.is_dir() or not lid.filename.startswith(voorvoegsel):
                    continue
                uit = doel / lid.filename[len(voorvoegsel) :]
                uit.parent.mkdir(parents=True, exist_ok=True)
                uit.write_bytes(z.read(lid))
            open_map(doel)
            return
    naam = _nette_naam(Path(zip_pad).stem)
    if (basis / naam).exists():
        shutil.rmtree(basis / naam)
    conn = pst.PasConnector(name=naam, path=str(basis), verbose=False)
    pst.PastaStore.from_zip(str(zip_pad), conn=conn, progressbar=False)
    open_map(basis / naam)


def naar_zip(zip_pad: str | Path) -> None:
    """Schrijf het project als zip die pastastore en PastasDash v2 kunnen lezen."""
    STORE.pstore.to_zip(str(zip_pad), overwrite=True, progressbar=False)


def _zonder_none(meta: dict) -> dict:
    return {k: (math.nan if v is None else v) for k, v in meta.items()}


def voeg_put_toe(gmw: str) -> dict:
    """Haal een put uit de BRO en zet elk filter met metingen in het project."""
    uitkomst = bro.haal_put(gmw)
    toegevoegd, overgeslagen = [], []
    for f in uitkomst["filters"]:
        if f["reeks"].empty:
            overgeslagen.append({"naam": f["naam"], "reden": "; ".join(f["meldingen"])})
            continue
        STORE.pstore.add_oseries(
            f["reeks"].rename(f["naam"]), f["naam"], metadata=_zonder_none(f["meta"]), overwrite=True
        )
        toegevoegd.append(
            {
                "naam": f["naam"],
                "metingen": int(f["reeks"].size),
                "van": f["reeks"].index[0].date().isoformat(),
                "tot": f["reeks"].index[-1].date().isoformat(),
                "meldingen": f["meldingen"],
            }
        )
    invalidate_store(STORE.store_key)
    return {"put": gmw.strip().upper(), "toegevoegd": toegevoegd, "overgeslagen": overgeslagen}


def verwijder_put(naam: str) -> None:
    pstore = STORE.pstore
    if naam in pstore.model_names:
        pstore.del_models(naam, verbose=False)
    pstore.del_oseries(naam, verbose=False)
    invalidate_store(STORE.store_key)


def _of_none(waarde):
    """Waarde uit een tabel als gewoon Python-type; ontbrekend wordt None."""
    if hasattr(waarde, "item"):
        waarde = waarde.item()
    if waarde is None or (isinstance(waarde, float) and math.isnan(waarde)):
        return None
    return waarde


def toestand() -> dict:
    """Wat er in het project zit: putten, verklarende reeksen en modellen."""
    if not STORE.is_loaded:
        return {"geladen": False, "putten": [], "stresses": [], "modellen": []}
    df = STORE.oseries()
    modellen = set(STORE.model_names())
    putten = []
    for naam in sorted(df.index):
        rij = df.loc[naam]
        stats = timeseries_stats(STORE.store_key, naam)
        putten.append(
            {
                "naam": naam,
                "van": stats["tmin"],
                "tot": stats["tmax"],
                "metingen": stats["n_observations"],
                "lat": _of_none(rij.get("lat")),
                "lon": _of_none(rij.get("lon")),
                "maaiveld": _of_none(rij.get("ground_level")),
                "filter_boven": _of_none(rij.get("screen_top")),
                "filter_onder": _of_none(rij.get("screen_bottom")),
                "bro_id": _of_none(rij.get("bro_id")),
                "model": naam in modellen,
            }
        )
    stresses = [
        {"naam": naam, "soort": _of_none(rij.get("kind")), "station": _of_none(rij.get("station_naam"))}
        for naam, rij in STORE.pstore.stresses.iterrows()
    ]
    return {
        "geladen": True,
        "naam": STORE.display_name,
        "putten": putten,
        "stresses": stresses,
        "modellen": sorted(modellen),
    }


# ── afstemmen met de map op schijf ──────────────────────────────────────────
def _vingerafdrukken() -> dict[str, str]:
    wortel = STORE.source_path
    return {
        p.relative_to(wortel).as_posix(): hashlib.sha1(p.read_bytes()).hexdigest()
        for p in sorted(wortel.rglob("*"))
        if p.is_file()
    }


def schijf_is_gelijk() -> None:
    """De map op schijf bevat nu precies wat er in het geheugen staat."""
    _op_schijf.clear()
    if STORE.is_loaded:
        _op_schijf.update(_vingerafdrukken())


def schijf_is_leeg() -> None:
    """Er staat nog niets op schijf: alles moet nog weggeschreven worden."""
    _op_schijf.clear()


def gewijzigd() -> dict:
    """Bestanden die sinds de vorige aanroep veranderd of verdwenen zijn."""
    if not STORE.is_loaded:
        return {"wortel": None, "schrijf": [], "weg": []}
    nu = _vingerafdrukken()
    uit = {
        "wortel": STORE.source_path.as_posix(),
        "schrijf": [pad for pad, afdruk in nu.items() if _op_schijf.get(pad) != afdruk],
        "weg": [pad for pad in _op_schijf if pad not in nu],
    }
    _op_schijf.clear()
    _op_schijf.update(nu)
    return uit
