import pandas as pd
import geopandas as gpd
import os

# Configuration
INPUT_GPKG = r'C:\GIS_Projecten\ArcGIS_online\data\outputs\Gierzwaluwen_StichtseVecht.gpkg'
OUTPUT_EXCEL = r'C:\GIS_Projecten\ArcGIS_online\data\outputs\Gierzwaluwen_StichtseVecht_External_v3.xlsx'

def main():
    if not os.path.exists(INPUT_GPKG):
        print(f"Error: Input file {INPUT_GPKG} not found.")
        return

    print(f"Loading data from {INPUT_GPKG}...")
    gdf = gpd.read_file(INPUT_GPKG)
    
    if gdf.empty:
        print("Dataset is empty.")
        return

    # 1. Transform CRS to WGS84 (EPSG:4326)
    print("Transforming coordinates to WGS84...")
    gdf_wgs84 = gdf.to_crs("EPSG:4326")

    # 2. Extract Latitude and Longitude
    # We want format "Lat, Lon" or similar. User example: "51.97742, 5.64724"
    gdf_wgs84['lat'] = gdf_wgs84.geometry.y.round(5)
    gdf_wgs84['lon'] = gdf_wgs84.geometry.x.round(5)
    gdf_wgs84['Coördinaten'] = gdf_wgs84.apply(lambda row: f"{row['lat']}, {row['lon']}", axis=1)

    # 3. Handle Dates
    # Format "1-6-2025" and extract year
    if 'Datum' in gdf.columns:
        gdf_wgs84['Datum_parsed'] = pd.to_datetime(gdf_wgs84['Datum'])
        gdf_wgs84['Datum waarneming'] = gdf_wgs84['Datum_parsed'].dt.strftime('%d-%m-%Y')
        gdf_wgs84['Jaar aanwezigheid vastgesteld'] = gdf_wgs84['Datum_parsed'].dt.year
        # Add requested "data" column
        gdf_wgs84['data'] = gdf_wgs84['Datum_parsed'].dt.strftime('%d-%m-%Y')
    else:
        gdf_wgs84['Datum waarneming'] = ""
        gdf_wgs84['Jaar aanwezigheid vastgesteld'] = ""
        gdf_wgs84['data'] = ""

    # 4. Map other fields
    field_mapping = {
        'Soort': 'Soort',
        'Aantal': 'Aantal dieren',
        'Gedrag': 'Waargenomen gedrag (In- en uit vliegend enz)'
    }
    
    for src, tgt in field_mapping.items():
        if src in gdf.columns:
            gdf_wgs84[tgt] = gdf[src]
        else:
            gdf_wgs84[tgt] = ""

    # 5. Add static/empty requested columns
    other_cols = [
        'Straat', 'Plaats', 'Huisnummer', 'Aantal nesten', 
        'Ligging (Voor/Achter/Zijkant)', 'Soort verblijfplaats (Spouwmuur, Kantpannen enz)',
        'Bedrijf dat verplaatsen aanlevert', 'Contactpersoon', 'Opmerkingen'
    ]
    for col in other_cols:
        gdf_wgs84[col] = ""

    # 6. Select and Order Columns
    final_columns = [
        'Coördinaten', 'Straat', 'Plaats', 'Huisnummer', 'Datum waarneming',
        'Jaar aanwezigheid vastgesteld', 'Soort', 'Aantal nesten', 'Aantal dieren',
        'Waargenomen gedrag (In- en uit vliegend enz)', 'Ligging (Voor/Achter/Zijkant)',
        'Soort verblijfplaats (Spouwmuur, Kantpannen enz)', 'Bedrijf dat verplaatsen aanlevert',
        'Contactpersoon', 'Opmerkingen', 'data'
    ]
    
    # Filter for existing columns only in case mapping missed something
    final_columns = [c for c in final_columns if c in gdf_wgs84.columns]
    df_export = gdf_wgs84[final_columns].copy()

    # 7. Save to Excel
    print(f"Saving to {OUTPUT_EXCEL}...")
    df_export.to_excel(OUTPUT_EXCEL, index=False)
    print("Export complete!")

if __name__ == "__main__":
    main()
