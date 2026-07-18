"""
Netwroxia Dashboard — Status Badge Component
Renders 🟢🟡🔴 colored status indicators for routers.
"""
import streamlit as st

# ── Status Logic ────────────────────────────────────────
def get_status_color(fault_prob: float, packet_loss: float = 0.0) -> str:
    """
    Returns status color based on fault probability + packet loss.
    """
    if packet_loss >= 50.0 or fault_prob >= 0.7:
        return "🔴 CRITICAL"
    elif fault_prob >= 0.3 or packet_loss >= 10.0:
        return "🟡 WARNING"
    else:
        return "🟢 HEALTHY"


def get_status_css(color_label: str) -> str:
    """Returns CSS style string for the badge."""
    colors = {
        "🔴 CRITICAL": ("#ff4444", "#330000"),
        "🟡 WARNING":  ("#ffaa00", "#332200"),
        "🟢 HEALTHY":  ("#00cc66", "#003311"),
    }
    fg, bg = colors.get(color_label, ("#888888", "#222222"))
    return f"""
        <span style="
            background-color: {bg};
            color: {fg};
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: bold;
            border: 1px solid {fg};
            display: inline-block;
        ">
            {color_label}
        </span>
    """


def render_router_card(router_name: str, metrics: dict):
    """
    Render a single router status card in Streamlit.
    metrics = {
        "latency_ms": float,
        "packet_loss_pct": float,
        "ospf_neighbors": int,
        "bgp_established": bool,
        "cpu_pct": float,
        "mem_pct": float,
        "fault_probability": float,  # from prediction JSON
    }
    """
    fault_prob = metrics.get("fault_probability", 0.0)
    pkt_loss = metrics.get("packet_loss_pct", 0.0)
    status = get_status_color(fault_prob, pkt_loss)

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown(f"### {router_name}")
    with col2:
        st.markdown(get_status_css(status), unsafe_allow_html=True)

    # Metrics grid
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Latency", f"{metrics.get('latency_ms', 0):.2f} ms")
    with c2:
        st.metric("Loss", f"{metrics.get('packet_loss_pct', 0):.1f}%")
    with c3:
        st.metric("OSPF", f"{metrics.get('ospf_neighbors', 0)}")
    with c4:
        bgp = metrics.get("bgp_established", False)
        st.metric("BGP", "UP" if bgp else "DOWN", delta=None)
    with c5:
        st.metric("Fault Prob", f"{fault_prob*100:.1f}%")

    st.divider()


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Status badge module loaded.")
    print(f"  get_status_color(0.1, 0)   = {get_status_color(0.1, 0)}")
    print(f"  get_status_color(0.5, 5)   = {get_status_color(0.5, 5)}")
    print(f"  get_status_color(0.9, 100) = {get_status_color(0.9, 100)}")
