import os
import json
import duckdb
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from owslib.wfs import WebFeatureService

# Configuration
DUCKDB_PATH = r'C:\GIS_Projecten\ArcGIS_online\data\ewaarnemingen.duckdb'
OUTPUT_DIR  = r'C:\GIS_Projecten\ArcGIS_online\data\outputs'
OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'Gierzwaluwen_StichtseVecht.gpkg')
MUNICIPALITY_NAME = 'Stichtse Vecht'

def get_municipality_boundary(name):
    print(f"Fetching boundary for {name}...")
    wfs_url = "https://service.pdok.nl/kadaster/bestuurlijkegebieden/wfs/v1_0"
    wfs = WebFeatureService(url=wfs_url, version='2.0.0')
    response = wfs.getfeature(typename='bestuurlijkegebieden:Gemeentegebied',
                              outputFormat='application/json')
    gdf_all = gpd.read_file(response)
    gdf = gdf_all[gdf_all['naam'] == name]
    if gdf.empty and 'gemeentenaam' in gdf_all.columns:
        gdf = gdf_all[gdf_all['gemeentenaam'] == name]
    if gdf.empty:
        raise ValueError(f"Could not find municipality: {name}")
    print(f"Boundary found for {name}. Area: {gdf.geometry.area.sum() / 1e6:.2f} km2")
    return gdf.dissolve()

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 1. Gemeentegrens ophalen
    try:
        boundary_gdf = get_municipality_boundary(MUNICIPALITY_NAME)
        print("Boundary fetched successfully.")
    except Exception as e:
        print(f"Error fetching boundary: {e}")
        return

    # 2. Gierzwaluw uit DuckDB lezen
    # DuckDB heeft datum_beste (beste datum uit AGOL + parquet combinatie)
    # en geometry als GeoJSON blob (WGS84/EPSG:4326)
    print(f"Loading Gierzwaluwen from DuckDB: {DUCKDB_PATH}")
    con = duckdb.connect(DUCKDB_PATH, read_only=True)

    df = con.execute("""
        SELECT
            object_id     AS OBJECTID,
            soort         AS Soort,
            gedrag        AS Gedrag,
            geslacht      AS Geslacht,
            telmethode    AS Telmethode,
            waarnemer     AS Waarnemer,
            aantal        AS Aantal,
            opmerking     AS Opmerking,
            datum_beste   AS Datum,
            datum_bron    AS Datum_bron,
            global_id     AS GlobalID,
            creation_date AS CreationDate,
            ingevoerd_datum AS Ingevoerd_datum,
            stadium,
            geometry
        FROM waarnemingen_vogels
        WHERE soort = 'Gierzwaluw'
    """).df()
    con.close()

    print(f"Found {len(df)} Gierzwaluwen in total.")
    datum_ok = df['Datum'].notna().sum()
    print(f"Datum ingevuld: {datum_ok}/{len(df)} ({datum_ok/len(df)*100:.0f}%)")

    if df.empty:
        print("No Gierzwaluwen found.")
        return

    # 3. Geometry parsen — DuckDB slaat geometry op als GeoJSON string/blob
    print("Parsing geometry...")
    def parse_geojson(val):
        if val is None:
            return None
        try:
            if isinstance(val, (bytes, bytearray)):
                val = val.decode("utf-8")
            return shape(json.loads(val))
        except Exception:
            return None

    df['geometry'] = df['geometry'].apply(parse_geojson)
    gdf_birds = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
    valid = gdf_birds['geometry'].notna().sum()
    print(f"Geometry geldig: {valid}/{len(gdf_birds)}")

    # 4. Spatial clip naar gemeente
    print(f"Clipping to {MUNICIPALITY_NAME}...")
    if gdf_birds.crs != boundary_gdf.crs:
        boundary_gdf = boundary_gdf.to_crs(gdf_birds.crs)

    gdf_filtered = gpd.clip(gdf_birds, boundary_gdf)
    print(f"Found {len(gdf_filtered)} Gierzwaluwen within {MUNICIPALITY_NAME}.")

    if not gdf_filtered.empty:
        datum_filled = gdf_filtered['Datum'].notna().sum()
        print(f"Datum ingevuld in subset: {datum_filled}/{len(gdf_filtered)}")
        print(f"Saving to {OUTPUT_FILE}...")
        gdf_filtered.to_file(OUTPUT_FILE, driver="GPKG")
        print("Done!")
    else:
        print("No observations found within the municipality.")

if __name__ == "__main__":
    main()
