"""
Netwroxia Dashboard — Live Event Feed
Reads InfluxDB and generates terminal-style NOC events.
Detects spikes, drops, and state changes in real-time.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st   # ← ADD THIS
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict
from utils.influx_client import get_ping_data, get_ospf_data, get_bgp_data


def _time_ago(dt) -> str:
    """Human-readable relative time."""
    if pd.isna(dt):
        return "?"
    diff = datetime.utcnow() - pd.to_datetime(dt).replace(tzinfo=None)
    secs = int(diff.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    elif secs < 3600:
        return f"{secs//60}m ago"
    else:
        return f"{secs//3600}h ago"


def _is_fresh(dt, seconds: int = 120) -> bool:
    """Check if event happened in last N seconds."""
    if pd.isna(dt):
        return False
    diff = datetime.utcnow() - pd.to_datetime(dt).replace(tzinfo=None)
    return diff.total_seconds() < seconds


def detect_events(hours: int = 1) -> List[Dict]:
    """
    Scan InfluxDB metrics and generate human-readable NOC events.
    Returns list of: {time, severity, message, router, fresh}
    """
    events = []

    # ── Ping Events ──
    df_ping = get_ping_data(hours=hours, limit=500)
    if df_ping is not None and not df_ping.empty and "url" in df_ping.columns:
        df_ping = df_ping.sort_values("time")
        for url, grp in df_ping.groupby("url"):
            router = _ip_to_router(url)
            if len(grp) < 2:
                continue
            latest = grp.iloc[-1]
            prev = grp.iloc[-2]
            
            loss_now = float(latest.get("percent_packet_loss", 0) or 0)
            loss_prev = float(prev.get("percent_packet_loss", 0) or 0)
            lat_now = float(latest.get("average_response_ms", 0) or 0)
            lat_prev = float(prev.get("average_response_ms", 0) or 0)
            
            # Packet loss spike
            if loss_now >= 50 and loss_prev < 50:
                events.append({
                    "time": latest["time"],
                    "severity": "CRITICAL",
                    "message": f"{router} packet loss SPIKED to {loss_now:.0f}%",
                    "router": router,
                })
            elif loss_now == 100 and loss_prev < 100:
                events.append({
                    "time": latest["time"],
                    "severity": "CRITICAL",
                    "message": f"{router} LINK DOWN — 100% packet loss",
                    "router": router,
                })
            elif loss_now == 0 and loss_prev > 0:
                events.append({
                    "time": latest["time"],
                    "severity": "HEALTHY",
                    "message": f"{router} link RECOVERED — 0% loss",
                    "router": router,
                })
            
            # Latency spike
            if lat_prev > 0 and lat_now > lat_prev * 5 and lat_now > 10:
                events.append({
                    "time": latest["time"],
                    "severity": "WARNING",
                    "message": f"{router} latency SPIKED to {lat_now:.1f}ms",
                    "router": router,
                })

    # ── OSPF Events ──
    df_ospf = get_ospf_data(hours=hours, limit=500)
    if df_ospf is not None and not df_ospf.empty and "router" in df_ospf.columns:
        df_ospf = df_ospf.sort_values("time")
        for router_raw, grp in df_ospf.groupby("router"):
            router = _normalize_router(router_raw)
            if len(grp) < 2:
                continue
            latest = grp.iloc[-1]
            prev = grp.iloc[-2]
            count_now = int(latest.get("count", 0) or 0)
            count_prev = int(prev.get("count", 0) or 0)
            
            if count_now < count_prev:
                events.append({
                    "time": latest["time"],
                    "severity": "CRITICAL",
                    "message": f"{router} OSPF neighbor LOST ({count_prev}→{count_now})",
                    "router": router,
                })
            elif count_now > count_prev:
                events.append({
                    "time": latest["time"],
                    "severity": "HEALTHY",
                    "message": f"{router} OSPF neighbor RESTORED ({count_prev}→{count_now})",
                    "router": router,
                })

    # ── BGP Events ──
    df_bgp = get_bgp_data(hours=hours, limit=500)
    if df_bgp is not None and not df_bgp.empty and "router" in df_bgp.columns:
        df_bgp = df_bgp.sort_values("time")
        for router_raw, grp in df_bgp.groupby("router"):
            router = _normalize_router(router_raw)
            if len(grp) < 2:
                continue
            latest = grp.iloc[-1]
            prev = grp.iloc[-2]
            state_now = int(latest.get("state", -1) or -1)
            state_prev = int(prev.get("state", -1) or -1)
            
            if state_now != 1 and state_prev == 1:
                events.append({
                    "time": latest["time"],
                    "severity": "CRITICAL",
                    "message": f"{router} BGP peer WENT DOWN",
                    "router": router,
                })
            elif state_now == 1 and state_prev != 1:
                events.append({
                    "time": latest["time"],
                    "severity": "HEALTHY",
                    "message": f"{router} BGP peer CAME UP",
                    "router": router,
                })

    # Sort by time descending, keep last 30
    events.sort(key=lambda x: x["time"], reverse=True)
    return events[:30]


def render_event_feed():
    """Render the live event feed in Streamlit."""
    st.subheader("📡 Live Event Feed")
    
    events = detect_events(hours=1)
    
    if not events:
        st.info("No events in the last hour. Network is stable.")
        return

    # CSS for terminal look
    st.markdown("""
    <style>
    .noc-event {
        font-family: 'Courier New', monospace;
        font-size: 13px;
        padding: 6px 10px;
        margin: 2px 0;
        border-radius: 4px;
        border-left: 3px solid;
    }
    .noc-event-critical {
        background-color: rgba(255, 68, 68, 0.1);
        border-left-color: #ff4444;
        color: #ff8888;
    }
    .noc-event-warning {
        background-color: rgba(255, 170, 0, 0.1);
        border-left-color: #ffaa00;
        color: #ffcc66;
    }
    .noc-event-healthy {
        background-color: rgba(0, 204, 102, 0.1);
        border-left-color: #00cc66;
        color: #66ff99;
    }
    .noc-fresh {
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    .noc-time {
        color: #888888;
        font-size: 11px;
    }
    </style>
    """, unsafe_allow_html=True)

    for ev in events:
        sev = ev["severity"].lower()
        fresh = _is_fresh(ev["time"], seconds=120)
        fresh_badge = " 🆕" if fresh else ""
        time_str = _time_ago(ev["time"])
        
        st.markdown(
            f'<div class="noc-event noc-event-{sev} {"noc-fresh" if fresh else ""}">'
            f'<span class="noc-time">[{time_str}]</span> '
            f'<b>{ev["severity"]}</b>: {ev["message"]}{fresh_badge}'
            f'</div>',
            unsafe_allow_html=True
        )


def render_mini_sparkline(router: str, metric: str = "packet_loss"):
    """Render a tiny sparkline for a router card."""
    df = get_ping_data(hours=1, limit=50)
    if df is None or df.empty or "url" not in df.columns:
        return None
    
    # Filter to this router
    ip = _router_to_ip(router)
    df_r = df[df["url"] == ip].sort_values("time").tail(15)
    if len(df_r) < 2:
        return None
    
    import plotly.graph_objects as go
    
    col = "percent_packet_loss" if metric == "packet_loss" else "average_response_ms"
    if col not in df_r.columns:
        return None
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(df_r))),
        y=df_r[col],
        mode="lines",
        fill="tozeroy",
        line=dict(width=1.5, color="#ff4444" if metric == "packet_loss" else "#00ccff"),
        fillcolor="rgba(255, 68, 68, 0.15)" if metric == "packet_loss" else "rgba(0, 204, 255, 0.15)"
    ))
    fig.update_layout(
        height=50,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


# ── Helpers ─────────────────────────────────────────────
def _ip_to_router(ip: str) -> str:
    mapping = {
        "172.20.20.3": "HO-Chennai",
        "172.20.20.4": "ZO-Bengaluru",
        "172.20.20.5": "BR-Koramangala",
        "172.20.20.7": "BR-Whitefield",
    }
    return mapping.get(str(ip), str(ip))


def _router_to_ip(router: str) -> str:
    mapping = {
        "HO-Chennai": "172.20.20.3",
        "ZO-Bengaluru": "172.20.20.4",
        "BR-Koramangala": "172.20.20.5",
        "BR-Whitefield": "172.20.20.7",
    }
    return mapping.get(router, "")


def _normalize_router(name: str) -> str:
    mapping = {
        "ho-chennai": "HO-Chennai",
        "zo-bengaluru": "ZO-Bengaluru",
        "br-koramangala": "BR-Koramangala",
        "br-whitefield": "BR-Whitefield",
    }
    return mapping.get(str(name).lower().strip(), str(name).title())


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Live feed module loaded.")
    evs = detect_events(hours=1)
    print(f"  Found {len(evs)} events")
    for e in evs[:5]:
        print(f"  [{e['severity']}] {e['message']} ({_time_ago(e['time'])})")
