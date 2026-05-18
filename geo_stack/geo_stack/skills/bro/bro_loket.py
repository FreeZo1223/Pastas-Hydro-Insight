"""Parser voor BRO Loket ZIP-exports (publiek.broservices.nl).

Een BRO Loket-export bevat per geselecteerde GMW:
- ``BRO_Grondwatermonitoring/BRO_Grondwatermonitoringput/<gmw_id>/<gmw_id>.xml``
  — peilbuis-metadata (coördinaten, maaiveld, filterdiepten)
- ``BRO_Grondwatermonitoring/BRO_Grondwatermonitoringput/<gmw_id>/<gld_id>-full.csv``
  — tijdreeks per filter (uurwaarden of meetregistraties, multi-sectie)

Plus ``locatie_levering.kml`` met de gebiedsselectie.

Dit module-pakket leest de ZIP en geeft een lijst met geparseerde peilbuizen
terug. Een aparte CLI-tool (`lesa-bro-loket-to-pastastore`) bouwt daaruit een
volledige PastaStore inclusief KNMI-stresses, klaar voor pastasdash-upload.
"""

from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

log = logging.getLogger(__name__)


NS = {
    "brocom": "http://www.broservices.nl/xsd/brocommon/3.0",
    "gmwcommon": "http://www.broservices.nl/xsd/gmwcommon/1.1",
    "gml": "http://www.opengis.net/gml/3.2",
    "gmw": "http://www.broservices.nl/xsd/dsgmw/1.1",
}


@dataclass
class TubeMeta:
    tube_nr: int
    screen_top: float | None = None
    screen_bottom: float | None = None
    tube_top: float | None = None


@dataclass
class GmwRecord:
    gmw_id: str
    x: float | None = None
    y: float | None = None
    ground_level: float | None = None
    well_code: str | None = None
    nitg_code: str | None = None
    tubes: dict[int, TubeMeta] = field(default_factory=dict)
    gld_csvs: list[tuple[str, str]] = field(default_factory=list)  # (gld_id, raw_csv_text)


# ── XML parsing ──────────────────────────────────────────────────────────────

def _parse_gmw_xml(xml_text: str) -> GmwRecord:
    """Parse een GMW XML-bestand naar een :class:`GmwRecord`."""
    root = ET.fromstring(xml_text)
    gmw_id_el = root.find(".//brocom:broId", NS)
    gmw_id = gmw_id_el.text.strip() if gmw_id_el is not None and gmw_id_el.text else ""
    rec = GmwRecord(gmw_id=gmw_id)

    well_code_el = root.find(".//gmw:wellCode", NS)
    if well_code_el is not None and well_code_el.text:
        rec.well_code = well_code_el.text.strip()
    nitg_el = root.find(".//gmw:nitgCode", NS)
    if nitg_el is not None and nitg_el.text:
        rec.nitg_code = nitg_el.text.strip()

    pos = root.find(".//gmwcommon:location/gml:pos", NS)
    if pos is not None and pos.text:
        try:
            x_s, y_s = pos.text.strip().split()[:2]
            rec.x, rec.y = float(x_s), float(y_s)
        except ValueError:
            log.warning("Onparsbare locatie in %s: %r", gmw_id, pos.text)

    glp = root.find(".//gmwcommon:groundLevelPosition", NS)
    if glp is not None and glp.text:
        try:
            rec.ground_level = float(glp.text)
        except ValueError:
            pass

    # Filters / tubes
    for tube_el in root.findall(".//gmw:monitoringTube", NS):
        nr_el = tube_el.find("gmw:tubeNumber", NS)
        if nr_el is None or not nr_el.text:
            continue
        try:
            tube_nr = int(nr_el.text)
        except ValueError:
            continue
        tube = TubeMeta(tube_nr=tube_nr)
        tt_el = tube_el.find("gmw:tubeTopPosition", NS)
        if tt_el is not None and tt_el.text:
            try:
                tube.tube_top = float(tt_el.text)
            except ValueError:
                pass
        st_el = tube_el.find(".//gmw:screenTopPosition", NS)
        sb_el = tube_el.find(".//gmw:screenBottomPosition", NS)
        if st_el is not None and st_el.text:
            try:
                tube.screen_top = float(st_el.text)
            except ValueError:
                pass
        if sb_el is not None and sb_el.text:
            try:
                tube.screen_bottom = float(sb_el.text)
            except ValueError:
                pass
        rec.tubes[tube_nr] = tube

    return rec


