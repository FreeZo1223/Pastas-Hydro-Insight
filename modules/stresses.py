import hydropandas as hpd
import streamlit as st
import pandas as pd
import numpy as np
import hydropandas.io.knmi as hpd_knmi
import logging

logger = logging.getLogger("PastasHydroInsight")

@st.cache_data(show_spinner=False)
def get_nearest_knmi_stations(coords_rd, n=3):
    """
    Finds the n nearest KNMI stations for given RD coordinates.
    """
    try:
        if coords_rd == (0, 0):
            return pd.DataFrame()

        # Get all KNMI stations for precipitation (RH)
        stations = hpd_knmi.get_stations(meteo_var='RH')
        
        if stations.empty:
            return pd.DataFrame()

        # Add index as a column for easier use in Streamlit
        stations["stn"] = stations.index
        
        # Calculate distance (Euclidean in RD is fine for short distances)
        x, y = coords_rd
        stations["dist"] = np.sqrt((stations["x"] - x)**2 + (stations["y"] - y)**2)
        
        # Sort and return top n
        nearest = stations.sort_values("dist").head(n)
        return nearest
    except Exception as e:
        logger.error(f"Fout bij ophalen KNMI stations: {e}")
        return pd.DataFrame()

@st.cache_data(show_spinner=False)
def fetch_knmi_data(stn_code, start_date, end_date, variable="RH"):
    """
    Fetches KNMI data for a specific station and variable.
    RH = Precipitation, EV24 = Evaporation
    """
    try:
        stn = int(stn_code)
        # Ensure dates are timestamps
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        
        # read_knmi returns an ObsCollection
        oc = hpd.read_knmi(stns=[stn], meteo_vars=[variable], starts=start, ends=end)
        
        if oc.empty:
            logger.warning(f"Geen KNMI data gevonden voor station {stn} ({variable}) tussen {start} en {end}")
            return None
            
        # Extract the observation object
        obs = oc.obs.iloc[0]
        
        # Return only the values as a Series (Pastas requirement)
        series = obs.iloc[:, 0]
        
        # Fix: Pastas stressors must be regular and have no NaNs
        # 1. Ensure daily frequency
        series = series.asfreq("D")
        
        # 2. Fill small gaps with interpolation, larger ones with 0 for RH or mean for EV
        if series.isna().any():
            logger.info(f"Filling gaps in {variable} data for station {stn}")
            if variable == "RH":
                series = series.fillna(0.0)
            else:
                series = series.interpolate(method="linear").fillna(method="bfill").fillna(method="ffill")
        
        if series.dropna().empty:
             logger.warning(f"KNMI data voor station {stn} ({variable}) bevat alleen lege waarden.")
             return None

        return series
    except Exception as e:
        logger.error(f"Fout bij ophalen KNMI data ({variable}): {e}")
        return None
