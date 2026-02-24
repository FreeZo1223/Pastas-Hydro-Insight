import pandas as pd
import io

def generate_excel_report(ml, oseries_raw, metadata):
    """
    Generates an Excel report with multiple sheets.
    """
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # 1. Metadata
        df_meta = pd.DataFrame(metadata.items(), columns=["Veld", "Waarde"])
        df_meta.to_excel(writer, sheet_name="Metadata", index=False)
        
        # 2. Raw Data
        oseries_raw.to_excel(writer, sheet_name="Ruwe Data")
        
        # 3. Simulation & Results
        if ml is not None:
            # Simulated series
            sim = ml.simulate()
            sim.name = "Simulatie"
            sim.to_excel(writer, sheet_name="Model Simulatie")
            
            # Parameters
            params = ml.parameters
            params.to_excel(writer, sheet_name="Model Parameters")
            
            # Statistics
            stats = ml.stats.summary()
            stats.to_excel(writer, sheet_name="Statistieken")

    return output.getvalue()
