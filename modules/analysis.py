import numpy as np
import pandas as pd

def calculate_stowa_p_statistics(series):
    """
    Calculates GHG, GLG, GVG based on percentiles.
    GHG: P5 (High)
    GVG: P50 (Average)
    GLG: P95 (Low)
    """
    if series is None or series.empty:
        return {"GHG": 0, "GLG": 0, "GVG": 0}
    
    # Sort for safety
    s = series.dropna().sort_values()
    
    return {
        "GHG": np.percentile(s, 95), # Top 5% (Higher values)
        "GVG": np.percentile(s, 50), # Median
        "GLG": np.percentile(s, 5),  # Bottom 5% (Lower values)
    }

def get_model_health_status(ml):
    """
    Determines traffic light status based on model fit.
    """
    if ml is None: return "Rood", "Geen model resultaten"
    
    stats = ml.stats.summary()
    r2_key = "rsq" if "rsq" in stats.index else "R2"
    r2 = stats.loc[r2_key, "Value"]
    
    if r2 > 0.8:
        return "Groen", f"Uitstekende fit (R² = {r2:.2f})"
    elif r2 > 0.6:
        return "Oranje", f"Matige fit (R² = {r2:.2f})"
    else:
        return "Rood", f"Zwakke fit (R² = {r2:.2f})"
