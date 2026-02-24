import hydropandas as hpd
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

bro_id = "GMW000000069526"

try:
    print(f"Fetching BRO data for {bro_id}...")
    obs = hpd.GroundwaterObs.from_bro(bro_id, tube_nr=1)
    print(f"Success! Data length: {len(obs)}")
    print("Metadata:")
    for k, v in obs.metadata.items():
        print(f"  {k}: {v}")
    
    x = obs.metadata.get("x")
    y = obs.metadata.get("y")
    print(f"Coordinates (RD): x={x}, y={y}")
    
    if x and y:
        import hydropandas.io.knmi as hpd_knmi
        stations = hpd_knmi.get_stations(meteo_var='RH')
        print(f"Found {len(stations)} KNMI stations.")
        # Logic from stresses.py
        import numpy as np
        stations["dist"] = np.sqrt((stations["x"] - x)**2 + (stations["y"] - y)**2)
        nearest = stations.sort_values("dist").head(3)
        print("Nearest stations:")
        print(nearest[["name", "x", "y", "dist"]])
    else:
        print("FAILED: No coordinates found in metadata.")

except Exception as e:
    print(f"ERROR: {e}")
