#!/usr/bin/env python3
"""
Netwroxia Stage 3 — feature_engineer.py
Builds ML-ready feature matrix + fault labels from raw InfluxDB metrics.
"""

import pandas as pd
import numpy as np
import os
import glob
from datetime import datetime, timedelta
from typing import Tuple, Optional
import json
import re

# ── CONFIG ──────────────────────────────────────────────────────────────────
RAW_DIR = "ml/data/raw"
PROCESSED_DIR = "ml/data/processed"
LABELS_DIR = "ml/data/labels"

# Time window for aggregation (seconds)
WINDOW_S = 60  # 1-minute buckets

# Fault thresholds
PACKET_LOSS_THRESHOLD = 50.0   # % packet loss = fault
OSPF_DOWN_THRESHOLD = 0        # 0 neighbors = fault
BGP_DOWN_STATES = [0, 2, 3]    # Not Established = fault
CPU_HIGH_THRESHOLD = 90.0      # CPU% = fault
MEM_HIGH_THRESHOLD = 90.0      # Mem% = fault

# Router list (order matters for feature columns)
ROUTERS = ["HO-Chennai", "ZO-Bengaluru", "BR-Koramangala", "BR-Whitefield"]


def load_latest_csv(pattern: str) -> Optional[pd.DataFrame]:
    """Load the most recent CSV matching pattern from raw dir."""
    files = sorted(glob.glob(os.path.join(RAW_DIR, pattern)))
    if not files:
        print(f"[WARN] No files found for pattern: {pattern}")
        return None
    latest = files[-1]
    print(f"[LOAD] {latest}")
    df = pd.read_csv(latest)
    if "time" in df.columns:
        def _safe_parse(ts):
            ts = str(ts).replace(" ", "T")
            if ts.endswith("Z"):
                ts = ts[:-1]
            # Truncate nanoseconds to 6 digits max
            ts = re.sub(r'(\.\d{6})\d*', r'\1', ts)
            dt = datetime.fromisoformat(ts)
            # Strip timezone — pandas resample needs naive datetimes
            if dt.tzinfo is not None:
                return dt.replace(tzinfo=None)
            return dt
        
        # Parse to datetime objects, then force pandas datetime dtype
        df["time"] = pd.to_datetime(df["time"].apply(_safe_parse))
    return df


