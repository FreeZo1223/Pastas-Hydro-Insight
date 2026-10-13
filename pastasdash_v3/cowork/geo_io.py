"""
Geodata inlezen zonder GDAL/geopandas: GeoJSON, GeoPackage, Shapefile, DXF.
Alles komt eruit als GeoJSON-achtige FeatureCollection met RD New-coordinaten
(EPSG:28992, meters), tenzij de bron aantoonbaar WGS84 is.

Puur standaardbibliotheek + (optioneel) numpy. Geen externe pakketten.
"""

import json
import math
import os
import struct
import sqlite3


# ---------------------------------------------------------------------------
# Coordinaattransformatie
# ---------------------------------------------------------------------------

# Officiele Kadaster-benaderingsformule (Schreutelkamp & Strang van Hees).
# De coefficienten leveren BOOGSECONDEN; de deling door 3600 is verplicht.
# Zonder die deling klopt alleen het nulpunt Amersfoort en loopt de rest van
# Nederland duizenden kilometers weg. Zie references/valkuilen.md.
_K = [(0, 1, 3235.65389), (2, 0, -32.58297), (0, 2, -0.24750), (2, 1, -0.84978),
      (0, 3, -0.06550), (2, 2, -0.01709), (1, 0, -0.00738), (4, 0, 0.00530),
      (2, 3, -0.00039), (4, 1, 0.00033), (1, 1, -0.00012)]
_L = [(1, 0, 5260.52916), (1, 1, 105.94684), (1, 2, 2.45656), (3, 0, -0.81885),
      (1, 3, 0.05594), (3, 1, -0.05607), (0, 1, 0.01199), (3, 2, -0.00256),
      (1, 4, 0.00128), (0, 2, 0.00022), (5, 0, -0.00022), (5, 1, 0.00026)]
_R = [(0, 1, 190094.945), (1, 1, -11832.228), (2, 1, -114.221), (0, 3, -32.391),
      (1, 0, -0.705), (3, 1, -2.340), (1, 3, -0.608), (0, 2, -0.008), (2, 3, 0.148)]
_S = [(1, 0, 309056.544), (0, 2, 3638.893), (2, 0, 73.077), (1, 2, -157.984),
      (3, 0, 59.788), (0, 1, 0.433), (2, 2, -6.439), (1, 1, -0.032),
      (0, 4, 0.092), (1, 4, -0.054)]


def rd_to_wgs84(x, y):
    """RD New (EPSG:28992) -> (lat, lon) WGS84. Nauwkeurig tot ~0,25 m in NL."""
    dx = (x - 155000.0) * 1e-5
    dy = (y - 463000.0) * 1e-5
    lat = 52.15517440 + sum(c * dx ** p * dy ** q for p, q, c in _K) / 3600.0
    lon = 5.38720621 + sum(c * dx ** p * dy ** q for p, q, c in _L) / 3600.0
    return lat, lon


def wgs84_to_rd(lat, lon):
    """(lat, lon) WGS84 -> RD New (EPSG:28992)."""
    df = (lat - 52.15517440) * 0.36
    dl = (lon - 5.38720621) * 0.36
    x = 155000.0 + sum(c * df ** p * dl ** q for p, q, c in _R)
    y = 463000.0 + sum(c * df ** p * dl ** q for p, q, c in _S)
    return x, y


def selftest_rd(verbose=False):
    """Heen-en-terug over heel Nederland. Geeft de grootste fout in meters.

    Draai dit als de transformatie ooit wordt aangepast: een fout groter dan
    een halve meter betekent dat er een coefficient of een deling mis is.
    """
    worst = 0.0
    for x in range(20000, 270001, 25000):
        for y in range(310000, 620001, 25000):
            lat, lon = rd_to_wgs84(x, y)
            x2, y2 = wgs84_to_rd(lat, lon)
            worst = max(worst, math.hypot(x2 - x, y2 - y))
    if verbose:
        print(f"RD-transformatie: grootste terugkeerfout {worst * 100:.2f} cm")
    return worst


def looks_like_wgs84(fc):
    """Ruwe check: liggen de coordinaten in graden in plaats van RD-meters?"""
    for x, y in _iter_coords(fc):
        return abs(x) <= 180 and abs(y) <= 90
    return False


