import pastas as ps
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("PastasHydroInsight")

def build_pastas_model(oseries, prec, evap, outliers=None):
    """
    Builds a Pastas model (RMM) without solving it yet.
    Returns (model, error_message)
    """
    try:
        # Pre-check: Stressors must not be None
        if prec is None or evap is None:
            return None, "Neerslag of verdamping ontbreekt."

        # Handle outliers
        oseries_clean = oseries.copy()
        if outliers is not None and len(outliers) > 0:
            # Pastas handles NaNs in oseries as missing observations
            oseries_clean.loc[outliers] = np.nan
            logger.info(f"Ignoring {len(outliers)} outliers in model.")

        # Create model
        ml = ps.Model(oseries_clean, name="HydroInsight_Model")

        # Create stressmodel (RechargeModel)
        # Using Gamma response function as default
        sm = ps.RechargeModel(prec, evap, ps.Gamma(), name="recharge")
        ml.add_stressmodel(sm)

        # Check overlap
        tmin = max(oseries_clean.index.min(), prec.index.min(), evap.index.min())
        tmax = min(oseries_clean.index.max(), prec.index.max(), evap.index.max())
        
        if tmin >= tmax:
            return None, "Geen overlap tussen grondwaterstand en KNMI data."

        return ml, None
    except Exception as e:
        logger.error(f"Pastas Build Error: {e}")
        return None, str(e)

def solve_pastas_model(ml):
    """
    Solves the model with optimized settings for speed and stability.
    """
    try:
        if ml is None: return None, "Geen model om op te lossen."
        
        # Calculate available warmup based on stressor start vs oseries start
        # Use .series.index for Pastas TimeSeries objects
        s_start = ml.oseries.series.index.min()
        prec_start = ml.stressmodels["recharge"].stress[0].series.index.min()
        available_warmup_days = (s_start - prec_start).days
        
        # Use 10 years or whatever is available
        warmup = min(3650, max(0, available_warmup_days))
        
        # Solve with optimized settings
        # ps.LeastSquares is generally fast and robust
        ml.solve(
            warmup=warmup,
            report=False,
            solver=ps.LeastSquares()
        )
        return ml, None
    except Exception as e:
        logger.error(f"Pastas Solve Error: {e}")
        return None, str(e)

def get_decomposition(ml):
    """
    Returns the contribution of stressors.
    """
    if ml is None: return None
    try:
        return ml.get_contributions()
    except Exception as e:
        logger.error(f"Fout bij ophalen decompositie: {e}")
        return None
