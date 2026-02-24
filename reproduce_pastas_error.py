import pastas as ps
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Test")

def test_pastas_attributes():
    # Create dummy data
    idx = pd.date_range("2000-01-01", periods=100, freq="D")
    oseries = pd.Series(np.random.randn(100), index=idx, name="oseries")
    prec = pd.Series(np.random.rand(100), index=idx, name="prec")
    evap = pd.Series(np.random.rand(100), index=idx, name="evap")

    # Build model
    ml = ps.Model(oseries)
    sm = ps.RechargeModel(prec, evap, ps.Gamma(), name="recharge")
    ml.add_stressmodel(sm)

    print(f"ml.oseries type: {type(ml.oseries)}")
    try:
        print(f"ml.oseries.index: {ml.oseries.index}")
    except AttributeError as e:
        print(f"ml.oseries.index FAILED: {e}")
    
    try:
        print(f"ml.oseries.series.index: {ml.oseries.series.index}")
    except AttributeError as e:
        print(f"ml.oseries.series.index FAILED: {e}")

    # Check stressmodel stress
    stress0 = ml.stressmodels["recharge"].stress[0]
    print(f"Stress[0] type: {type(stress0)}")
    try:
        print(f"Stress[0].index: {stress0.index}")
    except AttributeError as e:
        print(f"Stress[0].index FAILED: {e}")
    
    try:
        print(f"Stress[0].series.index: {stress0.series.index}")
    except AttributeError as e:
        print(f"Stress[0].series.index FAILED: {e}")

if __name__ == "__main__":
    test_pastas_attributes()