def to_rd(fc):
    """Zet een FeatureCollection om naar RD als hij in graden staat."""
    if not looks_like_wgs84(fc):
        return fc
    def conv(c):
        if c and isinstance(c[0], (int, float)):
            x, y = wgs84_to_rd(c[1], c[0])
            return [x, y]
        return [conv(p) for p in c]
    for ft in fc["features"]:
        ft["geometry"]["coordinates"] = conv(ft["geometry"]["coordinates"])
    return fc


def _iter_coords(fc):
    def walk(c):
        if c and isinstance(c[0], (int, float)):
            yield c[0], c[1]
        else:
            for p in c:
                yield from walk(p)
    for ft in fc.get("features", []):
        g = ft.get("geometry") or {}
        if g.get("coordinates"):
            yield from walk(g["coordinates"])


def bounds(fc):
    """(minx, miny, maxx, maxy) van een FeatureCollection."""
    xs, ys = [], []
    for x, y in _iter_coords(fc):
        xs.append(x)
        ys.append(y)
    if not xs:
        raise ValueError("Geen coordinaten gevonden in de geodata.")
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------

def read_geojson(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        obj = json.load(fh)
    if obj.get("type") == "FeatureCollection":
        return obj
    if obj.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [obj]}
    return {"type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {}, "geometry": obj}]}


# ---------------------------------------------------------------------------
# GeoPackage (via sqlite3)
# ---------------------------------------------------------------------------

def gpkg_layers(path):
    """Lijst van (tabelnaam, geometrietype, srs_id) in een GeoPackage."""
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT c.table_name, g.geometry_type_name, g.srs_id "
            "FROM gpkg_contents c JOIN gpkg_geometry_columns g "
            "ON c.table_name = g.table_name WHERE c.data_type = 'features'"
        ).fetchall()
    finally:
        con.close()
    return rows


