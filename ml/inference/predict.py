#!/usr/bin/env python3
"""
Netwroxia Stage 3 — predict.py
Real-time inference endpoint. Loads trained model, fetches latest metrics,
and returns structured predictions with confidence scores.

NOW WITH LSTM FORECAST: Future fault probability + Time-to-Impact (TTI)

Location: ml/inference/predict.py
"""

import numpy as np
import pandas as pd
import json
import os
import glob
import pickle
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ── PATH SETUP ──────────────────────────────────────────────────────────────
# This file is at ml/inference/predict.py
# Project root is two levels up
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

# Import fetch_metrics from ml/data/
from ml.data.fetch_metrics import (
    fetch_ping, fetch_ospf, fetch_bgp,
    fetch_container_cpu, fetch_container_mem,
    get_past_timestamp
)

# ── CONFIG ──────────────────────────────────────────────────────────────────
MODELS_DIR = os.path.join(PROJECT_ROOT, "ml", "models")
DEFAULT_HOURS = 1

# Confidence thresholds
CONFIDENCE_HIGH = 0.90
CONFIDENCE_MEDIUM = 0.70

# Feature names (must match training order)
FEATURE_NAMES = [
    "average_response_ms",
    "percent_packet_loss",
    "count",
    "state_ok",
    "cpu_percent",
    "mem_percent",
    "router_BR-Koramangala",
    "router_BR-Whitefield",
    "router_HO-Chennai",
    "router_ZO-Bengaluru",
]

ROUTERS = ["HO-Chennai", "ZO-Bengaluru", "BR-Koramangala", "BR-Whitefield"]

# LSTM Config (must match train_lstm.py)
LSTM_SEQ_LENGTH = 15
LSTM_HORIZON = 5
LSTM_FEATURES = [
    "average_response_ms",
    "percent_packet_loss",
    "latency_ma",
    "loss_ma",
    "latency_diff",
]

# ── LSTM IMPORTS (lazy — only if LSTM model found) ──────────────────────────
try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ═════════════════════════════════════════════════════════════════════════════
# LSTM MODEL CLASS (must match train_lstm.py exactly)
# ═════════════════════════════════════════════════════════════════════════════
class LSTMPredictor(nn.Module):
    """LSTM with TWO outputs: fault probability + time-to-impact"""
    def __init__(self, input_size, hidden_size=32, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.3 if num_layers > 1 else 0,
        )
        self.fc_fault = nn.Linear(hidden_size, 1)
        self.fc_tti = nn.Linear(hidden_size, 1)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last = lstm_out[:, -1, :]
        fault_prob = torch.sigmoid(self.fc_fault(last)).squeeze(-1)
        tti = torch.relu(self.fc_tti(last)).squeeze(-1)
        return fault_prob, tti


# ═════════════════════════════════════════════════════════════════════════════
# MODEL LOADING
# ═════════════════════════════════════════════════════════════════════════════
def load_latest_xgboost() -> Tuple[Optional[object], Optional[str]]:
    """Load the most recent XGBoost/ensemble model."""
    patterns = [
        "xgboost_reg_*.pkl",
        "xgboost_*.pkl",
        "randomforest_*.pkl",
        "isolation_forest_*.pkl",
    ]
    for pattern in patterns:
        files = sorted(glob.glob(os.path.join(MODELS_DIR, pattern)))
        if files:
            latest = files[-1]
            print(f"[LOAD] XGBoost Model: {os.path.basename(latest)}")
            with open(latest, "rb") as f:
                model = pickle.load(f)
            return model, latest
    print("[WARN] No XGBoost model found.")
    return None, None


