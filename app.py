import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from streamlit_plotly_events import plotly_events
import logging

# Modules
import modules.ingestion as ingestion
import modules.stresses as stresses
import modules.cleaner as cleaner
import modules.pastas_model as pastas_model
import modules.analysis as analysis
import modules.export as export

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PastasHydroInsight")

# Page Config
st.set_page_config(
    page_title="Pastas Hydro-Insight V2",
    page_icon="🌿",
    layout="wide",
)

# Custom CSS
st.markdown("""
<style>
    .section-header {
        background-color: rgba(255, 255, 255, 0.05);
        padding: 10px;
        border-radius: 5px;
        border-left: 5px solid #4CAF50;
        margin-top: 25px;
        margin-bottom: 15px;
    }
    .metric-card {
        background-color: rgba(255, 255, 255, 0.03);
        padding: 15px;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.1);
    }
</style>
""", unsafe_allow_html=True)

# ─── Session State Initialization ─────────────────────────────────────────────
if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["observations"] = {}    # {obs_id: {"name": str, "series": pd.Series, "metadata": dict, "outliers": list}}
    st.session_state["active_obs"] = None    # Current selected obs_id
    st.session_state["stresses"] = {"prec": None, "evap": None}
    st.session_state["model"] = None

def main():
    st.title("🌿 Pastas Hydro-Insight Dashboard")
    
    # ─── Sidebar: Data Ingestion & Selection ──────────────────────────────────
    with st.sidebar:
        st.header("📥 Data Ingestie")
        
        # Option A: BRO
        with st.expander("Optie A: BRO Automatisch", expanded=not st.session_state["observations"]):
            bro_id = st.text_input("GMW-ID", placeholder="GMW000000029823")
            if st.button("Haal BRO op"):
                with st.spinner("BRO aanvragen..."):
                    obs, err = ingestion.fetch_bro_groundwater(bro_id)
                    if err:
                        st.error(err)
                    else:
                        series = obs["values"]
                        meta = ingestion.get_metadata(obs)
                        # Construct a unique ID
                        obs_id = f"{bro_id}_{meta.get('Filter', 1)}"
                        st.session_state["observations"][obs_id] = {
                            "name": meta.get("Naam", obs_id),
                            "series": series,
                            "metadata": meta,
                            "outliers": []
                        }
                        st.session_state["active_obs"] = obs_id
                        st.success(f"Geladen: {obs_id}")
        
        # Option B: File Upload
        with st.expander("Optie B: Bestand Uploaden"):
            uploaded_file = st.file_uploader("CSV of Excel", type=["csv", "xlsx", "xls"])
            if uploaded_file and st.button("Verwerk Bestand"):
                with st.spinner("Bestand inladen..."):
                    obs, err = ingestion.read_uploaded_file(uploaded_file)
                    if err:
                        st.error(err)
                    else:
                        series = obs["values"]
                        meta = ingestion.get_metadata(obs)
                        obs_id = meta.get("Naam", "Handmatig")
                        st.session_state["observations"][obs_id] = {
                            "name": obs_id,
                            "series": series,
                            "metadata": meta,
                            "outliers": []
                        }
                        st.session_state["active_obs"] = obs_id
                        st.success(f"Geladen: {obs_id}")

        st.divider()
        
        # Selection & Management
        if st.session_state["observations"]:
            st.header("📍 Locaties")
            obs_list = list(st.session_state["observations"].keys())
            
            # Use columns for select + delete
            for o_id in obs_list:
                col_sel, col_del = st.columns([4, 1])
                # Highlight active
                btn_type = "primary" if st.session_state["active_obs"] == o_id else "secondary"
                if col_sel.button(f"{st.session_state['observations'][o_id]['name']}", key=f"sel_{o_id}", use_container_width=True, type=btn_type):
                    st.session_state["active_obs"] = o_id
                    st.session_state["model"] = None # Reset model when switching
                    st.session_state["stresses"] = {"prec": None, "evap": None} # Reset stresses for new obs
                    st.rerun()
                if col_del.button("🗑️", key=f"del_{o_id}"):
                    del st.session_state["observations"][o_id]
                    if st.session_state["active_obs"] == o_id:
                        st.session_state["active_obs"] = None
                    st.rerun()
            
            if st.button("Wis alles"):
                st.session_state["observations"] = {}
                st.session_state["active_obs"] = None
                st.rerun()

    # ─── Main Content: The Dashboard ──────────────────────────────────────────
    
    if not st.session_state["observations"]:
        st.info("👈 Begin door grondwaterdata in te laden via de zijbalk.")
        return

    # Section 1: Comparative View
    st.markdown('<div class="section-header"><h4>🔍 Vergelijken (Multi-serie)</h4></div>', unsafe_allow_html=True)
    fig_comp = go.Figure()
    for o_id, data in st.session_state["observations"].items():
        s = data["series"]
        fig_comp.add_trace(go.Scatter(x=s.index, y=s.values, mode='lines', name=data["name"]))
    
    fig_comp.update_layout(
        height=400, 
        template="plotly_dark", 
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Datum",
        yaxis_title="Stijghoogte (m t.o.v. NAP)",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_comp, use_container_width=True)

    # Section 2: Active Observation Detail
    if st.session_state["active_obs"]:
        active_id = st.session_state["active_obs"]
        active_data = st.session_state["observations"][active_id]
        
        st.markdown(f'<div class="section-header"><h4>📊 Detail Analyse: {active_data["name"]}</h4></div>', unsafe_allow_html=True)
        
        # Layout columns for metadata and meteorology
        col_meta, col_meteo = st.columns([1, 1])
        
        with col_meta:
            st.subheader("Metadata")
            # Flatten metadata for display
            display_meta = {k: v for k, v in active_data["metadata"].items() if not isinstance(v, (list, dict))}
            st.table(pd.DataFrame(display_meta.items(), columns=["Veld", "Waarde"]))
            
        with col_meteo:
            st.subheader("Meteorologie (KNMI)")
            coords = (active_data["metadata"].get("X", 0), active_data["metadata"].get("Y", 0))
            stations = stresses.get_nearest_knmi_stations(coords)
            
            if not stations.empty:
                st.write("Dichtstbijzijnde stations:")
                selected_stn = st.selectbox(
                    "Kies KNMI Station", 
                    stations["stn"].tolist(), 
                    format_func=lambda x: f"{stations.loc[stations['stn']==x, 'name'].values[0]} ({stations.loc[stations['stn']==x, 'dist'].values[0]/1000:.1f} km)"
                )
                
                if st.button("Koppel Neerslag & Verdamping"):
                    with st.status("KNMI meteorologie ophalen...") as status:
                        s = active_data["series"]
                        # We want at least 10 years of warmup if available
                        start_warmup = s.index.min() - pd.DateOffset(years=10)
                        
                        status.write(f"Aanvraag indienen bij KNMI API ({start_warmup.year} - {s.index.max().year})...")
                        prec = stresses.fetch_knmi_data(selected_stn, start_warmup, s.index.max(), "RH")
                        status.write("Referentie-verdamping (Makkink) berekenen...")
                        evap = stresses.fetch_knmi_data(selected_stn, start_warmup, s.index.max(), "EV24")
                        
                        st.session_state["stresses"]["prec"] = prec
                        st.session_state["stresses"]["evap"] = evap
                        if prec is not None and evap is not None:
                            status.update(label="KNMI data succesvol gekoppeld!", state="complete")
                        else:
                            status.update(label="Koppelen mislukt. Geen data gevonden.", state="error")
            else:
                st.warning("Geen KNMI stations gevonden. Controleer X/Y coördinaten.")

        # Section 3: Data Cleaning
        st.markdown('<div class="section-header"><h4>🧹 Data Cleaning & Uitschieters</h4></div>', unsafe_allow_html=True)
        col_clean_left, col_clean_right = st.columns([3, 1])
        
        with col_clean_left:
            try:
                df = active_data["series"].to_frame()
                fig_clean = cleaner.create_cleaning_chart(df, active_data["outliers"])
                # Key must be unique per observation to avoid cross-contamination
                selected_points = plotly_events(fig_clean, select_event=True, key=f"cleaner_{active_id}")
                
                if selected_points:
                    new_outliers = cleaner.update_outliers_from_selection({"points": selected_points})
                    if new_outliers:
                        current = set(active_data["outliers"])
                        current.update(new_outliers)
                        active_data["outliers"] = list(current)
                        st.rerun()
            except Exception as e:
                st.error(f"Fout in de chart module: {e}")
        
        with col_clean_right:
            st.info("Selecteer punten in de grafiek (lasso of box select) om ze als uitschieter te markeren.")
            st.write(f"**Gemarkeerd:** {len(active_data['outliers'])} uitschieters.")
            if st.button("Wis alle Uitschieters", key=f"clear_out_{active_id}"):
                active_data["outliers"] = []
                st.rerun()

        # Section 4: Pastas Modeling
        st.markdown('<div class="section-header"><h4>🧠 Pastas Modellering</h4></div>', unsafe_allow_html=True)
        if st.session_state["stresses"]["prec"] is None:
            st.info("Koppel eerst neerslag/verdamping (zie Meteorologie sectie hierboven) om een model te kunnen bouwen.")
        else:
            if st.button("🚀 Voer Pastas Simulatie uit", key=f"run_ml_{active_id}"):
                with st.status("Pastas model oplossen...") as status:
                    status.write("Model opbouwen...")
                    ml, err_build = pastas_model.build_pastas_model(
                        active_data["series"],
                        st.session_state["stresses"]["prec"],
                        st.session_state["stresses"]["evap"],
                        active_data["outliers"]
                    )
                    
                    if ml:
                        status.write("Parameters optimaliseren (Least Squares)...")
                        ml_solved, err_solve = pastas_model.solve_pastas_model(ml)
                        
                        if ml_solved:
                            st.session_state["model"] = ml_solved
                            status.update(label="Model succesvol opgelost!", state="complete")
                        else:
                            st.error(f"Fout tijdens optimalisatie: {err_solve}")
                            status.update(label="Model kon niet worden geoptimaliseerd.", state="error")
                    else:
                        st.error(f"Fout tijdens opbouw: {err_build}")
                        status.update(label="Model kon niet worden opgebouwd.", state="error")

            if st.session_state["model"]:
                ml = st.session_state["model"]
                status_m, desc = analysis.get_model_health_status(ml)
                
                # Metrics
                kpis = analysis.calculate_stowa_p_statistics(ml.simulate())
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("GHG (P95)", f"{kpis['GHG']:.2f}")
                m2.metric("GVG (P50)", f"{kpis['GVG']:.2f}")
                m3.metric("GLG (P5)", f"{kpis['GLG']:.2f}")
                m4.metric("Model Fit", status_m, help=desc)
                
                # Plots
                obs_series = ml.oseries.series
                sim_series = ml.simulate()
                fig_res = go.Figure()
                fig_res.add_trace(go.Scatter(x=obs_series.index, y=obs_series.values, mode='markers', name='Waargenomen', marker=dict(color='gray', size=4)))
                fig_res.add_trace(go.Scatter(x=sim_series.index, y=sim_series.values, mode='lines', name='Gesimuleerd', line=dict(color='blue')))
                fig_res.update_layout(height=400, template="plotly_dark", title="Obsereerd vs Gesimuleerd")
                st.plotly_chart(fig_res, use_container_width=True)
                
                # Decomposition
                st.subheader("Decompositie")
                decomp = pastas_model.get_decomposition(ml)
                if decomp is not None:
                    fig_dec = go.Figure()
                    for name, series in decomp.items():
                        fig_dec.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=name))
                    fig_dec.update_layout(height=300, template="plotly_dark")
                    st.plotly_chart(fig_dec, use_container_width=True)

        # Section 5: Export
        st.markdown('<div class="section-header"><h4>💾 Rapportage</h4></div>', unsafe_allow_html=True)
        if st.button("🚀 Maak Excel Export", key=f"export_{active_id}"):
            excel_data = export.generate_excel_report(
                st.session_state["model"],
                active_data["series"],
                active_data["metadata"]
            )
            st.download_button(
                label="Download Excel",
                data=excel_data,
                file_name=f"Pastas_Report_{active_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

if __name__ == "__main__":
    main()
