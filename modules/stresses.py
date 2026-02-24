import hydropandas as hpd
import streamlit as st
import pandas as pd
import numpy as np
import hydropandas.io.knmi as hpd_knmi

def get_nearest_knmi_stations(coords_rd, n=3):
    """
    Finds the n nearest KNMI stations for given RD coordinates.
    """
    try:
        # Get all KNMI stations for precipitation (RH)
        stations = hpd_knmi.get_stations(meteo_var='RH')
        
        # Add index as a column for easier use in Streamlit
        stations["stn"] = stations.index
        
        # Calculate distance (Euclidean in RD is fine for short distances)
        x, y = coords_rd
        stations["dist"] = np.sqrt((stations["x"] - x)**2 + (stations["y"] - y)**2)
        
        # Sort and return top n
        nearest = stations.sort_values("dist").head(n)
        return nearest
    except Exception as e:
        st.error(f"Fout bij ophalen KNMI stations: {e}")
        return pd.DataFrame()

def fetch_knmi_data(stn_code, start_date, end_date, variable="RH"):
    """
    Fetches KNMI data for a specific station and variable.
    RH = Precipitation, EV24 = Evaporation
    """
    try:
        stn = int(stn_code)
        # read_knmi returns an ObsCollection
        oc = hpd.read_knmi(stns=[stn], meteo_vars=[variable], starts=start_date, ends=end_date)
        
        if oc.empty:
            return None
            
        # Extract the observation object
        obs = oc.obs.iloc[0]
        
        # Return only the values as a Series (Pastas requirement)
        # obs.iloc[:, 0] gets the actual data column (RH or EV24)
        series = obs.iloc[:, 0]
        return series
    except Exception as e:
        st.error(f"Fout bij ophalen KNMI data ({variable}): {e}")
        return None