def read_gpkg(path, layer=None):
    con = sqlite3.connect(path)
    try:
        layers = gpkg_layers(path)
        if not layers:
            raise ValueError(f"Geen vectorlagen gevonden in {os.path.basename(path)}.")
        names = [r[0] for r in layers]
        if layer is None:
            layer = names[0]
        elif layer not in names:
            raise ValueError(f"Laag '{layer}' niet gevonden. Beschikbaar: {', '.join(names)}")
        srs = dict((r[0], r[2]) for r in layers)[layer]
        geom_col = con.execute(
            "SELECT column_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (layer,)).fetchone()[0]
        # De laagnaam is hierboven al getoetst aan gpkg_contents; SQLite kent
        # geen parameter voor een tabelnaam, dus quoten we hem expliciet.
        veilig = '"' + str(layer).replace('"', '""') + '"'
        cur = con.execute("SELECT * FROM " + veilig)  # nosec B608 - naam uit gpkg_contents
        cols = [d[0] for d in cur.description]
        gi = cols.index(geom_col)
        feats = []
        for row in cur:
            blob = row[gi]
            if blob is None:
                continue
            geom = _decode_gpkg_geom(blob)
            if geom is None:
                continue
            props = {c: row[i] for i, c in enumerate(cols)
                     if i != gi and not isinstance(row[i], (bytes, bytearray))}
            feats.append({"type": "Feature", "properties": props, "geometry": geom})
    finally:
        con.close()
    fc = {"type": "FeatureCollection", "features": feats,
          "_srs_id": srs, "_layer": layer}
    if srs == 4326:
        to_rd(fc)
    return fc


def _decode_gpkg_geom(blob):
    if blob[:2] != b"GP":
        return None
    flags = blob[3]
    env = (flags >> 1) & 0x07
    esize = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(env, 0)
    return _decode_wkb(blob[8 + esize:])


def _decode_wkb(buf, off=0):
    """WKB -> GeoJSON-geometrie.

    Ondersteunt 2D, Z, M en ZM (de Z/M-waarden worden overgeslagen) en
    GeometryCollection (WKB-type 7). Een GeoPackage uit QGIS bevat na een
    overlay- of clip-bewerking regelmatig GeometryCollections; een lezer die
    type 7 niet kent laat die objecten stilzwijgend vallen en levert een kaart
    met te weinig vlakken op. Zie references/valkuilen.md.
    """
    order = "<" if buf[off] == 1 else ">"
    gtype = struct.unpack_from(order + "I", buf, off + 1)[0]
    base = gtype % 1000
    dims = _wkb_dims(gtype)
    stap = 8 * dims
    off += 5

    def ring(o):
        n = struct.unpack_from(order + "I", buf, o)[0]
        o += 4
        pts = [list(struct.unpack_from(order + "dd", buf, o + stap * i)) for i in range(n)]
        return pts, o + stap * n

    if base == 1:
        return {"type": "Point", "coordinates": list(struct.unpack_from(order + "dd", buf, off))}
    if base == 2:
        pts, _ = ring(off)
        return {"type": "LineString", "coordinates": pts}
    if base == 3:
        nr = struct.unpack_from(order + "I", buf, off)[0]
        off += 4
        rings = []
        for _ in range(nr):
            pts, off = ring(off)
            rings.append(pts)
        return {"type": "Polygon", "coordinates": rings}
    if base in (4, 5, 6):
        n = struct.unpack_from(order + "I", buf, off)[0]
        off += 4
        parts = []
        for _ in range(n):
            sub = _decode_wkb(buf, off)
            if sub:
                parts.append(sub["coordinates"])
            off = _wkb_len(buf, off)
        return {"type": {4: "MultiPoint", 5: "MultiLineString", 6: "MultiPolygon"}[base],
                "coordinates": parts}
    if base == 7:
        n = struct.unpack_from(order + "I", buf, off)[0]
        off += 4
        geoms = []
        for _ in range(n):
            sub = _decode_wkb(buf, off)
            if sub:
                geoms.append(sub)
            off = _wkb_len(buf, off)
        return {"type": "GeometryCollection", "geometries": geoms} if geoms else None
    return None


def _wkb_dims(gtype):
    """Aantal ordinaten per punt: 2 (XY), 3 (XYZ / XYM) of 4 (XYZM)."""
    hoog = gtype // 1000
    if hoog == 3:
        return 4
    if hoog in (1, 2):
        return 3
    return 2


def _wkb_len(buf, off):
    """Byte-lengte van een WKB-geometrie; moet Z/M meetellen, anders loopt de
    leespositie in een Multi* of GeometryCollection uit de pas."""
    order = "<" if buf[off] == 1 else ">"
    gtype = struct.unpack_from(order + "I", buf, off + 1)[0]
    base = gtype % 1000
    stap = 8 * _wkb_dims(gtype)
    o = off + 5
    if base == 1:
        return o + stap
    if base == 2:
        n = struct.unpack_from(order + "I", buf, o)[0]
        return o + 4 + stap * n
    if base == 3:
        nr = struct.unpack_from(order + "I", buf, o)[0]
        o += 4
        for _ in range(nr):
            n = struct.unpack_from(order + "I", buf, o)[0]
            o += 4 + stap * n
        return o
    n = struct.unpack_from(order + "I", buf, o)[0]
    o += 4
    for _ in range(n):
        o = _wkb_len(buf, o)
    return o


# ---------------------------------------------------------------------------
# Shapefile (.shp + .dbf)
# ---------------------------------------------------------------------------

def read_shapefile(path):
    base = path[:-4] if path.lower().endswith(".shp") else path
    with open(base + ".shp", "rb") as fh:
        buf = fh.read()
    feats, off, n = [], 100, len(buf)
    while off < n:
        _, clen = struct.unpack_from(">II", buf, off)
        rec = off + 8
        stype = struct.unpack_from("<I", buf, rec)[0]
        geom = _shp_geom(buf, rec, stype)
        if geom:
            feats.append({"type": "Feature", "properties": {}, "geometry": geom})
        off = rec + clen * 2
    attrs = _read_dbf(base + ".dbf") if os.path.exists(base + ".dbf") else []
    for i, ft in enumerate(feats):
        if i < len(attrs):
            ft["properties"] = attrs[i]
    fc = {"type": "FeatureCollection", "features": feats}
    prj = base + ".prj"
    if os.path.exists(prj):
        txt = open(prj, "r", errors="replace").read()
        fc["_prj"] = txt.strip()[:200]
        if "GEOGCS" in txt and "PROJCS" not in txt:
            to_rd(fc)
    return fc


def _shp_geom(buf, rec, stype):
    if stype == 1:
        return {"type": "Point", "coordinates": list(struct.unpack_from("<dd", buf, rec + 4))}
    if stype in (3, 5):
        nparts, npts = struct.unpack_from("<II", buf, rec + 36)
        po = rec + 44
        parts = list(struct.unpack_from("<%dI" % nparts, buf, po))
        co = po + 4 * nparts
        pts = [list(struct.unpack_from("<dd", buf, co + 16 * i)) for i in range(npts)]
        rings = [pts[parts[i]:(parts[i + 1] if i + 1 < nparts else npts)]
                 for i in range(nparts)]
        if stype == 5:
            return ({"type": "Polygon", "coordinates": rings} if nparts == 1
                    else {"type": "MultiPolygon", "coordinates": [[r] for r in rings]})
        return ({"type": "LineString", "coordinates": rings[0]} if nparts == 1
                else {"type": "MultiLineString", "coordinates": rings})
    return None


def _read_dbf(path):
    with open(path, "rb") as fh:
        buf = fh.read()
    nrec, hlen, rlen = struct.unpack_from("<IHH", buf, 4)
    fields, off = [], 32
    while buf[off] != 0x0D:
        name = buf[off:off + 11].split(b"\0")[0].decode("latin-1").strip()
        ftype = chr(buf[off + 11])
        flen = buf[off + 16]
        fields.append((name, ftype, flen))
        off += 32
    rows = []
    for r in range(nrec):
        o = hlen + r * rlen + 1
        rec = {}
        for name, ftype, flen in fields:
            raw = buf[o:o + flen].decode("latin-1").strip()
            o += flen
            if ftype in "NF" and raw:
                try:
                    rec[name] = float(raw) if "." in raw else int(raw)
                except ValueError:
                    rec[name] = raw
            else:
                rec[name] = raw
        rows.append(rec)
    return rows


# ---------------------------------------------------------------------------
# DXF (ASCII)
# ---------------------------------------------------------------------------

def read_dxf(path, arc_segment_deg=2.0):
    """ASCII-DXF -> FeatureCollection. CAD-layer blijft bewaard als attribuut.

    Beperkingen: alleen ASCII-DXF (geen binaire DXF, geen .dwg), blokken
    (INSERT) worden een punt met de bloknaam, hatches/splines/dimensies
    worden overgeslagen. DXF bevat geen coordinaatstelsel -- de aanname is
    RD New, tenzij de collega anders zegt.
    """
    raw = open(path, "r", errors="replace").read().splitlines()
    pairs = []
    for i in range(0, len(raw) - 1, 2):
        try:
            pairs.append((int(raw[i].strip()), raw[i + 1].strip()))
        except ValueError:
            continue

    def arc(cx, cy, r, a0, a1):
        if a1 < a0:
            a1 += 360
        n = max(2, int((a1 - a0) / arc_segment_deg))
        return [[cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
                 cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))]
                for i in range(n + 1)]

    want = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
            "TEXT", "MTEXT", "POINT", "INSERT"}
    feats, cur, sec = [], None, None

    def flush():
        nonlocal cur
        if not cur:
            return
        t = cur["type"]
        props = {"layer": cur.get(8, "0"), "dxftype": t}
        geom = None
        if t == "LINE" and 11 in cur:
            geom = {"type": "LineString",
                    "coordinates": [[cur[10], cur[20]], [cur[11], cur[21]]]}
        elif t in ("LWPOLYLINE", "POLYLINE"):
            pts = cur["verts"]
            if cur.get(70, 0) & 1 and len(pts) > 2:
                geom = {"type": "Polygon", "coordinates": [pts + [pts[0]]]}
            elif len(pts) > 1:
                geom = {"type": "LineString", "coordinates": pts}
        elif t == "CIRCLE":
            geom = {"type": "Polygon", "coordinates": [arc(cur[10], cur[20], cur[40], 0, 360)]}
        elif t == "ARC":
            geom = {"type": "LineString",
                    "coordinates": arc(cur[10], cur[20], cur[40],
                                       cur.get(50, 0), cur.get(51, 360))}
        elif t in ("TEXT", "MTEXT"):
            props["text"] = cur.get(1, "")
            geom = {"type": "Point", "coordinates": [cur[10], cur[20]]}
        elif t in ("POINT", "INSERT"):
            props["blockname"] = cur.get(2, "")
            geom = {"type": "Point", "coordinates": [cur[10], cur[20]]}
        if geom:
            feats.append({"type": "Feature", "properties": props, "geometry": geom})
        cur = None

    for code, val in pairs:
        if code == 2 and val in ("ENTITIES", "HEADER", "BLOCKS", "TABLES", "OBJECTS"):
            sec = val
            continue
        if code == 0:
            if val == "VERTEX" and cur and cur["type"] == "POLYLINE":
                continue
            if val == "SEQEND":
                continue
            flush()
            if sec == "ENTITIES" and val in want:
                cur = {"type": val, "verts": []}
            continue
        if cur is None:
            continue
        if code in (10, 11, 20, 21, 40, 50, 51, 70, 90):
            try:
                v = float(val)
            except ValueError:
                continue
            if code in (70, 90):
                v = int(v)
            if code == 10 and cur["type"] in ("LWPOLYLINE", "POLYLINE"):
                cur["_px"] = v
            elif code == 20 and cur["type"] in ("LWPOLYLINE", "POLYLINE") and "_px" in cur:
                cur["verts"].append([cur.pop("_px"), v])
            cur[code] = v
        elif code in (1, 2, 8):
            cur[code] = val
    flush()
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def read_any(path, layer=None):
    """Leest elk ondersteund formaat en geeft RD-coordinaten terug."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".geojson", ".json"):
        fc = read_geojson(path)
        to_rd(fc)
    elif ext == ".gpkg":
        fc = read_gpkg(path, layer)
    elif ext in (".shp", ".dbf"):
        fc = read_shapefile(path)
    elif ext == ".dxf":
        fc = read_dxf(path)
    else:
        raise ValueError(
            f"Formaat '{ext}' wordt niet ondersteund. "
            "Ondersteund: .geojson, .gpkg, .shp, .dxf. "
            "Een .dwg of File Geodatabase eerst in QGIS exporteren naar GeoPackage."
        )
    if not fc["features"]:
        raise ValueError(f"{os.path.basename(path)} bevat geen bruikbare geometrie.")
    normaliseer(fc)
    return fc


def read_alle_lagen(path, veld="laag"):
    """Leest ALLE lagen van een GeoPackage in een dict {laagnaam: FeatureCollection}.

    Elke feature krijgt de laagnaam in `properties[veld]`, zodat een viewer of
    kaartblad per laag kan symboliseren. Voor de overige formaten is er maar
    een laag; die krijgt de bestandsnaam.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext != ".gpkg":
        naam = os.path.splitext(os.path.basename(path))[0]
        fc = read_any(path)
        for ft in fc["features"]:
            ft.setdefault("properties", {})[veld] = naam
        return {naam: fc}
    uit = {}
    for naam, _gt, _srs in gpkg_layers(path):
        fc = read_any(path, naam)
        for ft in fc["features"]:
            ft.setdefault("properties", {})[veld] = naam
        uit[naam] = fc
    if not uit:
        raise ValueError(f"Geen vectorlagen gevonden in {os.path.basename(path)}.")
    return uit