def load_latest_lstm() -> Tuple[Optional[nn.Module], Optional[dict], Optional[str]]:
    """Load the most recent LSTM model checkpoint."""
    if not HAS_TORCH:
        print("[WARN] PyTorch not installed. LSTM forecast unavailable.")
        return None, None, None

    files = sorted(glob.glob(os.path.join(MODELS_DIR, "lstm_predictor_*.pt")))
    if not files:
        print("[WARN] No LSTM model found. Run train_lstm.py first.")
        return None, None, None

    latest = files[-1]
    print(f"[LOAD] LSTM Model: {os.path.basename(latest)}")

    checkpoint = torch.load(latest, map_location="cpu")
    state_dict = checkpoint["model_state"]
    mean = checkpoint.get("mean")
    std = checkpoint.get("std")
    hidden_size = checkpoint.get("hidden_size", 32)
    num_layers = checkpoint.get("num_layers", 2)
    seq_len = checkpoint.get("sequence_length", 15)

    # Infer input_size from state_dict
    input_size = state_dict["lstm.weight_ih_l0"].shape[1]

    model = LSTMPredictor(input_size, hidden_size, num_layers)
    model.load_state_dict(state_dict)
    model.eval()

    meta = {
        "mean": mean,
        "std": std,
        "sequence_length": seq_len,
        "horizon": checkpoint.get("horizon", 5),
    }

    return model, meta, latest


# ═════════════════════════════════════════════════════════════════════════════
# FEATURE BUILDING
# ═════════════════════════════════════════════════════════════════════════════
def build_latest_features() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """Fetch latest metrics and build feature vector for each router."""
    print(f"\n[FETCH] Fetching latest metrics...")

    ping_df = fetch_ping(hours=DEFAULT_HOURS)
    ospf_df = fetch_ospf(hours=DEFAULT_HOURS)
    bgp_df = fetch_bgp(hours=DEFAULT_HOURS)
    cpu_df = fetch_container_cpu(hours=DEFAULT_HOURS)
    mem_df = fetch_container_mem(hours=DEFAULT_HOURS)

    latest_times = []
    for df in [ping_df, ospf_df, bgp_df, cpu_df, mem_df]:
        if not df.empty and "time" in df.columns:
            latest_times.append(df["time"].max())

    if not latest_times:
        print("[ERROR] No metrics available")
        return None, None

    latest_time = max(latest_times)
    print(f"[FETCH] Latest metric time: {latest_time}")

    records = []
    raw_records = []

    for router in ROUTERS:
        record = {"time": latest_time, "router": router}

        # Ping
        if not ping_df.empty and router in ping_df["router"].values:
            r_ping = ping_df[ping_df["router"] == router].sort_values("time").tail(1)
            if not r_ping.empty:
                record["average_response_ms"] = r_ping["average_response_ms"].values[0]
                record["percent_packet_loss"] = r_ping["percent_packet_loss"].values[0]
            else:
                record["average_response_ms"] = 0.0
                record["percent_packet_loss"] = 0.0
        else:
            record["average_response_ms"] = 0.0
            record["percent_packet_loss"] = 0.0

        # OSPF
        if not ospf_df.empty and router.lower().replace("-", "_") in ospf_df["router"].values:
            r_ospf = ospf_df[ospf_df["router"] == router.lower().replace("-", "_")].sort_values("time").tail(1)
            if not r_ospf.empty:
                record["count"] = r_ospf["count"].values[0]
            else:
                record["count"] = 0
        else:
            record["count"] = 0

        # BGP
        if not bgp_df.empty and router.lower().replace("-", "_") in bgp_df["router"].values:
            r_bgp = bgp_df[bgp_df["router"] == router.lower().replace("-", "_")].sort_values("time").tail(1)
            if not r_bgp.empty:
                record["state_ok"] = r_bgp["state_ok"].values[0]
            else:
                record["state_ok"] = 1
        else:
            record["state_ok"] = 1

        # CPU
        if not cpu_df.empty and router in cpu_df["router"].values:
            r_cpu = cpu_df[cpu_df["router"] == router].sort_values("time").tail(1)
            if not r_cpu.empty:
                record["cpu_percent"] = r_cpu["usage_percent"].values[0]
            else:
                record["cpu_percent"] = 0.0
        else:
            record["cpu_percent"] = 0.0

        # Memory
        if not mem_df.empty and router in mem_df["router"].values:
            r_mem = mem_df[mem_df["router"] == router].sort_values("time").tail(1)
            if not r_mem.empty:
                record["mem_percent"] = r_mem["usage_percent"].values[0]
            else:
                record["mem_percent"] = 0.0
        else:
            record["mem_percent"] = 0.0

        # Router one-hot encoding
        for r in ROUTERS:
            record[f"router_{r}"] = 1 if r == router else 0

        raw_records.append(record)

    df = pd.DataFrame(raw_records)
    features_df = df[FEATURE_NAMES].copy()
    features_df = features_df.fillna(0)

    return features_df, df


