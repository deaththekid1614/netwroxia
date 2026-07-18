"""
Netwroxia Dashboard — Alert Card Component
Renders ML prediction cards from Stage 3 latest_prediction.json.
"""
import streamlit as st
import json
from pathlib import Path

PROJECT_ROOT = Path("/home/death-kid/IDE/netwroxia")
PREDICTION_PATH = PROJECT_ROOT / "ml" / "inference" / "latest_prediction.json"


def load_prediction() -> dict:
    if not PREDICTION_PATH.exists():
        return {}
    try:
        with open(PREDICTION_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def render_alert_card(pred: dict):
    """Render a single router prediction as an alert card."""
    router = pred.get("router", "Unknown")
    xgb = pred.get("xgboost", {})
    lstm = pred.get("lstm_forecast", {})
    combined = pred.get("combined_alert", "NORMAL")
    top_feature = pred.get("top_feature", "N/A")
    raw = pred.get("raw_metrics", {})

    # Status color
    fault = xgb.get("predicted_fault", False)
    prob = xgb.get("fault_probability", 0.0)
    conf = xgb.get("confidence", "LOW")

    if combined == "CRITICAL" or (lstm.get("predicted_future_fault") and lstm.get("future_fault_probability", 0) > 0.8):
        color = "#ff4444"
        border = "2px solid #ff4444"
        icon = "🚨"
    elif combined == "SUSPECTED_FAULT" or fault:
        color = "#ffaa00"
        border = "2px solid #ffaa00"
        icon = "⚠️"
    else:
        color = "#00cc66"
        border = "2px solid #00cc66"
        icon = "✅"

    with st.container():
        st.markdown(f"""
        <div style="
            border: {border};
            border-radius: 8px;
            padding: 12px 16px;
            margin-bottom: 12px;
            background-color: rgba(0,0,0,0.2);
        ">
            <h4 style="color: {color}; margin: 0 0 8px 0;">
                {icon} {router}
            </h4>
            <p style="margin: 4px 0; font-size: 0.9rem;">
                <b>Combined Alert:</b> <span style="color: {color};">{combined}</span>
                &nbsp;|&nbsp;
                <b>Confidence:</b> {conf}
            </p>
        </div>
        """, unsafe_allow_html=True)

        # XGBoost bar
        st.progress(min(float(prob), 1.0))
        st.caption(f"XGBoost Fault Probability: {prob*100:.1f}% | Status: {xgb.get('status', 'UNKNOWN')}")

        # LSTM forecast
        if lstm:
            future_prob = lstm.get("future_fault_probability", 0.0)
            tti = lstm.get("time_to_impact", "N/A")
            st.progress(min(float(future_prob), 1.0))
            st.caption(f"LSTM Future Prob: {future_prob*100:.1f}% | TTI: {tti} | {lstm.get('status', 'N/A')}")

        # Raw metrics
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Latency", f"{raw.get('latency_ms', 0):.2f} ms")
        with c2:
            st.metric("Packet Loss", f"{raw.get('packet_loss_pct', 0):.1f}%")
        with c3:
            st.metric("OSPF Neighbors", f"{raw.get('ospf_neighbors', 0)}")
        with c4:
            bgp = raw.get("bgp_established", False)
            st.metric("BGP", "UP" if bgp else "DOWN")

        st.caption(f"Top Feature: **{top_feature}**")
        st.divider()


def render_all_alerts():
    """Render alert cards for all routers in the prediction file."""
    data = load_prediction()
    predictions = data.get("predictions", [])

    if not predictions:
        st.info("No predictions available. Run the pipeline first.")
        return

    st.subheader(f"🔮 Predictions | Overall: {data.get('overall_status', 'UNKNOWN')} | "
                 f"Routers at Risk: {data.get('routers_at_risk', 0)}")

    for pred in predictions:
        render_alert_card(pred)


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    data = load_prediction()
    print(f"Loaded prediction: {data.get('timestamp', 'N/A')}")
    print(f"Overall status: {data.get('overall_status', 'N/A')}")
    print(f"Routers at risk: {data.get('routers_at_risk', 0)}")
    for p in data.get("predictions", []):
        print(f"  {p.get('router')}: {p.get('combined_alert')} "
              f"(XGB: {p.get('xgboost',{}).get('fault_probability',0)*100:.1f}%)")
