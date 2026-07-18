"""
Netwroxia Dashboard — Clean Professional NOC
No HTML hacks. No broken wrappers. Just clean Streamlit.
"""
import streamlit as st
import sys
from pathlib import Path
from datetime import datetime

DASHBOARD_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(DASHBOARD_DIR))

from utils.influx_client import get_latest_by_router
from utils.pipeline_runner import run_pipeline, get_pipeline_status, get_prediction_json, get_copilot_json
from components.alert_card import render_all_alerts
from components.metric_chart import render_metrics_tab
from components.topology_graph import render_topology_tab
from components.live_feed import render_event_feed

# ── Page Config ─────────────────────────────────────────
st.set_page_config(
    page_title="Netwroxia NOC",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Header ──────────────────────────────────────────────
st.title("🏦 Netwroxia NOC")
st.caption("Air-Gapped Predictive AI Copilot for Banking Networks | IBM Z Datathon 2026")

status = get_pipeline_status()
overall = status.get("overall_status", "UNKNOWN")
risk = status.get("routers_at_risk", 0)

# Status bar
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("System Status", overall, delta=None)
with col2:
    st.metric("Routers at Risk", risk, delta=None)
with col3:
    st.metric("Last Update", datetime.now().strftime("%H:%M:%S"), delta=None)
with col4:
    st.metric("Prediction", "Available" if status.get("prediction_exists") else "None", delta=None)
with col5:
    st.metric("Copilot", "Available" if status.get("copilot_exists") else "None", delta=None)

st.divider()

# ── RUN PIPELINE ────────────────────────────────────────
if st.button("🚀 RUN PIPELINE", type="primary"):
    with st.spinner("Running pipeline... (~60 seconds)"):
        ok, results = run_pipeline(verbose=False)
    
    if ok:
        st.success("✅ Pipeline complete! Refreshing...")
        st.balloons()
        try:
            st.rerun()
        except Exception:
            try:
                st.experimental_rerun()
            except Exception:
                st.info("Please refresh the page manually.")
    else:
        st.error("❌ Pipeline failed.")
        for r in results:
            if not r["success"]:
                st.code(f"{r['name']}: {r.get('error', 'Unknown')[:200]}")

st.divider()

# ── Load Data ───────────────────────────────────────────
snapshot = get_latest_by_router()
pred_data = get_prediction_json()
predictions = {p.get("router"): p for p in pred_data.get("predictions", [])}
copilot_data = get_copilot_json()

# Defensive copilot parsing
responses = []
if copilot_data:
    if isinstance(copilot_data, list):
        responses = copilot_data
    elif isinstance(copilot_data, dict):
        if "responses" in copilot_data and isinstance(copilot_data["responses"], list):
            responses = copilot_data["responses"]
        elif "results" in copilot_data and isinstance(copilot_data["results"], list):
            responses = copilot_data["results"]
        elif "data" in copilot_data and isinstance(copilot_data["data"], list):
            responses = copilot_data["data"]
        elif "predicted_issue" in copilot_data:
            responses = [copilot_data]

# ── Tabs ────────────────────────────────────────────────
tab_overview, tab_network, tab_predictions, tab_copilot, tab_metrics = st.tabs([
    "🏠 Overview", "🌐 Network", "🔮 Predictions", "🤖 Copilot", "📊 Metrics"
])

# ── Overview Tab ────────────────────────────────────────
with tab_overview:
    # Router cards
    st.subheader("🖥️ Router Health")
    
    for router in ["HO-Chennai", "ZO-Bengaluru", "BR-Koramangala", "BR-Whitefield"]:
        metrics = snapshot.get(router, {})
        pred = predictions.get(router, {})
        xgb = pred.get("xgboost", {})
        
        fault_prob = xgb.get("fault_probability", 0.0)
        pkt_loss = metrics.get("packet_loss_pct", 0.0)
        ospf = metrics.get("ospf_neighbors", 0)
        bgp = metrics.get("bgp_established", False)
        lat = metrics.get("latency_ms", 0.0)
        
        # Determine status
        if pkt_loss >= 50 or fault_prob >= 0.7:
            status_label = "🔴 CRITICAL"
            status_color = "red"
        elif fault_prob >= 0.3 or pkt_loss >= 10:
            status_label = "🟡 WARNING"
            status_color = "orange"
        else:
            status_label = "🟢 HEALTHY"
            status_color = "green"
        
        with st.container():
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 1, 1, 1])
            with c1:
                st.markdown(f"**{router}**  \n<span style='color:{status_color};font-size:12px;'>{status_label}</span>", unsafe_allow_html=True)
            with c2:
                st.metric("Latency", f"{lat:.2f} ms")
            with c3:
                st.metric("Loss", f"{pkt_loss:.1f}%")
            with c4:
                st.metric("OSPF", str(ospf))
            with c5:
                st.metric("BGP", "UP" if bgp else "DOWN")
            with c6:
                st.metric("Fault %", f"{fault_prob*100:.1f}%")
            st.divider()
    
    # Event feed
    st.subheader("📡 Live Event Feed")
    render_event_feed()
    
    # Copilot summary
    st.subheader("🤖 Latest Copilot Insight")
    if responses:
        r = responses[0]
        st.info(
            f"**{r.get('predicted_issue', 'No active issues')}**\n\n"
            f"🎯 {str(r.get('root_cause', 'N/A'))[:200]}...\n\n"
            f"🔧 **Quick Fix:** {r.get('quick_fix', 'N/A')}\n\n"
            f"🛠️ **Deep Fix:** {r.get('deep_fix', 'N/A')}"
        )
    else:
        st.info("No copilot data available. Click **RUN PIPELINE** to generate insights.")

