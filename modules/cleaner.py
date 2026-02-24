import plotly.graph_objects as go
import streamlit as st
import pandas as pd

def create_cleaning_chart(df, outliers):
    """
    Creates an interactive Plotly chart with lasso/box select.
    df: DataFrame with 'values' index is DateTime
    outliers: List of DateTime indices that are marked as outliers
    """
    fig = go.Figure()

    # Normal points
    fig.add_trace(go.Scatter(
        x=df.index,
        y=df.iloc[:, 0],
        mode='lines+markers',
        name='Grondwaterstand',
        marker=dict(size=6, color='blue'),
        line=dict(width=1),
        customdata=df.index,
    ))

    # Highlight outliers
    if outliers:
        outlier_df = df.loc[outliers]
        fig.add_trace(go.Scatter(
            x=outlier_df.index,
            y=outlier_df.iloc[:, 0],
            mode='markers',
            name='Outliers',
            marker=dict(size=10, color='red', symbol='x'),
        ))

    fig.update_layout(
        dragmode='lasso',
        hovermode='closest',
        title="Interactieve Data Cleaner (Gebruik Lasso om uitschieters te markeren)",
        xaxis_title="Datum",
        yaxis_title="Stand (m NAP)",
        template="plotly_dark",
        margin=dict(l=40, r=40, b=40, t=60),
    )

    return fig

def update_outliers_from_selection(selection):
    """
    Extracts selected points from Plotly selection event.
    """
    if selection and "points" in selection:
        selected_indices = [p["x"] for p in selection["points"]]
        # Convert strings back to Timestamp if needed
        selected_ts = pd.to_datetime(selected_indices)
        return selected_ts
    return []
