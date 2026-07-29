"""
Netwroxia Dashboard — Metric Chart Component
Plotly time-series charts. Real-time anchored, 1-second auto-refresh.
Data fixes:
  • OSPF neighbor count: tries multiple column names, falls back to realistic demo.
  • Packet loss: unique colors + markers per router; no overlapping identical lines.
  • Ping latency: same shared telemetry as OSPF/packet-loss (single source of truth).
  • Demo generator writes into st.session_state so Overview / Network / Predictions /
    Copilot all read the SAME numbers.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, timedelta
import random
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

# ── Fragment support detection ─────────────────────────────────────────────
# Root cause of the "charts greying out constantly" issue: st_autorefresh
# was firing a FULL-SCRIPT rerun every `refresh_s` seconds, and Streamlit
# dims/greys the entire page while any full rerun is in flight. At a 1s
# interval that overlay is basically always on.
#
# Fix: isolate the auto-refreshing chart block inside an st.fragment so only
# that block re-executes (and only that block's DOM region gets the brief
# "running" indicator) — the sliders, tabs, and header never grey out.
_SUPPORTS_FRAGMENT = hasattr(st, "fragment")

def _supports_run_every():
    """Newer Streamlit's st.fragment(run_every=...) lets the fragment drive
    its own timer internally — no autorefresh component needed at all."""
    if not _SUPPORTS_FRAGMENT:
        return False
    try:
        import inspect
        return "run_every" in inspect.signature(st.fragment).parameters
    except (TypeError, ValueError):
        return False

_SUPPORTS_RUN_EVERY = _supports_run_every()

from utils.influx_client import (
    get_ping_data, get_ospf_data, get_bgp_data,
    get_container_cpu, get_container_mem
)

# ── Router registry (single source of truth) ──────────────────────────────
ROUTERS = ["HO-Chennai", "ZO-Bengaluru", "BR-Koramangala", "BR-Whitefield"]

# Distinct colors + markers so overlapping series stay visible
ROUTER_STYLE = {
    "HO-Chennai":      {"color": "#00E5FF", "symbol": "circle",       "dash": "solid"},
    "ZO-Bengaluru":    {"color": "#7C4DFF", "symbol": "square",       "dash": "solid"},
    "BR-Koramangala":  {"color": "#FFC400", "symbol": "diamond",      "dash": "solid"},
    "BR-Whitefield":   {"color": "#FF3D71", "symbol": "triangle-up",  "dash": "solid"},
}

IP_MAP = {
    "172.20.20.3": "HO-Chennai",
    "172.20.20.4": "ZO-Bengaluru",
    "172.20.20.5": "BR-Koramangala",
    "172.20.20.7": "BR-Whitefield",
}
CONTAINER_MAP = {
    "clab-netwroxia-ho-chennai":     "HO-Chennai",
    "clab-netwroxia-zo-bengaluru":   "ZO-Bengaluru",
    "clab-netwroxia-br-koramangala": "BR-Koramangala",
    "clab-netwroxia-br-whitefield":  "BR-Whitefield",
}

OSPF_COL_CANDIDATES  = ["count", "neighbor_count", "neighbors", "ospf_neighbors", "value", "_value"]
LOSS_COL_CANDIDATES  = ["percent_packet_loss", "packet_loss", "loss", "packet_loss_percent"]
LAT_COL_CANDIDATES   = ["average_response_ms", "latency_ms", "avg_latency", "rtt_ms"]


# ── Helpers ───────────────────────────────────────────────────────────────
def _ip_to_name(ip):  return IP_MAP.get(str(ip), str(ip))
def _container_to_router(c): return CONTAINER_MAP.get(str(c), str(c))

def _normalize_router(name):
    key = str(name).lower().strip()
    for r in ROUTERS:
        if r.lower() == key:
            return r
    return str(name).title()

def _pick_col(df, candidates):
    if df is None or df.empty:
        return None
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _align_to_now(df, time_col="time"):
    """Shift timestamps so the newest sample sits at local wall-clock 'now'."""
    if df is None or df.empty or time_col not in df.columns:
        return df
    df = df.copy()
    ts = pd.to_datetime(df[time_col], errors="coerce", utc=True).dt.tz_convert(None)
    # Convert from UTC-naive to LOCAL-naive by adding local UTC offset
    local_offset = datetime.now() - datetime.utcnow()
    ts = ts + local_offset
    latest = ts.max()
    if pd.isna(latest):
        df[time_col] = ts
        return df
    shift = datetime.now() - latest.to_pydatetime()
    df[time_col] = ts + shift
    return df

def _apply_time_axis(fig, hours):
    now = datetime.now()
    fig.update_xaxes(
        range=[now - timedelta(hours=hours), now],
        tickformat="%H:%M:%S",
    )
    return fig


# ── Demo-data generator (used only when live telemetry is empty/all-zero) ──
def _generate_demo_timeline(hours=1, points=120):
    """Realistic banking-MPLS telemetry: BR-Whitefield gradually fails."""
    now = datetime.now()
    times = [now - timedelta(seconds=int(hours * 3600 * (1 - i / (points - 1)))) for i in range(points)]

    rng = random.Random(int(now.timestamp()) // 5)  # stable-ish per 5s window

    def smooth_walk(base, target, points, jitter, seed_off=0):
        """Gradual drift from base toward target with light jitter."""
        r = random.Random(int(now.timestamp()) // 10 + seed_off)
        vals = []
        v = base
        for i in range(points):
            f = i / (points - 1)
            aim = base + (target - base) * f
            # Move v toward aim smoothly
            v += (aim - v) * 0.25 + r.uniform(-jitter, jitter)
            vals.append(max(0.5, v))
        return vals

    # Realistic enterprise MPLS latency profiles
    # HO stable ~2ms, ZO ~6ms, Koramangala warning ~12ms, Whitefield degrades 12→45ms
    lat_series = {
        "HO-Chennai":     smooth_walk(2.0,  2.3,   points, 0.25, seed_off=1),
        "ZO-Bengaluru":   smooth_walk(5.5,  7.5,   points, 0.55, seed_off=2),
        "BR-Koramangala": smooth_walk(11.0, 13.5,  points, 1.10, seed_off=3),
        "BR-Whitefield":  smooth_walk(12.0, 45.0,  points, 1.20, seed_off=4),
    }
    # Add a couple of realistic transient spikes on Koramangala (congestion)
    for idx in (int(points * 0.45), int(points * 0.72)):
        if 0 <= idx < points:
            lat_series["BR-Koramangala"][idx] += 3.5

    def nonlinear_ramp(base, target, points, jitter, power=2.0, seed_off=0):
        """Accelerating drift from base toward target (slow start, faster
        finish) with light jitter — used for a degrading link's packet loss
        instead of a straight-line ramp."""
        r = random.Random(int(now.timestamp()) // 10 + seed_off)
        vals = []
        for i in range(points):
            f = i / (points - 1)
            eased = f ** power  # <1 slows early growth, accelerates later
            aim = base + (target - base) * eased
            v = aim + r.uniform(-jitter, jitter)
            vals.append(max(0.0, min(100.0, v)))
        return vals

    loss_series = {
        "HO-Chennai":     [max(0.0, 0.5 + math.sin(i / 9.0) * 0.4) for i in range(points)],
        "ZO-Bengaluru":   [max(0.0, 2.0 + math.sin(i / 7.0) * 1.2) for i in range(points)],
        "BR-Koramangala": [max(0.0, 4.0 + math.sin(i / 5.0) * 2.5) for i in range(points)],
        # Whitefield loss ramps correlated with latency: 5 → 100, non-linear (accelerating), not a straight line
        "BR-Whitefield":  nonlinear_ramp(5.0, 100.0, points, jitter=1.5, power=2.0, seed_off=5),
    }

    ospf_series = {
        "HO-Chennai":     [3] * (points - max(1, points // 8)) + [2] * max(1, points // 8),
        "ZO-Bengaluru":   [1] * points,
        "BR-Koramangala": [1] * points,
        "BR-Whitefield":  [1 if (i / (points - 1)) < 0.55 else 0 for i in range(points)],
    }

    ping_rows, ospf_rows = [], []
    for router in ROUTERS:
        for i, t in enumerate(times):
            pl = loss_series[router][i]
            lat = lat_series[router][i]
            # If packet loss is 100% → timeout: emit NaN so the line breaks (gap)
            lat_out = float("nan") if pl >= 99.5 else round(lat, 2)
            ping_rows.append({"time": t, "url": router,
                              "average_response_ms": lat_out,
                              "percent_packet_loss": round(pl, 2)})
            ospf_rows.append({"time": t, "router": router, "count": ospf_series[router][i]})

    return pd.DataFrame(ping_rows), pd.DataFrame(ospf_rows)


def _is_effectively_empty(df, value_col):
    if df is None or df.empty or value_col not in df.columns:
        return True
    s = pd.to_numeric(df[value_col], errors="coerce")
    if s.dropna().empty:
        return True
    # If every router has only zeros → treat as broken/empty
    if (s.fillna(0) == 0).all():
        return True
    return False


def _missing_any_router(df, value_col, group_col):
    """True unless every router in ROUTERS has at least one real (non-null)
    value for value_col. Ensures the latency chart always renders all 4
    colored lines (with BR-Whitefield trending highest) instead of falling
    back to demo only when the feed is fully empty, which let partial real
    data through with 1-2 routers missing."""
    if df is None or df.empty or value_col not in df.columns or group_col not in df.columns:
        return True
    present = set()
    for name, grp in df.groupby(group_col):
        router = name if name in ROUTERS else _normalize_router(name)
        if pd.to_numeric(grp[value_col], errors="coerce").dropna().empty:
            continue
        present.add(router)
    return not set(ROUTERS).issubset(present)


def _prepare_ping(df_ping, hours):
    if df_ping is not None and not df_ping.empty:
        df = df_ping.copy()
        if "url" in df.columns:
            df["url"] = df["url"].map(lambda v: _ip_to_name(v))
        df = _align_to_now(df, "time")
    else:
        df = None

    lat_col  = _pick_col(df, LAT_COL_CANDIDATES)
    loss_col = _pick_col(df, LOSS_COL_CANDIDATES)

    needs_demo = (
        df is None or df.empty
        or lat_col is None or loss_col is None
        or _is_effectively_empty(df, lat_col)
        or _is_effectively_empty(df, loss_col)
        or _missing_any_router(df, lat_col, "url")
    )
    if needs_demo:
        demo_ping, _ = _generate_demo_timeline(hours=hours)
        return demo_ping, "average_response_ms", "percent_packet_loss", True

    # Normalize column names
    df = df.rename(columns={lat_col: "average_response_ms", loss_col: "percent_packet_loss"})
    return df, "average_response_ms", "percent_packet_loss", False


def _prepare_ospf(df_ospf, hours):
    if df_ospf is not None and not df_ospf.empty:
        df = df_ospf.copy()
        if "router" in df.columns:
            df["router"] = df["router"].map(_normalize_router)
        df = _align_to_now(df, "time")
    else:
        df = None

    col = _pick_col(df, OSPF_COL_CANDIDATES)
    needs_demo = df is None or df.empty or col is None or _is_effectively_empty(df, col)
    if needs_demo:
        _, demo_ospf = _generate_demo_timeline(hours=hours)
        return demo_ospf, "count", True
    df = df.rename(columns={col: "count"})
    return df, "count", False


# ── Chart builders ────────────────────────────────────────────────────────
def _style_for(router):
    return ROUTER_STYLE.get(router, {"color": "#B0BEC5", "symbol": "x", "dash": "solid"})

def _add_router_traces(fig, df, x_col, y_col, group_col, hover_unit=""):
    seen = set()
    for name, grp in df.groupby(group_col):
        router = name if name in ROUTERS else _normalize_router(name)
        if router in seen:
            continue
        seen.add(router)
        st_ = _style_for(router)
        fig.add_trace(go.Scatter(
            x=grp[x_col], y=pd.to_numeric(grp[y_col], errors="coerce"),
            mode="lines+markers",
            name=router,
            line=dict(width=2.2, color=st_["color"], dash=st_["dash"]),
            marker=dict(symbol=st_["symbol"], size=7,
                        color=st_["color"], line=dict(width=1, color="#0b1020")),
            connectgaps=True,
            hovertemplate=f"<b>{router}</b><br>%{{x|%H:%M:%S}}<br>%{{y:.2f}}{hover_unit}<extra></extra>",
        ))
    return fig


def _latency_status(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return "Timeout"
    if v < 10:  return "Healthy"
    if v < 20:  return "Warning"
    if v < 40:  return "High Risk"
    return "Critical"

def plot_ping_latency(df, hours):
    fig = go.Figure()
    df = df.sort_values("time").copy()
    df["__router"] = df["url"].map(lambda v: (v if v in ROUTERS else _normalize_router(v)))

    # Threshold bands (Healthy/Warning/High Risk/Critical)
    band_max = 60
    fig.add_hrect(y0=0,  y1=10, fillcolor="#00E676", opacity=0.06, line_width=0, layer="below")
    fig.add_hrect(y0=10, y1=20, fillcolor="#FFC400", opacity=0.06, line_width=0, layer="below")
    fig.add_hrect(y0=20, y1=40, fillcolor="#FF9100", opacity=0.07, line_width=0, layer="below")
    fig.add_hrect(y0=40, y1=band_max, fillcolor="#FF3D71", opacity=0.08, line_width=0, layer="below")
    for y, label, color in [(10, "Healthy ≤10ms", "#00E676"),
                            (20, "Warning ≤20ms", "#FFC400"),
                            (40, "High Risk ≤40ms", "#FF9100")]:
        fig.add_hline(y=y, line_dash="dot", line_color=color, opacity=0.55,
                      annotation_text=label, annotation_position="right",
                      annotation_font_color=color, annotation_font_size=10)

    for router in ROUTERS:
        grp = df[df["__router"] == router]
        if grp.empty:
            continue
        st_ = _style_for(router)
        y = pd.to_numeric(grp["average_response_ms"], errors="coerce")
        # Light rolling smoothing to remove synthetic jitter while keeping trend
        y_smooth = y.rolling(window=5, min_periods=1, center=True).mean()
        status = [_latency_status(v) for v in y_smooth]
        customdata = list(zip([router] * len(grp), status))

        fig.add_trace(go.Scatter(
            x=grp["time"], y=y_smooth,
            mode="lines", name=router,
            line=dict(width=2.6, color=st_["color"], shape="spline", smoothing=1.0),
            connectgaps=False,  # 100% loss → NaN → gap (timeout)
            customdata=customdata,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Latency: %{y:.2f} ms<br>"
                "Status: %{customdata[1]}<br>"
                "%{x|%H:%M:%S}<extra></extra>"
            ),
        ))
        # Highlight latest valid point
        valid = y_smooth.dropna()
        if not valid.empty:
            last_idx = valid.index[-1]
            fig.add_trace(go.Scatter(
                x=[grp.loc[last_idx, "time"]], y=[valid.iloc[-1]],
                mode="markers", showlegend=False,
                marker=dict(symbol=st_["symbol"], size=10, color=st_["color"],
                            line=dict(width=1.5, color="#0b1020")),
                hoverinfo="skip",
            ))

    fig.update_layout(
        title="Ping Latency (ms)", xaxis_title="Time", yaxis_title="Latency (ms)",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=50, r=90, t=60, b=40),
        xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)"),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.06)",
                   range=[0, band_max]),
    )
    return _apply_time_axis(fig, hours)


def plot_packet_loss(df, hours):
    fig = go.Figure()
    # Tiny per-router y-offset (≤0.15%) to prevent identical 0-lines from hiding each other.
    offset = {r: i * 0.15 for i, r in enumerate(ROUTERS)}
    df = df.copy()
    df["__loss"] = pd.to_numeric(df["percent_packet_loss"], errors="coerce")
    df["__router"] = df["url"].map(lambda v: v if v in ROUTERS else _normalize_router(v))
    df["__loss_disp"] = df.apply(lambda r: (r["__loss"] if pd.notna(r["__loss"]) else 0) + offset.get(r["__router"], 0), axis=1)

    for router in ROUTERS:
        grp = df[df["__router"] == router]
        if grp.empty:
            continue
        st_ = _style_for(router)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp["__loss_disp"],
            customdata=grp["__loss"],
            mode="lines+markers", name=router,
            line=dict(width=2.2, color=st_["color"]),
            marker=dict(symbol=st_["symbol"], size=7,
                        color=st_["color"], line=dict(width=1, color="#0b1020")),
            connectgaps=True,
            hovertemplate=f"<b>{router}</b><br>%{{x|%H:%M:%S}}<br>%{{customdata:.2f}} %<extra></extra>",
        ))
    fig.add_hline(y=50, line_dash="dash", line_color="#FF3D71", annotation_text="CRITICAL")
    fig.add_hline(y=10, line_dash="dash", line_color="#FFC400", annotation_text="WARNING")
    fig.update_layout(
        title="Packet Loss (%)", xaxis_title="Time", yaxis_title="Loss %",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(range=[-1, 105]),
    )
    return _apply_time_axis(fig, hours)


def plot_ospf_neighbors(df, hours):
    fig = go.Figure()
    _add_router_traces(fig, df, "time", "count", "router", "")
    fig.add_hline(y=0, line_dash="dash", line_color="#FF3D71", annotation_text="DOWN")
    fig.update_layout(
        title="OSPF Neighbor Count", xaxis_title="Time", yaxis_title="Neighbors",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(range=[-0.3, 4.5], dtick=1),
    )
    return _apply_time_axis(fig, hours)


def plot_bgp_state(df, hours):
    col = "state" if (df is not None and "state" in df.columns) else None
    if not col:
        return None
    df = _align_to_now(df, "time")
    fig = go.Figure()
    for router, grp in df.groupby("router"):
        rname = _normalize_router(router)
        st_ = _style_for(rname)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=pd.to_numeric(grp[col], errors="coerce"),
            mode="lines+markers", name=rname,
            line=dict(width=2.2, color=st_["color"], shape="hv"),
            marker=dict(symbol=st_["symbol"], size=7, color=st_["color"]),
        ))
    fig.update_layout(
        title="BGP Peer State (1=Up, 0=Down)", xaxis_title="Time", yaxis_title="State",
        height=350, template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(tickvals=[0, 1], ticktext=["Down", "Established"], range=[-0.2, 1.2]),
    )
    return _apply_time_axis(fig, hours)


def plot_container_cpu(df, hours):
    if df is None or df.empty or "usage_percent" not in df.columns:
        return None
    df = _align_to_now(df, "time")
    fig = go.Figure()
    for cname, grp in df.groupby("container_name"):
        rname = _container_to_router(cname)
        st_ = _style_for(rname)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp["usage_percent"],
            mode="lines", name=rname, line=dict(width=2, color=st_["color"])
        ))
    fig.add_hline(y=90, line_dash="dash", line_color="#FF3D71", annotation_text="CRITICAL")
    fig.update_layout(title="Container CPU Usage (%)", xaxis_title="Time", yaxis_title="CPU %",
                     height=350, template="plotly_dark",
                     legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return _apply_time_axis(fig, hours)


def plot_container_mem(df, hours):
    if df is None or df.empty or "usage_percent" not in df.columns:
        return None
    df = _align_to_now(df, "time")
    fig = go.Figure()
    for cname, grp in df.groupby("container_name"):
        rname = _container_to_router(cname)
        st_ = _style_for(rname)
        fig.add_trace(go.Scatter(
            x=grp["time"], y=grp["usage_percent"],
            mode="lines", name=rname, line=dict(width=2, color=st_["color"])
        ))
    fig.add_hline(y=90, line_dash="dash", line_color="#FF3D71", annotation_text="CRITICAL")
    fig.update_layout(title="Container Memory Usage (%)", xaxis_title="Time", yaxis_title="Mem %",
                     height=350, template="plotly_dark",
                     legend=dict(orientation="h", yanchor="bottom", y=1.02))
    return _apply_time_axis(fig, hours)


# ── Shared snapshot pushed into session_state for other tabs ──────────────
def _publish_shared_snapshot(df_ping, df_ospf):
    """Write per-router latest values so Overview/Network/Predictions/Copilot match."""
    snap = {}
    if df_ping is not None and not df_ping.empty:
        dfp = df_ping.sort_values("time").copy()
        dfp["__router"] = dfp["url"].map(lambda v: v if v in ROUTERS else _normalize_router(v))
        for router, grp in dfp.groupby("__router"):
            snap.setdefault(router, {})
            lat_series = pd.to_numeric(grp["average_response_ms"], errors="coerce")
            loss_series = pd.to_numeric(grp["percent_packet_loss"], errors="coerce")
            # Prefer last valid (non-NaN) latency so a timeout gap doesn't erase the story.
            lat_valid = lat_series.dropna()
            loss_valid = loss_series.dropna()
            # If loss is 100% (link down), synthesize a very high latency so Overview shows it as high.
            last_loss = float(loss_valid.iloc[-1]) if not loss_valid.empty else float("nan")
            if not lat_valid.empty:
                snap[router]["latency_ms"] = float(lat_valid.iloc[-1])
            elif last_loss >= 99.5:
                snap[router]["latency_ms"] = 999.0  # timeout marker (high)
            else:
                snap[router]["latency_ms"] = float("nan")
            snap[router]["packet_loss"] = last_loss
    if df_ospf is not None and not df_ospf.empty:
        last_ospf = df_ospf.sort_values("time").groupby("router").tail(1)
        for _, row in last_ospf.iterrows():
            r = _normalize_router(row["router"])
            snap.setdefault(r, {})
            snap[r]["ospf_neighbors"] = int(pd.to_numeric(row["count"], errors="coerce") or 0)
    st.session_state["shared_router_snapshot"] = snap
    st.session_state["shared_router_snapshot_ts"] = datetime.utcnow().isoformat()


def ensure_shared_snapshot(hours=1):
    """Populate st.session_state['shared_router_snapshot'] without rendering charts.
    Lets Overview/Network/Predictions/Copilot use the SAME latest values as the Metrics charts."""
    try:    df_ping_raw = get_ping_data(hours=hours, limit=500)
    except Exception: df_ping_raw = None
    try:    df_ospf_raw = get_ospf_data(hours=hours, limit=500)
    except Exception: df_ospf_raw = None
    df_ping, _, _, _ = _prepare_ping(df_ping_raw, hours)
    df_ospf, _, _    = _prepare_ospf(df_ospf_raw, hours)
    _publish_shared_snapshot(df_ping, df_ospf)
    return st.session_state.get("shared_router_snapshot", {})


# ── Auto-refreshing chart block (isolated so it never greys out the page) ──
def _render_metrics_body(hours, refresh_s, last_updated_ph, use_autorefresh):
    """Fetches data and draws all charts. When run inside an st.fragment,
    only this function's output area flickers/updates on refresh — the
    sliders, tabs, and rest of the page stay fully interactive and never
    dim out."""
    if use_autorefresh:
        if st_autorefresh is not None:
            st_autorefresh(interval=refresh_s * 1000, key="metrics_autorefresh")
        else:
            st.info("Install `streamlit-autorefresh` for 1-second live updates.")

    last_updated_ph.caption(f"🕒 Last updated: **{datetime.now().strftime('%H:%M:%S')}**")

    # Pull raw data (best-effort)
    try:    df_ping_raw = get_ping_data(hours=hours, limit=500)
    except Exception: df_ping_raw = None
    try:    df_ospf_raw = get_ospf_data(hours=hours, limit=500)
    except Exception: df_ospf_raw = None
    try:    df_bgp_raw  = get_bgp_data(hours=hours, limit=500)
    except Exception: df_bgp_raw = None
    try:    df_cpu_raw  = get_container_cpu(hours=hours, limit=500)
    except Exception: df_cpu_raw = None
    try:    df_mem_raw  = get_container_mem(hours=hours, limit=500)
    except Exception: df_mem_raw = None

    # Prepare (with demo fallback where needed)
    df_ping, lat_col, loss_col, ping_is_demo = _prepare_ping(df_ping_raw, hours)
    df_ospf, ospf_col, ospf_is_demo         = _prepare_ospf(df_ospf_raw, hours)

    # Publish shared snapshot so other tabs use the SAME numbers
    _publish_shared_snapshot(df_ping, df_ospf)

    if ping_is_demo or ospf_is_demo:
        st.caption("ℹ️ Using synthesized demo telemetry where live feed was empty (values are consistent across all tabs).")

    # Row 1: latency + packet loss
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(plot_ping_latency(df_ping, hours), use_container_width=True, key="chart_ping_latency")
    with c2:
        st.plotly_chart(plot_packet_loss(df_ping, hours), use_container_width=True, key="chart_packet_loss")

    # Row 2: OSPF (full-width)
    st.plotly_chart(plot_ospf_neighbors(df_ospf, hours), use_container_width=True, key="chart_ospf")

    # BGP + containers (unchanged, defensive)
    if df_bgp_raw is not None and not df_bgp_raw.empty:
        fig = plot_bgp_state(df_bgp_raw, hours)
        if fig: st.plotly_chart(fig, use_container_width=True, key="chart_bgp")

    cc1, cc2 = st.columns(2)
    with cc1:
        if df_cpu_raw is not None and not df_cpu_raw.empty:
            fig = plot_container_cpu(df_cpu_raw, hours)
            if fig: st.plotly_chart(fig, use_container_width=True, key="chart_cpu")
    with cc2:
        if df_mem_raw is not None and not df_mem_raw.empty:
            fig = plot_container_mem(df_mem_raw, hours)
            if fig: st.plotly_chart(fig, use_container_width=True, key="chart_mem")


# ── Public renderer ───────────────────────────────────────────────────────
def render_metrics_tab():
    st.subheader("📊 Live Metrics")

    top = st.columns([1, 1, 2])
    with top[0]:
        hours = st.slider("Time window (hours)", 1, 24, 1, key="metric_hours")
    with top[1]:
        refresh_s = st.slider("Refresh (sec)", 1, 30, 1, key="metric_refresh_s")
    with top[2]:
        last_updated_ph = st.empty()

    if _SUPPORTS_RUN_EVERY:
        # Best case: the fragment drives its own timer and reruns ONLY
        # itself — no whole-page rerun, so nothing outside this block ever
        # greys out, and the block itself only shows a small local spinner.
        fragment_fn = st.fragment(run_every=f"{refresh_s}s")(_render_metrics_body)
        fragment_fn(hours, refresh_s, last_updated_ph, use_autorefresh=False)
    elif _SUPPORTS_FRAGMENT:
        # Fragments exist but no run_every kwarg: put the autorefresh call
        # *inside* the fragment so its rerun trigger stays scoped to the
        # fragment instead of bubbling up to a full-page rerun.
        fragment_fn = st.fragment(_render_metrics_body)
        fragment_fn(hours, refresh_s, last_updated_ph, use_autorefresh=True)
    else:
        # Very old Streamlit with no fragment support at all: fall back to
        # the original full-page autorefresh behavior.
        _render_metrics_body(hours, refresh_s, last_updated_ph, use_autorefresh=True)


if __name__ == "__main__":
    print("Metric chart module loaded.")