def build_lstm_sequence(ping_df: pd.DataFrame, router: str, meta: dict) -> Optional[np.ndarray]:
    """
    Build LSTM input sequence of last N steps for a router.
    Returns normalized sequence or None if insufficient data.
    """
    seq_len = meta["sequence_length"]

    if ping_df.empty or router not in ping_df["router"].values:
        return None

    rdf = ping_df[ping_df["router"] == router].copy().sort_values("time").reset_index(drop=True)

    if len(rdf) < seq_len:
        return None

    # Take last seq_len rows
    rdf = rdf.tail(seq_len).reset_index(drop=True)

    # Build LSTM features (must match train_lstm.py exactly)
    rdf["latency_ma"] = rdf["average_response_ms"].fillna(0).rolling(3, min_periods=1).mean()
    rdf["loss_ma"] = rdf["percent_packet_loss"].fillna(0).rolling(3, min_periods=1).mean()
    rdf["latency_diff"] = rdf["average_response_ms"].fillna(0).diff().fillna(0)

    features = rdf[[
        "average_response_ms",
        "percent_packet_loss",
        "latency_ma",
        "loss_ma",
        "latency_diff",
    ]].fillna(0).values

    # Normalize using training stats
    mean = meta["mean"]
    std = meta["std"]
    if mean is not None and std is not None:
        features_norm = (features - mean) / std
    else:
        features_norm = features

    return features_norm  # shape: (seq_len, 5)


# ═════════════════════════════════════════════════════════════════════════════
# PREDICTION
# ═════════════════════════════════════════════════════════════════════════════
def predict_xgboost(model, features_df: pd.DataFrame) -> np.ndarray:
    """Run XGBoost prediction. Returns fault probabilities."""
    X = features_df.values.astype(np.float32)
    if hasattr(model, "predict_proba"):
        return model.predict_proba(X)[:, 1]
    else:
        scores = model.decision_function(X)
        return 1.0 / (1.0 + np.exp(scores * 2))


def predict_lstm(model: nn.Module, sequences: List[Optional[np.ndarray]]) -> Tuple[List[float], List[float], List[bool]]:
    """
    Run LSTM prediction on sequences.
    Returns: (fault_probs, tti_estimates, has_data_flags)
    """
    fault_probs = []
    tti_estimates = []
    has_data = []

    with torch.no_grad():
        for seq in sequences:
            if seq is None:
                fault_probs.append(0.0)
                tti_estimates.append(0.0)
                has_data.append(False)
                continue

            # seq shape: (seq_len, 5) → add batch dim → (1, seq_len, 5)
            x = torch.FloatTensor(seq).unsqueeze(0)
            pred_fault, pred_tti = model(x)
            fault_probs.append(float(pred_fault.item()))
            tti_estimates.append(float(pred_tti.item()))
            has_data.append(True)

    return fault_probs, tti_estimates, has_data


