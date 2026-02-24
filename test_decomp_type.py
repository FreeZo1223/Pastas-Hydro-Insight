import pastas as ps
import pandas as pd
import numpy as np

def test_decomposition():
    idx = pd.date_range("2000-01-01", periods=100, freq="D")
    oseries = pd.Series(np.random.randn(100), index=idx, name="oseries")
    prec = pd.Series(np.random.rand(100), index=idx, name="prec")
    evap = pd.Series(np.random.rand(100), index=idx, name="evap")

    ml = ps.Model(oseries)
    sm = ps.RechargeModel(prec, evap, ps.Gamma(), name="recharge")
    ml.add_stressmodel(sm)
    ml.solve(report=False)

    decomp = ml.get_contributions()
    print(f"Type of decomp: {type(decomp)}")
    if isinstance(decomp, list):
        print(f"Length of list: {len(decomp)}")
        for i, item in enumerate(decomp):
            print(f"Item {i} type: {type(item)}")
            if hasattr(item, "name"):
                print(f"Item {i} name: {item.name}")
    elif isinstance(decomp, pd.DataFrame):
        print("Decomp is a DataFrame")
        print(f"Columns: {decomp.columns}")

if __name__ == "__main__":
    test_decomposition()