# ---------------------------------------------------------------------------
# Normaliseren en vereenvoudigen
# ---------------------------------------------------------------------------

_MULTI = {"Point": "MultiPoint", "LineString": "MultiLineString",
          "Polygon": "MultiPolygon"}


def normaliseer(fc):
    """Vlakt GeometryCollections uit tot een enkelvoudig Multi*-type.

    Downstream (SVG-paden, QGIS-symbology, Leaflet-stijl) verwacht een
    homogeen geometrietype. Een GeometryCollection met vlakken en losse lijnen
    houdt alleen het dominante type over; dat wordt gemeld via het aantal
    weggelaten delen, nooit stilzwijgend.
    """
    weg = 0
    for ft in fc.get("features", []):
        g = ft.get("geometry") or {}
        if g.get("type") != "GeometryCollection":
            continue
        delen = {"Polygon": [], "LineString": [], "Point": []}
        _verzamel(g, delen)
        for soort in ("Polygon", "LineString", "Point"):
            if delen[soort]:
                andere = sum(len(delen[s]) for s in delen if s != soort)
                weg += andere
                ft["geometry"] = {"type": _MULTI[soort], "coordinates": delen[soort]}
                break
        else:
            ft["geometry"] = None
    fc["features"] = [f for f in fc["features"] if f.get("geometry")]
    if weg:
        fc["_genegeerde_delen"] = weg
    return fc