def run_inference(xgb_model, lstm_model, lstm_meta, features_df: pd.DataFrame, raw_df: pd.DataFrame, ping_df: pd.DataFrame) -> Dict:
    """Run both XGBoost and LSTM predictions and combine results."""

    # ── XGBoost: Current fault probability ──────────────────────────────────
    xgb_proba = predict_xgboost(xgb_model, features_df)

    # ── LSTM: Future fault probability + TTI ────────────────────────────────
    if lstm_model is not None and lstm_meta is not None:
        sequences = [build_lstm_sequence(ping_df, router, lstm_meta) for router in ROUTERS]
        lstm_proba, lstm_tti, lstm_has_data = predict_lstm(lstm_model, sequences)
    else:
        lstm_proba = [None] * len(ROUTERS)
        lstm_tti = [None] * len(ROUTERS)
        lstm_has_data = [False] * len(ROUTERS)

    # ── Build per-router predictions ────────────────────────────────────────
    predictions = []
    critical_count = 0
    warning_count = 0

    for i, router in enumerate(ROUTERS):
        xgb_prob = float(xgb_proba[i])
        xgb_is_fault = xgb_prob > 0.5

        lstm_prob = lstm_proba[i]
        lstm_tti_val = lstm_tti[i]
        lstm_has = lstm_has_data[i]

        # XGBoost confidence
        if xgb_prob >= CONFIDENCE_HIGH:
            xgb_conf = "HIGH"
        elif xgb_prob >= CONFIDENCE_MEDIUM:
            xgb_conf = "MEDIUM"
        else:
            xgb_conf = "LOW"

        # XGBoost status
        if xgb_is_fault:
            if xgb_prob >= CONFIDENCE_HIGH:
                xgb_status = "CRITICAL"
                critical_count += 1
            else:
                xgb_status = "WARNING"
                warning_count += 1
        else:
            xgb_status = "HEALTHY"

        # LSTM status
        if lstm_has and lstm_prob is not None:
            lstm_is_fault = lstm_prob > 0.5
            if lstm_is_fault:
                if lstm_prob >= CONFIDENCE_HIGH:
                    lstm_status = "CRITICAL"
                elif lstm_prob >= CONFIDENCE_MEDIUM:
                    lstm_status = "WARNING"
                else:
                    lstm_status = "LOW_RISK"
            else:
                lstm_status = "HEALTHY"
            tti_display = f"{lstm_tti_val:.1f} min" if lstm_tti_val > 0 else "imminent"
        else:
            lstm_status = "NO_DATA"
            lstm_is_fault = None
            tti_display = "N/A"

        # Combined alert: both models agree on fault = highest confidence
        if xgb_is_fault and lstm_has and lstm_is_fault:
            combined_alert = "HIGH_CONFIDENCE_FAULT"
        elif xgb_is_fault or (lstm_has and lstm_is_fault):
            combined_alert = "SUSPECTED_FAULT"
        else:
            combined_alert = "NORMAL"

        # Top feature (simple heuristic from XGBoost features)
        row = features_df.iloc[i]
        top_feature = row.abs().idxmax()

        predictions.append({
            "router": router,
            # XGBoost
            "xgboost": {
                "fault_probability": round(xgb_prob, 3),
                "predicted_fault": bool(xgb_is_fault),
                "confidence": xgb_conf,
                "status": xgb_status,
            },
            # LSTM Forecast
            "lstm_forecast": {
                "future_fault_probability": round(lstm_prob, 3) if lstm_prob is not None else None,
                "predicted_future_fault": lstm_is_fault,
                "time_to_impact": tti_display,
                "tti_raw_steps": round(lstm_tti_val, 2) if lstm_tti_val is not None else None,
                "has_sequence_data": lstm_has,
                "status": lstm_status,
            },
            # Combined
            "combined_alert": combined_alert,
            "top_feature": top_feature,
            "raw_metrics": {
                "latency_ms": round(float(row["average_response_ms"]), 2),
                "packet_loss_pct": round(float(row["percent_packet_loss"]), 1),
                "ospf_neighbors": int(row["count"]),
                "bgp_established": bool(row["state_ok"]),
                "cpu_pct": round(float(row["cpu_percent"]), 1),
                "mem_pct": round(float(row["mem_percent"]), 1),
            }
        })

    # Overall status
    if critical_count > 0:
        overall = "CRITICAL"
    elif warning_count > 0:
        overall = "WARNING"
    else:
        overall = "HEALTHY"

    result = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models_used": {
            "xgboost": type(xgb_model).__name__,
            "lstm": "LSTMPredictor" if lstm_model is not None else None,
        },
        "overall_status": overall,
        "routers_at_risk": critical_count + warning_count,
        "predictions": predictions,
    }

    return result


