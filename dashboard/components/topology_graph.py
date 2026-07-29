"""
Netwroxia Dashboard — Topology Graph Component
Interactive NetworkX + Plotly topology map.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import networkx as nx
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path("/home/death-kid/IDE/netwroxia")
PREDICTION_PATH = PROJECT_ROOT / "ml" / "inference" / "latest_prediction.json"

# ── Topology Definition ─────────────────────────────────
NODES = {
    "HO-Chennai":     {"x": 0.5, "y": 0.9, "role": "Head Office", "icon": "🏦"},
    "ZO-Bengaluru":   {"x": 0.5, "y": 0.5, "role": "Zonal Office", "icon": "🏢"},
    "BR-Koramangala": {"x": 0.2, "y": 0.1, "role": "Branch + ATM", "icon": "🏧"},
    "BR-Whitefield":  {"x": 0.8, "y": 0.1, "role": "Branch + ATM", "icon": "🏧"},
}

EDGES = [
    ("HO-Chennai", "ZO-Bengaluru", "MPLS L3VPN"),
    ("ZO-Bengaluru", "BR-Koramangala", "Leased Line"),
    ("ZO-Bengaluru", "BR-Whitefield", "Broadband + SD-WAN"),
]


def load_prediction() -> dict:
    if not PREDICTION_PATH.exists():
        return {}
    try:
        with open(PREDICTION_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def get_node_color(router: str, predictions: list) -> str:
    """Return color based on prediction status.

    Fix: a router can be genuinely, fully down (BGP down + zero OSPF
    neighbors, or 100% packet loss) while the ML `combined_alert` still
    reads "SUSPECTED_FAULT"/"WARNING" (a probability-based label, not a
    hard state check) — which was rendering a dead router as orange
    instead of red. We now check the actual raw link state first and
    force red whenever the router is truly down, before falling back to
    the model's label.
    """
    for p in predictions:
        if p.get("router") == router:
            raw = p.get("raw_metrics", {})
            bgp_down = not raw.get("bgp_established", True)
            ospf_down = raw.get("ospf_neighbors", 1) == 0
            loss_total = raw.get("packet_loss_pct", 0) >= 100
            if (bgp_down and ospf_down) or loss_total:
                return "#ff4444"  # hard down — always red

            combined = p.get("combined_alert", "NORMAL")
            if combined == "CRITICAL" or combined == "HIGH_CONFIDENCE_FAULT":
                return "#ff4444"
            elif combined == "SUSPECTED_FAULT" or combined == "WARNING":
                return "#ffaa00"
            else:
                return "#00cc66"
    return "#888888"  # No data


def get_node_hover(router: str, predictions: list) -> str:
    """Build hover tooltip text."""
    for p in predictions:
        if p.get("router") == router:
            xgb = p.get("xgboost", {})
            lstm = p.get("lstm_forecast", {})
            raw = p.get("raw_metrics", {})
            lines = [
                f"<b>{router}</b>",
                f"Role: {NODES[router]['role']}",
                f"Status: {p.get('combined_alert', 'N/A')}",
                f"XGB Prob: {xgb.get('fault_probability', 0)*100:.1f}%",
                f"LSTM Future: {lstm.get('future_fault_probability', 0)*100:.1f}%",
                f"Latency: {raw.get('latency_ms', 0):.2f} ms",
                f"Packet Loss: {raw.get('packet_loss_pct', 0):.1f}%",
                f"OSPF Neighbors: {raw.get('ospf_neighbors', 0)}",
                f"BGP: {'UP' if raw.get('bgp_established') else 'DOWN'}",
            ]
            return "<br>".join(lines)
    return f"<b>{router}</b><br>{NODES[router]['role']}<br>No prediction data"


def build_topology_graph():
    """Build and return a Plotly figure of the network topology."""
    pred_data = load_prediction()
    predictions = pred_data.get("predictions", [])

    # Node positions and colors
    node_x, node_y, node_color, node_text, node_size = [], [], [], [], []
    for name, attrs in NODES.items():
        node_x.append(attrs["x"])
        node_y.append(attrs["y"])
        node_color.append(get_node_color(name, predictions))
        node_text.append(get_node_hover(name, predictions))
        node_size.append(45)

    # Edge traces
    edge_traces = []
    for src, dst, label in EDGES:
        x0, y0 = NODES[src]["x"], NODES[src]["y"]
        x1, y1 = NODES[dst]["x"], NODES[dst]["y"]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=3, color="#555555"),
            hoverinfo="text",
            text=f"{src} ↔ {dst}<br>{label}",
            showlegend=False
        ))
        # Edge label at midpoint
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        edge_traces.append(go.Scatter(
            x=[mx], y=[my],
            mode="text",
            text=[label],
            textposition="top center",
            textfont=dict(size=10, color="#aaaaaa"),
            hoverinfo="skip",
            showlegend=False
        ))

    # Node trace
    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        marker=dict(
            size=node_size,
            color=node_color,
            line=dict(width=2, color="#ffffff"),
            symbol="circle"
        ),
        text=[f"{NODES[n]['icon']} {n}" for n in NODES],
        textposition="top center",
        textfont=dict(size=11, color="#eeeeee"),
        hovertemplate="%{text}<extra></extra>",
        hovertext=node_text,
        showlegend=False
    )

    # Layout
    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        title=dict(
            text="🏦 State Bank of Netwroxia — Live Topology",
            font=dict(size=18, color="#ffffff"),
            x=0.5
        ),
        showlegend=False,
        hovermode="closest",
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.1, 1.1]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.1, 1.0]),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        margin=dict(l=20, r=20, t=60, b=20),
        height=500,
        dragmode="pan"
    )
    return fig


def render_topology_tab():
    """Render the topology tab in Streamlit."""
    st.subheader("🌐 Network Topology")
    fig = build_topology_graph()
    st.plotly_chart(fig, use_container_width=True, use_container_height=False)

    # Legend
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("🟢 **Healthy** — Normal operation")
    with c2:
        st.markdown("🟡 **Warning** — Elevated risk detected")
    with c3:
        st.markdown("🔴 **Critical** — Fault predicted or active")
    with c4:
        st.markdown("⚫ **No Data** — Metrics unavailable")


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Topology graph module loaded.")
    pred = load_prediction()
    print(f"  Prediction loaded: {pred.get('timestamp', 'N/A')}")
    print(f"  Routers: {[p.get('router') for p in pred.get('predictions', [])]}")
    print("  Run via Streamlit to see the graph.")