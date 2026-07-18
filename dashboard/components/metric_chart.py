"""
Netwroxia Dashboard — Metric Chart Component
Plotly time-series charts from InfluxDB live data. DEFENSIVE: skips missing columns.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import plotly.graph_objects as go
import streamlit as st
from utils.influx_client import (
    get_ping_data, get_ospf_data, get_bgp_data,
    get_container_cpu, get_container_mem
)


def _safe_col(df, col: str):
    """Return column if exists, else None."""
    if df is None or df.empty:
        return None
    return col if col in df.columns else None


def plot_ping_latency(df):
    """Line chart: ping latency over time per router."""
    col = _safe_col(df, "average_response_ms")
    if not col:
        return None
    fig = go.Figure()
    for url, grp in df.groupby("url"):
        router = _ip_to_name(url)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines+markers", name=router,
            line=dict(width=2)
        ))
    fig.update_layout(
        title="Ping Latency (ms)",
        xaxis_title="Time", yaxis_title="Latency (ms)",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig


def plot_packet_loss(df):
    """Line chart: packet loss % over time per router."""
    col = _safe_col(df, "percent_packet_loss")
    if not col:
        return None
    fig = go.Figure()
    for url, grp in df.groupby("url"):
        router = _ip_to_name(url)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines+markers", name=router,
            line=dict(width=2), connectgaps=True
        ))
    fig.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="CRITICAL")
    fig.add_hline(y=10, line_dash="dash", line_color="orange", annotation_text="WARNING")
    fig.update_layout(
        title="Packet Loss (%)",
        xaxis_title="Time", yaxis_title="Loss %",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig


def plot_ospf_neighbors(df):
    """Bar chart: OSPF neighbor count per router over time."""
    col = _safe_col(df, "count")
    if not col:
        return None
    fig = go.Figure()
    for router, grp in df.groupby("router"):
        rname = _normalize_router(router)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines+markers", name=rname,
            line=dict(width=2)
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="DOWN")
    fig.update_layout(
        title="OSPF Neighbor Count",
        xaxis_title="Time", yaxis_title="Neighbors",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig


def plot_bgp_state(df):
    """Step chart: BGP state (1=Established, 0=Down) over time."""
    col = _safe_col(df, "state")
    if not col:
        return None
    fig = go.Figure()
    for router, grp in df.groupby("router"):
        rname = _normalize_router(router)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines+markers", name=rname,
            line=dict(width=2, shape="hv")
        ))
    fig.add_hline(y=1, line_dash="dash", line_color="green", annotation_text="Established")
    fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Down")
    fig.update_layout(
        title="BGP Peer State (1=Up, 0=Down)",
        xaxis_title="Time", yaxis_title="State",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(tickvals=[0, 1, 2, 3], ticktext=["Down", "Established", "Other", "Other"])
    )
    return fig


def plot_container_cpu(df):
    """Line chart: container CPU usage %."""
    col = _safe_col(df, "usage_percent")
    if not col:
        return None
    fig = go.Figure()
    for cname, grp in df.groupby("container_name"):
        rname = _container_to_router(cname)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines", name=rname, line=dict(width=2)
        ))
    fig.add_hline(y=90, line_dash="dash", line_color="red", annotation_text="CRITICAL")
    fig.update_layout(
        title="Container CPU Usage (%)",
        xaxis_title="Time", yaxis_title="CPU %",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig


def plot_container_mem(df):
    """Line chart: container memory usage %."""
    col = _safe_col(df, "usage_percent")
    if not col:
        return None
    fig = go.Figure()
    for cname, grp in df.groupby("container_name"):
        rname = _container_to_router(cname)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp[col],
            mode="lines", name=rname, line=dict(width=2)
        ))
    fig.add_hline(y=90, line_dash="dash", line_color="red", annotation_text="CRITICAL")
    fig.update_layout(
        title="Container Memory Usage (%)",
        xaxis_title="Time", yaxis_title="Mem %",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    return fig


def render_metrics_tab():
    """Render the full Metrics tab with all charts. DEFENSIVE."""
    st.subheader("📊 Live Metrics from InfluxDB")
    hours = st.slider("Time window (hours)", 1, 24, 1, key="metric_hours")

    # Ping
    df_ping = get_ping_data(hours=hours, limit=500)
    if df_ping is not None and not df_ping.empty:
        fig1 = plot_ping_latency(df_ping)
        fig2 = plot_packet_loss(df_ping)
        if fig1:
            st.plotly_chart(fig1, use_container_width=True)
        else:
            st.info("ℹ️ Latency data unavailable (likely 100% packet loss).")
        if fig2:
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("No ping data available.")

    # OSPF
    df_ospf = get_ospf_data(hours=hours, limit=500)
    if df_ospf is not None and not df_ospf.empty:
        fig3 = plot_ospf_neighbors(df_ospf)
        if fig3:
            st.plotly_chart(fig3, use_container_width=True)
    else:
        st.warning("No OSPF data available.")

    # BGP
    df_bgp = get_bgp_data(hours=hours, limit=500)
    if df_bgp is not None and not df_bgp.empty:
        fig4 = plot_bgp_state(df_bgp)
        if fig4:
            st.plotly_chart(fig4, use_container_width=True)
    else:
        st.warning("No BGP data available.")

    # Container CPU/Mem
    df_cpu = get_container_cpu(hours=hours, limit=500)
    df_mem = get_container_mem(hours=hours, limit=500)
    if df_cpu is not None and not df_cpu.empty:
        fig5 = plot_container_cpu(df_cpu)
        if fig5:
            st.plotly_chart(fig5, use_container_width=True)
    else:
        st.warning("No container CPU data available.")
    if df_mem is not None and not df_mem.empty:
        fig6 = plot_container_mem(df_mem)
        if fig6:
            st.plotly_chart(fig6, use_container_width=True)
    else:
        st.warning("No container memory data available.")


# ── Helpers ─────────────────────────────────────────────
def _ip_to_name(ip: str) -> str:
    mapping = {
        "172.20.20.3": "HO-Chennai",
        "172.20.20.4": "ZO-Bengaluru",
        "172.20.20.5": "BR-Koramangala",
        "172.20.20.7": "BR-Whitefield",
    }
    return mapping.get(str(ip), str(ip))


def _normalize_router(name: str) -> str:
    mapping = {
        "ho-chennai": "HO-Chennai",
        "zo-bengaluru": "ZO-Bengaluru",
        "br-koramangala": "BR-Koramangala",
        "br-whitefield": "BR-Whitefield",
    }
    return mapping.get(str(name).lower().strip(), str(name).title())


def _container_to_router(cname: str) -> str:
    mapping = {
        "clab-netwroxia-ho-chennai": "HO-Chennai",
        "clab-netwroxia-zo-bengaluru": "ZO-Bengaluru",
        "clab-netwroxia-br-koramangala": "BR-Koramangala",
        "clab-netwroxia-br-whitefield": "BR-Whitefield",
    }
    return mapping.get(str(cname), str(cname))


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Metric chart module loaded (defensive).")
    df = get_ping_data(hours=1, limit=10)
    if df is not None and not df.empty:
        print(f"  Ping cols: {list(df.columns)}")
        print(f"  Has latency: {'average_response_ms' in df.columns}")
        print(f"  Has loss: {'percent_packet_loss' in df.columns}")
    else:
        print("  No ping data")
    print("  All chart functions ready.")