# ═════════════════════════════════════════════════════════════════════════════
# OUTPUT FORMATTING
# ═════════════════════════════════════════════════════════════════════════════
def print_prediction(result: Dict):
    """Pretty-print prediction results with both XGBoost and LSTM."""

    print(f"\n{'='*70}")
    print("NETWROXIA — REAL-TIME PREDICTION + LSTM FORECAST")
    print(f"{'='*70}")
    print(f"Timestamp: {result['timestamp']}")
    print(f"XGBoost:   {result['models_used']['xgboost']}")
    print(f"LSTM:      {result['models_used']['lstm'] or 'NOT LOADED'}")
    print(f"Overall:   {result['overall_status']}")
    print(f"At Risk:   {result['routers_at_risk']} router(s)")
    print(f"{'-'*70}")

    for pred in result["predictions"]:
        router = pred["router"]

        # Icon based on combined alert
        if pred["combined_alert"] == "HIGH_CONFIDENCE_FAULT":
            icon = "🔴🔴"
        elif pred["combined_alert"] == "SUSPECTED_FAULT":
            icon = "🟡"
        elif pred["xgboost"]["status"] == "CRITICAL":
            icon = "🔴"
        elif pred["xgboost"]["status"] == "WARNING":
            icon = "🟡"
        else:
            icon = "🟢"

        print(f"\n{icon} {router}")
        print(f"   ┌─ XGBoost (CURRENT)")
        print(f"   │  Fault Probability: {pred['xgboost']['fault_probability']*100:.1f}%")
        print(f"   │  Status:            {pred['xgboost']['status']}")
        print(f"   │  Confidence:        {pred['xgboost']['confidence']}")
        print(f"   ├─ LSTM Forecast (FUTURE)")
        lstm = pred["lstm_forecast"]
        if lstm["has_sequence_data"]:
            prob_str = f"{lstm['future_fault_probability']*100:.1f}%" if lstm["future_fault_probability"] is not None else "N/A"
            print(f"   │  Future Prob:       {prob_str}")
            print(f"   │  Time-to-Impact:    {lstm['time_to_impact']}")
            print(f"   │  Status:            {lstm['status']}")
        else:
            print(f"   │  [No LSTM sequence data — need {LSTM_SEQ_LENGTH} historical points]")
        print(f"   └─ Combined Alert:    {pred['combined_alert']}")
        print(f"      Top Signal:        {pred['top_feature']}")
        print(f"      Metrics:           latency={pred['raw_metrics']['latency_ms']}ms | "
              f"loss={pred['raw_metrics']['packet_loss_pct']}% | "
              f"ospf={pred['raw_metrics']['ospf_neighbors']} | "
              f"cpu={pred['raw_metrics']['cpu_pct']}% | "
              f"mem={pred['raw_metrics']['mem_pct']}%")


# ═════════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("NETWROXIA — Predictive Inference (XGBoost + LSTM Forecast)")
    print("=" * 70)

    # 1. Load XGBoost
    print("\n[1/3] Loading XGBoost model...")
    xgb_model, xgb_path = load_latest_xgboost()
    if xgb_model is None:
        print("[FATAL] No XGBoost model. Run train_ensemble.py first.")
        return

    # 2. Load LSTM
    print("\n[2/3] Loading LSTM model...")
    lstm_model, lstm_meta, lstm_path = load_latest_lstm()

    # 3. Fetch metrics
    print("\n[3/3] Building features from live metrics...")
    features_df, raw_df = build_latest_features()
    if features_df is None:
        return

    # Also fetch ping data for LSTM sequences (need more history)
    print("[FETCH] Fetching extended ping history for LSTM...")
    ping_df = fetch_ping(hours=max(DEFAULT_HOURS, 2))  # Get 2h for LSTM history

    # 4. Run inference
    result = run_inference(xgb_model, lstm_model, lstm_meta, features_df, raw_df, ping_df)

    # 5. Display
    print_prediction(result)

    # 6. Save JSON
    out_path = os.path.join(PROJECT_ROOT, "ml", "inference", "latest_prediction.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n[SAVE] Prediction saved to: {out_path}")

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()