def _verzamel(g, delen):
    t = g.get("type")
    if t == "GeometryCollection":
        for sub in g.get("geometries", []):
            _verzamel(sub, delen)
    elif t in delen:
        delen[t].append(g["coordinates"])
    elif t == "MultiPolygon":
        delen["Polygon"].extend(g["coordinates"])
    elif t == "MultiLineString":
        delen["LineString"].extend(g["coordinates"])
    elif t == "MultiPoint":
        delen["Point"].extend(g["coordinates"])


def vereenvoudig(fc, tolerantie_m, min_opp_m2=0.0):
    """Douglas-Peucker in meters (RD), plus het weglaten van snippers.

    Bedoeld om een browser-viewer werkbaar te houden. Geeft een dict terug met
    het aantal punten voor en na, zodat de skill dat eerlijk kan melden.
    Gebruik dit NOOIT voor oppervlakteberekeningen -- vereenvoudigde randen
    veranderen de oppervlakte.
    """
    voor = sum(1 for _ in _iter_coords(fc))
    for ft in fc.get("features", []):
        g = ft.get("geometry")
        if g:
            ft["geometry"] = _vereenvoudig_geom(g, tolerantie_m, min_opp_m2)
    fc["features"] = [f for f in fc["features"] if f.get("geometry")]
    na = sum(1 for _ in _iter_coords(fc))
    return {"punten_voor": voor, "punten_na": na, "tolerantie_m": tolerantie_m}


