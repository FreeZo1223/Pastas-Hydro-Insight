import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
import logging

# Modules
import modules.ingestion as ingestion
import modules.stresses as stresses
# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PastasHydroInsight")

# Page Config
st.set_page_config(
    page_title="Pastas Hydro-Insight",
    page_icon="🌿",
    layout="wide",
)

# Custom CSS for modern look
st.markdown("""
    <style>
    .main { font-family: 'Inter', sans-serif; }
    .stMetric { background-color: rgba(255, 255, 255, 0.05); padding: 15px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); }
    </style>
    """, unsafe_allow_html=True)

# ─── Session State Initialization ─────────────────────────────────────────────
if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["gw_series"] = None     # Current pandas Series
    st.session_state["metadata"] = {}
    st.session_state["stresses"] = {"prec": None, "evap": None}
    st.session_state["outliers"] = []       # List of timestamps
    st.session_state["model"] = None
    st.session_state["status"] = "Nog niet berekend"

def main():
    st.title("🌿 Pastas Hydro-Insight")

    # Tabs
    tab_ingest, tab_clean, tab_analysis, tab_export = st.tabs([
        "📥 Data Ingestie", 
        "🧹 Data Cleaning", 
        "📊 Dashboard", 
        "💾 Export"
    ])

    with tab_ingest:
        import_tab()

    with tab_clean:
        cleaning_tab()

    with tab_analysis:
        analysis_tab()

    with tab_export:
        export_tab()

# ─── Tab Content ──────────────────────────────────────────────────────────────

def import_tab():
    st.header("Grondwater & Stressoren Laden")
    
    # Use two main columns for "Grondwaterstand" and "Meteorologie"
    main_col1, main_col2 = st.columns([1, 1])
    
    with main_col1:
        st.header("1. Grondwaterstand")
        
        # Sub-columns for BRO and File Upload
        sub_col1, sub_col2 = st.columns(2)
        
        with sub_col1:
            st.subheader("Optie A: BRO Automatisch")
            bro_id = st.text_input("Voer BRO-ID in (bijv. GMW000000029823)", "")
            if st.button("Haal gegevens op"):
                with st.spinner("BRO-database aanvragen..."):
                    obs, err = ingestion.fetch_bro_groundwater(bro_id)
                    if err:
                        st.error(err)
                    else:
                        st.session_state["gw_series"] = obs["values"]
                        st.session_state["metadata"] = ingestion.get_metadata(obs)
                        st.success(f"Data geladen voor {bro_id}")
                        st.rerun()

        with sub_col2:
            st.subheader("Optie B: Bestand Uploaden")
            uploaded_file = st.file_uploader("Sleep een CSV of Excel bestand hierheen", type=["csv", "xlsx", "xls"])
            if uploaded_file is not None:
                if st.button("Verwerk bestand"):
                    with st.spinner(f"Bestand '{uploaded_file.name}' verwerken..."):
                        obs, err = ingestion.read_uploaded_file(uploaded_file)
                        if err:
                            st.error(err)
                        else:
                            st.session_state["gw_series"] = obs["values"]
                            st.session_state["metadata"] = ingestion.get_metadata(obs)
                            st.success(f"Bestand '{uploaded_file.name}' succesvol geladen.")
                            st.rerun()
        
        if st.session_state["gw_series"] is not None:
            st.write("**Metadata:**")
            st.table(pd.DataFrame(st.session_state["metadata"].items(), columns=["Veld", "Waarde"]))

    with main_col2:
        st.subheader("2. Meteorologie (Auto-Stress)")
        if st.session_state["gw_series"] is not None:
            coords = (st.session_state["metadata"].get("x", 0), st.session_state["metadata"].get("y", 0))
            stations = stresses.get_nearest_knmi_stations(coords)
            
            if not stations.empty:
                st.write("Dichtstbijzijnde stations:")
                st.dataframe(stations[["name", "dist"]])
                
                selected_stn = st.selectbox("Kies KNMI Station", stations["stn"].tolist(), format_func=lambda x: stations.loc[stations["stn"]==x, "name"].values[0])
                
                if st.button("Koppel Neerslag & Verdamping"):
                    with st.status("KNMI meteorologie ophalen...") as status:
                        s = st.session_state["gw_series"]
                        status.write("Aanvraag indienen bij KNMI API...")
                        prec = stresses.fetch_knmi_data(selected_stn, s.index.min(), s.index.max(), "RH")
                        status.write("Referentie-verdamping (Makkink) berekenen...")
                        evap = stresses.fetch_knmi_data(selected_stn, s.index.min(), s.index.max(), "EV24")
                        
                        st.session_state["stresses"]["prec"] = prec
                        st.session_state["stresses"]["evap"] = evap
                        status.update(label="KNMI data succesvol gekoppeld!", state="complete")
            else:
                st.info("Geen stations gevonden (check coördinaten).")
        else:
            st.info("Laad eerst grondwaterdata om stations te zoeken.")

