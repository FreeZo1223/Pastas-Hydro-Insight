import pastas as ps
import pandas as pd
import logging

logger = logging.getLogger("PastasHydroInsight")

def build_pastas_model(oseries, prec, evap, outliers=None):
    """
    Builds and solves a Pastas model (RMM).
    oseries: Groundwater series
    prec: Precipitation series
    evap: Evaporation series
    outliers: List of timestamps to ignore
    """
    try:
        # Handle outliers by setting to NaN in oseries copy
        oseries_clean = oseries.copy()
        if outliers is not None and len(outliers) > 0:
            oseries_clean.loc[outliers] = pd.NA
            logger.info(f"Ignoring {len(outliers)} outliers in model.")

        # Create model
        ml = ps.Model(oseries_clean, name="HydroInsight_Model")

        # Create stressmodel (RechargeModel)
        sm = ps.RechargeModel(prec, evap, ps.Gamma(), name="recharge")
        ml.add_stressmodel(sm)

        # Solve
        ml.solve(report=False)
        return ml
    except Exception as e:
        logger.error(f"Pastas Model Error: {e}")
        return None

def get_decomposition(ml):
    """
    Returns the contribution of stressors.
    """
    if ml is None: return None
    return ml.get_contributions()