def _vereenvoudig_geom(g, tol, min_opp):
    t = g["type"]
    c = g["coordinates"]
    if t == "Point":
        return g
    if t == "MultiPoint":
        return g
    if t == "LineString":
        p = _dp(c, tol)
        return {"type": t, "coordinates": p} if len(p) > 1 else None
    if t == "MultiLineString":
        ls = [p for p in (_dp(l, tol) for l in c) if len(p) > 1]
        return {"type": t, "coordinates": ls} if ls else None
    if t == "Polygon":
        p = _vereenvoudig_poly(c, tol, min_opp)
        return {"type": t, "coordinates": p} if p else None
    if t == "MultiPolygon":
        ps = [p for p in (_vereenvoudig_poly(q, tol, min_opp) for q in c) if p]
        return {"type": t, "coordinates": ps} if ps else None
    return g


def _vereenvoudig_poly(rings, tol, min_opp):
    uit = []
    for i, r in enumerate(rings):
        rr = _dp(r, tol)
        if len(rr) < 4:
            if i == 0:
                return None
            continue
        if rr[0] != rr[-1]:
            rr.append(rr[0])
        if _ringopp(rr) < min_opp:
            if i == 0:
                return None
            continue
        uit.append(rr)
    return uit or None


def _ringopp(ring):
    s = 0.0
    for i in range(len(ring) - 1):
        s += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(s) / 2.0


def _dp(pts, tol):
    """Douglas-Peucker, iteratief (recursie loopt stuk op lange BGT-randen)."""
    if len(pts) < 3 or tol <= 0:
        return list(pts)
    houd = [False] * len(pts)
    houd[0] = houd[-1] = True
    stapel = [(0, len(pts) - 1)]
    while stapel:
        a, b = stapel.pop()
        ax, ay = pts[a][0], pts[a][1]
        bx, by = pts[b][0], pts[b][1]
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        idx, dmax = -1, tol
        for i in range(a + 1, b):
            px, py = pts[i][0], pts[i][1]
            if d2 == 0:
                afst = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
                afst = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if afst > dmax:
                idx, dmax = i, afst
        if idx > 0:
            houd[idx] = True
            stapel.append((a, idx))
            stapel.append((idx, b))
    return [p for p, k in zip(pts, houd) if k]