# ── GLD CSV parsing ──────────────────────────────────────────────────────────

_TUBE_LINE_RE = re.compile(r'^"(?P<gmw>GMW\d+)","(?P<tube>\d+)"')
_DATA_HEADER = '"tijdstip meting","waterstand"'


def parse_gld_csv(csv_text: str) -> tuple["pd.Series", int | None]:
    """Parse een BRO Loket GLD-full CSV naar (Series, tube_nr).

    Het bestand bevat een GMW/tube-header, gevolgd door blokken observaties
    met telkens een header-regel ``"tijdstip meting","waterstand",...``
    en daaronder de meetwaarden. Wij concateneren alle data-regels, parsen
    de tijden naar UTC en sorteren chronologisch.
    """
    import pandas as pd

    tube_nr: int | None = None
    data_rows: list[tuple[str, str]] = []  # (datetime_iso, waterstand)
    in_data = False
    for raw in csv_text.splitlines():
        line = raw.strip()
        if not line:
            in_data = False
            continue
        if line.startswith(_DATA_HEADER):
            in_data = True
            continue
        m = _TUBE_LINE_RE.match(line)
        if m:
            try:
                tube_nr = int(m.group("tube"))
            except ValueError:
                tube_nr = None
            continue
        if not in_data:
            continue
        # Data-regel: split op komma, neem eerste twee gequote velden
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        data_rows.append((parts[0], parts[1]))

    if not data_rows:
        return pd.Series(dtype=float), tube_nr

    df = pd.DataFrame(data_rows, columns=["t", "v"])
    df["t"] = pd.to_datetime(df["t"], utc=True, errors="coerce")
    df["v"] = pd.to_numeric(df["v"], errors="coerce")
    df = df.dropna()
    s = df.set_index("t")["v"].sort_index()
    s.index = s.index.tz_convert("Europe/Amsterdam").tz_localize(None)
    return s, tube_nr


# ── ZIP parsing ──────────────────────────────────────────────────────────────

def parse_bro_loket_zip(zip_path: Path | str) -> list[GmwRecord]:
    """Parse een BRO Loket ZIP-export naar GmwRecords met gld_csvs ingelezen.

    Parameters
    ----------
    zip_path
        Pad naar de BRO Loket export-ZIP (bevat ``BRO_Grondwatermonitoring/``).

    Returns
    -------
    list[GmwRecord]
        Eén record per GMW. ``gld_csvs`` bevat ruwe CSV-tekst — gebruik
        :func:`parse_gld_csv` om er Series van te maken.
    """
    records: dict[str, GmwRecord] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            # GMW XML's heten /<gmw_id>/<gmw_id>.xml ergens in de boom
            base = Path(name).name
            if name.endswith(".xml") and base.startswith("GMW"):
                xml_text = zf.read(name).decode("utf-8", errors="replace")
                try:
                    rec = _parse_gmw_xml(xml_text)
                except ET.ParseError as exc:
                    log.warning("XML-parse faalde voor %s: %s", name, exc)
                    continue
                if rec.gmw_id:
                    records[rec.gmw_id] = rec

        for name in zf.namelist():
            if not name.endswith("-full.csv"):
                continue
            # Pad: .../GMW000000029827/GLD000000008961-full.csv
            parts = name.split("/")
            gmw_id = next((p for p in parts if p.startswith("GMW")), None)
            if gmw_id is None:
                continue
            gld_id = Path(name).stem.replace("-full", "")
            csv_text = zf.read(name).decode("utf-8", errors="replace")
            rec = records.setdefault(gmw_id, GmwRecord(gmw_id=gmw_id))
            rec.gld_csvs.append((gld_id, csv_text))

    return list(records.values())


def daily_mean(series: "pd.Series") -> "pd.Series":
    """Resample een uurreeks naar dagelijkse gemiddelden (PASTAS-vriendelijk)."""
    import pandas as pd

    if series.empty:
        return series
    daily = series.resample("D").mean().dropna()
    daily.index.name = "Datum"
    return daily
