"""Tests voor de plot-helpers en JSON-serialisatie."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from pastasdash_v2.components.plots import clean_fig


def test_clean_fig_converts_timestamps():
    # Bouw een figuur met een pandas Timestamp
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=[pd.Timestamp("2026-05-28"), pd.Timestamp("2026-05-29")],
            y=[1.0, 2.0],
        )
    )
    
    # Run clean_fig
    cleaned = clean_fig(fig)
    
    # Verifieer dat het een dict is
    assert isinstance(cleaned, dict)
    
    # Verifieer dat het JSON serialiseerbaar is met standard json
    import json
    serialized = json.dumps(cleaned)
    assert isinstance(serialized, str)
    
    # En controleer dat de timestamp is omgezet naar een string-representatie in de x-waarden
    loaded = json.loads(serialized)
    x_vals = loaded["data"][0]["x"]
    assert x_vals == ["2026-05-28T00:00:00", "2026-05-29T00:00:00"]