def cleaning_tab():
    st.header("Interactieve Data Cleaner")
    if st.session_state["gw_series"] is None:
        st.warning("Laad eerst data in de Ingestie tab.")
        return
    
    st.write("Gebruik de **Lasso** of **Box** select op de Plotly chart om uitschieters (outliers) te markeren.")
    
    # Graceful degradation for Plotly
    try:
        df = st.session_state["gw_series"].to_frame()
        fig = cleaner.create_cleaning_chart(df, st.session_state["outliers"])
        
        # Catch selection events
        selected_points = plotly_events(fig, select_event=True, key="cleaner_chart")
        
        if selected_points:
            new_outliers = cleaner.update_outliers_from_selection({"points": selected_points})
            if len(new_outliers) > 0:
                # Add to existing outliers (simple union)
                current = set(st.session_state["outliers"])
                current.update(new_outliers)
                st.session_state["outliers"] = list(current)
                st.rerun()

        if st.button("Wis alle Outliers"):
            st.session_state["outliers"] = []
            st.rerun()
            
        st.info(f"Aantal gemarkeerde outliers: {len(st.session_state['outliers'])}")
    except Exception as e:
        st.error(f"Fout in de chart module: {e}")

def analysis_tab():
    st.header("Hydrologische Analyse & Modellering")
    if st.session_state["gw_series"] is None or st.session_state["stresses"]["prec"] is None:
        st.warning("Data incompleet. Zorg voor Grondwater + KNMI data.")
        return

    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Model Instellingen")
        if st.button("🚀 Voer Pastas Simulatie uit"):
            with st.status("Pastas model oplossen...") as status:
                status.write("Gegevens voorbereiden...")
                ml = pastas_model.build_pastas_model(
                    st.session_state["gw_series"],
                    st.session_state["stresses"]["prec"],
                    st.session_state["stresses"]["evap"],
                    st.session_state["outliers"]
                )
                status.write("Parameters optimaliseren (Least Squares)...")
                st.session_state["model"] = ml
                if ml:
                    status.update(label="Model succesvol opgelost!", state="complete")
                else:
                    status.update(label="Model kon niet worden opgelost.", state="error")

        if st.session_state["model"]:
            ml = st.session_state["model"]
            status, desc = analysis.get_model_health_status(ml)
            
            # KPI Section
            st.subheader("Grondwater Statistieken")
            kpis = analysis.calculate_stowa_p_statistics(ml.simulate())
            
            c1, c2, c3 = st.columns(3)
            c1.metric("GHG (P95)", f"{kpis['GHG']:.2f}")
            c2.metric("GVG (P50)", f"{kpis['GVG']:.2f}")
            c3.metric("GLG (P5)", f"{kpis['GLG']:.2f}")
            
            st.write("---")
            st.write(f"**Model Gezondheid:** {status}")
            st.write(desc)

    with col2:
        if st.session_state["model"]:
            st.subheader("Simulatie Resultaat")
            ml = st.session_state["model"]
            
            # Use ml.oseries.series to get the actual pandas Series from Pastas TimeSeries object
            obs_series = ml.oseries.series
            sim_series = ml.simulate()
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=obs_series.index, y=obs_series.values, mode='markers', name='Observed', marker=dict(color='gray', size=4)))
            fig.add_trace(go.Scatter(x=sim_series.index, y=sim_series.values, mode='lines', name='Simulated', line=dict(color='blue')))
            fig.update_layout(height=400, template="plotly_dark", title="Observed vs Simulated")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Decompositie (Stress Bijdrages)")
            decomp = pastas_model.get_decomposition(ml)
            if decomp:
                fig_dec = go.Figure()
                for name, series in decomp.items():
                    fig_dec.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=name))
                fig_dec.update_layout(height=300, template="plotly_dark")
                st.plotly_chart(fig_dec, use_container_width=True)

def export_tab():
    st.header("Rapportage & Export")
    if st.session_state["gw_series"] is None:
        st.info("Geen data om te exporteren.")
        return
    
    st.write("Genereer een volledig Excel rapport met alle ruwe data, modelparameters en statistieken.")
    
    if st.button("🚀 Maak Excel Export"):
        excel_data = export.generate_excel_report(
            st.session_state["model"],
            st.session_state["gw_series"],
            st.session_state["metadata"]
        )
        st.download_button(
            label="Download Excel",
            data=excel_data,
            file_name=f"Pastas_Hydro_Insight_{st.session_state['metadata'].get('Naam', 'export')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

if __name__ == "__main__":
    main()
