import hydropandas as hpd
import streamlit as st
import logging
import numpy as np
import pandas as pd
import os

logger = logging.getLogger("PastasHydroInsight")

@st.cache_data(show_spinner=False)
def fetch_bro_groundwater(bro_id: str):
    """
    Fetches groundwater level data and metadata from BRO via hydropandas.
    """
    try:
        bro_id = bro_id.strip().upper()
        logger.info(f"Fetching BRO data for: {bro_id}")
        
        # 1. Check ID type
        if bro_id.startswith("GMW"):
            # Individual well - requires tube_nr
            # Default to tube 1 as it's the most common use case
            obs = hpd.GroundwaterObs.from_bro(bro_id, tube_nr=1)
            
            if obs.empty:
                logger.warning(f"BRO GMW ID {bro_id} leverde een lege set op.")
                return None, f"Put {bro_id} gevonden, maar bevat geen metingen voor filter 1."
            
            return obs, None
            
        elif bro_id.startswith("GMN"):
            # Groundwater monitoring net - returns a collection
            oc = hpd.read_bro(bro_id=bro_id)
            if oc.empty:
                logger.warning(f"GMN ID {bro_id} leeg.")
                return None, "Geen data gevonden voor dit GMN-netwerk."
            return oc.iloc[0], None
            
        elif bro_id.startswith("GLD"):
            # Direct dossier lookup
            obs = hpd.GroundwaterObs.from_bro(bro_id)
            if obs.empty:
                return None, f"Geen data gevonden voor dossier {bro_id}."
            return obs, None
            
        else:
            return None, (
                f"ID '{bro_id}' wordt niet herkend als BRO-ID (begint met GMW, GMN of GLD). "
                "Voor legacy DINO-nummers: zoek a.u.b. het bijbehorende GMW-nummer op via "
                "DinoLoket/BRO of download de data handmatig."
            )

    except Exception as e:
        logger.error(f"BRO Fetch Error: {e}")
        error_msg = str(e)
        if "tube_nr" in error_msg:
            error_msg = "Specificeer een tube_nr (nu default 1). Wellicht heeft deze put een ander filternummer?"
        return None, f"Fout bij ophalen BRO data: {error_msg}"

def get_metadata(obs):
    """
    Extracts relevant metadata from a hydropandas Obs object.
    """
    # hydropandas Obs objects have a .metadata attribute (dict)
    meta = getattr(obs, "metadata", {})
    return {
        "Naam": meta.get("name", "Onbekend"),
        "Filter": meta.get("tube_nr", 1),
        "X": meta.get("x", 0),
        "Y": meta.get("y", 0),
        "Bovenkant Filter": meta.get("screen_top", np.nan),
        "Onderkant Filter": meta.get("screen_bottom", np.nan),
        "Maaiveld": meta.get("ground_level", np.nan),
    }

def read_uploaded_file(uploaded_file):
    """
    Reads an uploaded CSV or Excel file and converts it to a hydropandas-compatible structure.
    """
    try:
        filename = uploaded_file.name
        if filename.endswith(".csv"):
            # Try most common separators sequentially to avoid binary/text sniffer issues
            delimiters = [",", ";"]
            df = None
            for sep in delimiters:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, sep=sep)
                    # If we only have one column, it's likely the wrong separator
                    if len(df.columns) > 1:
                        break
                except:
                    continue
            
            if df is None:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file) # Fallback

        elif filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(uploaded_file)
        else:
            return None, "Bestandsformaat niet ondersteund. Gebruik CSV of Excel."

        if df.empty:
            return None, "Bestand is leeg."

        # Attempt to find date and value columns
        date_col = None
        val_col = None
        
        # Look for date-like content
        for col in df.columns:
            try:
                pd.to_datetime(df[col].iloc[0])
                date_col = col
                break
            except:
                continue
        
        # Look for numeric content
        for col in df.columns:
            if col == date_col: continue
            if pd.api.types.is_numeric_dtype(df[col]):
                val_col = col
                break
        
        if not date_col or not val_col:
            return None, "Kon datum- of waardekolom niet automatisch identificeren. Zorg voor een kolom met datums en een kolom met getallen."

        # Prepare DataFrame
        df[date_col] = pd.to_datetime(df[date_col])
        df = df.set_index(date_col).sort_index()
        
        # Create a mock metadata dict for hydropandas compatibility
        name = os.path.splitext(filename)[0]
        metadata = {
            "name": name,
            "x": 0, "y": 0,
            "source": "Manual Upload"
        }
        
        # Create a hydropandas-like observation object
        # We'll use a simple wrapper or just a DataFrame that mimics the expected structure
        obs_df = pd.DataFrame({"values": df[val_col]})
        obs = hpd.GroundwaterObs(obs_df, metadata=metadata)
        
        return obs, None

    except Exception as e:
        logger.error(f"File Upload Error: {e}")
        return None, f"Fout bij lezen bestand: {e}"