# ── Network Tab ─────────────────────────────────────────
with tab_network:
    render_topology_tab()

# ── Predictions Tab ─────────────────────────────────────
with tab_predictions:
    render_all_alerts()

# ── Copilot Tab ─────────────────────────────────────────
with tab_copilot:
    st.subheader("🤖 Full Copilot Analysis")
    
    if responses:
        for i, resp in enumerate(responses):
            title = resp.get("predicted_issue", f"Analysis {i+1}")
            urgency = resp.get("urgency", "N/A")
            
            with st.expander(f"🚨 {title} — {urgency}", expanded=(i==0)):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Confidence:** `{resp.get('confidence', 'N/A')}`")
                    st.markdown(f"**Urgency:** `{urgency}`")
                    st.markdown(f"**Affected Users:** `{resp.get('affected_users', 'N/A')}`")
                    st.markdown(f"**Time to Impact:** `{resp.get('time_to_impact_min', 'N/A')} min`")
                with c2:
                    sites = resp.get("affected_sites", [])
                    svcs = resp.get("affected_services", [])
                    st.markdown(f"**Affected Sites:** {', '.join(sites) if sites else 'N/A'}")
                    st.markdown(f"**Affected Services:** {', '.join(svcs) if svcs else 'N/A'}")
                
                st.markdown("**Root Cause:**")
                st.write(resp.get("root_cause", "N/A"))
                
                st.markdown("**Recommended Actions:**")
                for action in resp.get("recommended_actions", []):
                    st.markdown(f"- {action}")
                
                st.markdown(f"**Quick Fix:** `{resp.get('quick_fix', 'N/A')}`")
                st.markdown(f"**Deep Fix:** `{resp.get('deep_fix', 'N/A')}`")
                if resp.get('rbi_compliance_note'):
                    st.markdown(f"**RBI Compliance:** {resp.get('rbi_compliance_note')}")
    else:
        st.warning("No copilot responses found.")
        if copilot_data:
            with st.expander("🔍 Debug: Raw Copilot JSON Structure"):
                st.json(copilot_data)
        else:
            st.info("The copilot output file was not found. Run the pipeline first.")

# ── Metrics Tab ─────────────────────────────────────────
with tab_metrics:
    render_metrics_tab()

# ── Footer ──────────────────────────────────────────────
st.divider()
st.caption("Netwroxia v1.0 | IBM Z Datathon 2026 | Team Astro_X | 100% Air-Gapped 🏦")