def resample_ping(df: pd.DataFrame) -> pd.DataFrame:
    """Resample ping data to 1-min windows per router."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Drop rows where router is NaN (old loopback IPs not in map)
    df = df.dropna(subset=["router"])

    results = []
    for router in df["router"].unique():
        router_df = df[df["router"] == router].copy()
        router_df = router_df.set_index("time").sort_index()

        # Resample: mean latency, max packet loss
        resampled = router_df.resample(f"{WINDOW_S}S").agg({
            "average_response_ms": "mean",
            "percent_packet_loss": "max",
            "packets_transmitted": "sum",
            "packets_received": "sum",
        }).reset_index()

        resampled["router"] = router
        results.append(resampled)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def resample_ospf(df: pd.DataFrame) -> pd.DataFrame:
    """Resample OSPF neighbor counts to 1-min windows."""
    if df is None or df.empty:
        return pd.DataFrame()

    results = []
    for router in df["router"].unique():
        router_df = df[df["router"] == router].copy()
        router_df = router_df.set_index("time").sort_index()

        resampled = router_df.resample(f"{WINDOW_S}S").agg({
            "count": "last",  # Take last known count
        }).reset_index()

        resampled["router"] = router
        results.append(resampled)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def resample_bgp(df: pd.DataFrame) -> pd.DataFrame:
    """Resample BGP peer states to 1-min windows."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Group by router + peer, then resample
    results = []
    for (router, peer), group in df.groupby(["router", "peer"]):
        group = group.set_index("time").sort_index()
        resampled = group.resample(f"{WINDOW_S}S").agg({
            "state": "last",
            "state_ok": "last",
        }).reset_index()
        resampled["router"] = router
        resampled["peer"] = peer
        results.append(resampled)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def resample_container(df: pd.DataFrame, metric_name: str) -> pd.DataFrame:
    """Resample container CPU/memory to 1-min windows."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Drop rows where router is NaN
    df = df.dropna(subset=["router"])

    results = []
    for router in df["router"].unique():
        router_df = df[df["router"] == router].copy()
        router_df = router_df.set_index("time").sort_index()

        resampled = router_df.resample(f"{WINDOW_S}S").agg({
            "usage_percent": "mean",
        }).reset_index()

        resampled["router"] = router
        resampled["metric"] = metric_name
        results.append(resampled)

    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def create_fault_labels(ping_df: pd.DataFrame, ospf_df: pd.DataFrame,
                        bgp_df: pd.DataFrame, cpu_df: pd.DataFrame,
                        mem_df: pd.DataFrame) -> pd.DataFrame:
    """
    Create fault labels: 1 = network fault detected, 0 = normal.
    Fault conditions:
      - Packet loss > 50%
      - OSPF neighbors = 0
      - BGP state not Established
      - CPU > 90%
      - Memory > 90%
    """
    # Build a unified timeline
    all_times = set()
    for df in [ping_df, ospf_df, bgp_df, cpu_df, mem_df]:
        if not df.empty and "time" in df.columns:
            all_times.update(df["time"].unique())

    if not all_times:
        print("[ERROR] No time data available")
        return pd.DataFrame()

    # Create base dataframe with all router-time combinations
    records = []
    for t in sorted(all_times):
        for router in ROUTERS:
            records.append({"time": pd.Timestamp(t), "router": router})

    labels = pd.DataFrame(records)

    # Merge ping data
    if not ping_df.empty:
        labels = labels.merge(
            ping_df[["time", "router", "average_response_ms", "percent_packet_loss"]],
            on=["time", "router"], how="left"
        )
    else:
        labels["average_response_ms"] = np.nan
        labels["percent_packet_loss"] = np.nan

    # Merge OSPF
    if not ospf_df.empty:
        labels = labels.merge(
            ospf_df[["time", "router", "count"]],
            on=["time", "router"], how="left"
        )
    else:
        labels["count"] = np.nan

    # Merge BGP (aggregate: any peer down = fault)
    if not bgp_df.empty:
        bgp_agg = bgp_df.groupby(["time", "router"])["state_ok"].min().reset_index()
        labels = labels.merge(
            bgp_agg[["time", "router", "state_ok"]],
            on=["time", "router"], how="left"
        )
    else:
        labels["state_ok"] = np.nan

    # Merge CPU
    if not cpu_df.empty:
        labels = labels.merge(
            cpu_df[["time", "router", "usage_percent"]].rename(
                columns={"usage_percent": "cpu_percent"}
            ),
            on=["time", "router"], how="left"
        )
    else:
        labels["cpu_percent"] = np.nan

    # Merge Memory
    if not mem_df.empty:
        labels = labels.merge(
            mem_df[["time", "router", "usage_percent"]].rename(
                columns={"usage_percent": "mem_percent"}
            ),
            on=["time", "router"], how="left"
        )
    else:
        labels["mem_percent"] = np.nan

    # ── CREATE FAULT LABEL ──
    labels["fault_ping"] = (labels["percent_packet_loss"] > PACKET_LOSS_THRESHOLD).astype(int)
    labels["fault_ospf"] = (labels["count"] <= OSPF_DOWN_THRESHOLD).astype(int)
    labels["fault_bgp"] = (labels["state_ok"] == 0).astype(int)
    labels["fault_cpu"] = (labels["cpu_percent"] > CPU_HIGH_THRESHOLD).astype(int)
    labels["fault_mem"] = (labels["mem_percent"] > MEM_HIGH_THRESHOLD).astype(int)

    # Any fault = overall fault
    labels["fault"] = (
        labels["fault_ping"] |
        labels["fault_ospf"] |
        labels["fault_bgp"] |
        labels["fault_cpu"] |
        labels["fault_mem"]
    ).astype(int)

    # Fill NaN features with safe defaults
    labels["average_response_ms"] = labels["average_response_ms"].fillna(0)
    labels["percent_packet_loss"] = labels["percent_packet_loss"].fillna(0)
    labels["count"] = labels["count"].fillna(0)
    labels["state_ok"] = labels["state_ok"].fillna(1)  # Assume OK if unknown
    labels["cpu_percent"] = labels["cpu_percent"].fillna(0)
    labels["mem_percent"] = labels["mem_percent"].fillna(0)

    return labels


def create_feature_matrix(labels_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, list]:
    """
    Create X (features) and y (labels) for ML.
    Features per router: latency, loss, ospf_count, bgp_ok, cpu, mem
    """
    if labels_df.empty:
        return np.array([]), np.array([]), []

    # Sort by time then router for consistent ordering
    labels_df = labels_df.sort_values(["time", "router"]).reset_index(drop=True)

    # Feature columns
    feature_cols = [
        "average_response_ms",
        "percent_packet_loss",
        "count",
        "state_ok",
        "cpu_percent",
        "mem_percent",
    ]

    # One-hot encode router
    router_dummies = pd.get_dummies(labels_df["router"], prefix="router")
    labels_df = pd.concat([labels_df, router_dummies], axis=1)

    # Final feature list
    final_features = feature_cols + list(router_dummies.columns)

    X = labels_df[final_features].values
    y = labels_df["fault"].values

    print(f"[FEAT] Feature matrix shape: X={X.shape}, y={y.shape}")
    print(f"[FEAT] Fault rate: {y.mean()*100:.1f}% ({y.sum()} faults / {len(y)} total)")
    print(f"[FEAT] Features: {final_features}")

    return X, y, final_features


def save_processed(X: np.ndarray, y: np.ndarray, features: list,
                   labels_df: pd.DataFrame):
    """Save processed data for model training."""
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    os.makedirs(LABELS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save numpy arrays
    np.save(os.path.join(PROCESSED_DIR, f"X_{timestamp}.npy"), X)
    np.save(os.path.join(PROCESSED_DIR, f"y_{timestamp}.npy"), y)

    # Save feature names
    with open(os.path.join(PROCESSED_DIR, f"features_{timestamp}.json"), "w") as f:
        json.dump(features, f, indent=2)

    # Save labels dataframe for inspection
    labels_df.to_csv(os.path.join(LABELS_DIR, f"labels_{timestamp}.csv"), index=False)

    print(f"[SAVE] X: {os.path.join(PROCESSED_DIR, f'X_{timestamp}.npy')}")
    print(f"[SAVE] y: {os.path.join(PROCESSED_DIR, f'y_{timestamp}.npy')}")
    print(f"[SAVE] Features: {os.path.join(PROCESSED_DIR, f'features_{timestamp}.json')}")
    print(f"[SAVE] Labels CSV: {os.path.join(LABELS_DIR, f'labels_{timestamp}.csv')}")


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("NETWROXIA — Feature Engineering")
    print("=" * 60)

    # 1. Load raw data
    print("\n[1/4] Loading raw data...")
    ping_df = load_latest_csv("ping_*.csv")
    ospf_df = load_latest_csv("ospf_neighbors_*.csv")
    bgp_df = load_latest_csv("bgp_peer_*.csv")
    cpu_df = load_latest_csv("docker_container_cpu_*.csv")
    mem_df = load_latest_csv("docker_container_mem_*.csv")

    # 2. Resample
    print("\n[2/4] Resampling to 1-min windows...")
    ping_r = resample_ping(ping_df)
    ospf_r = resample_ospf(ospf_df)
    bgp_r = resample_bgp(bgp_df)
    cpu_r = resample_container(cpu_df, "cpu")
    mem_r = resample_container(mem_df, "mem")

    print(f"  ping: {len(ping_r)} windows")
    print(f"  ospf: {len(ospf_r)} windows")
    print(f"  bgp:  {len(bgp_r)} windows")
    print(f"  cpu:  {len(cpu_r)} windows")
    print(f"  mem:  {len(mem_r)} windows")

    # 3. Create labels
    print("\n[3/4] Creating fault labels...")
    labels_df = create_fault_labels(ping_r, ospf_r, bgp_r, cpu_r, mem_r)
    print(f"  Total windows: {len(labels_df)}")

    # Show fault breakdown
    if not labels_df.empty:
        print(f"\n  Fault breakdown:")
        print(f"    Ping loss > {PACKET_LOSS_THRESHOLD}%: {labels_df['fault_ping'].sum()}")
        print(f"    OSPF down (0 neighbors): {labels_df['fault_ospf'].sum()}")
        print(f"    BGP not Established: {labels_df['fault_bgp'].sum()}")
        print(f"    CPU > {CPU_HIGH_THRESHOLD}%: {labels_df['fault_cpu'].sum()}")
        print(f"    Mem > {MEM_HIGH_THRESHOLD}%: {labels_df['fault_mem'].sum()}")
        print(f"    ANY fault: {labels_df['fault'].sum()}")

    # 4. Feature matrix
    print("\n[4/4] Building feature matrix...")
    X, y, features = create_feature_matrix(labels_df)

    if len(X) == 0:
        print("[ERROR] No data to process. Exiting.")
        return

    # Save
    save_processed(X, y, features, labels_df)

    print("\n" + "=" * 60)
    print("DONE — Ready for model training")
    print("=" * 60)


if __name__ == "__main__":
    main()