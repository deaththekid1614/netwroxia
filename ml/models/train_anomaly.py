#!/usr/bin/env python3
"""
Netwroxia Stage 3 — train_anomaly.py
Trains Isolation Forest for unsupervised anomaly detection.
No labels needed — finds outliers in network telemetry.
"""

import numpy as np
import pandas as pd
import json
import os
import glob
import pickle
from datetime import datetime
from typing import Tuple, Optional

from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

# ── CONFIG ──────────────────────────────────────────────────────────────────
PROCESSED_DIR = "ml/data/processed"
MODELS_DIR = "ml/models"
LABELS_DIR = "ml/data/labels"

# Isolation Forest params (tuned for 8GB RAM, small dataset)
CONTAMINATION = 0.12  # Expected anomaly rate (~12.5% from labels)
N_ESTIMATORS = 100
RANDOM_STATE = 42
N_JOBS = 2  # Don't max out CPU


def load_latest_data() -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[list]]:
    """Load the most recent X, y, and feature names."""
    X_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "X_*.npy")))
    y_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "y_*.npy")))
    feat_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "features_*.json")))

    if not X_files or not y_files:
        print("[ERROR] No processed data found. Run feature_engineer.py first.")
        return None, None, None

    X = np.load(X_files[-1], allow_pickle=True)
    y = np.load(y_files[-1], allow_pickle=True)
    features = json.load(open(feat_files[-1])) if feat_files else []

    print(f"[LOAD] X shape: {X.shape}")
    print(f"[LOAD] y shape: {y.shape}")
    print(f"[LOAD] Features: {features}")

    return X, y, features

def train_isolation_forest(X: np.ndarray) -> IsolationForest:
    """Train Isolation Forest on the data."""
    print(f"\n[TRAIN] Training Isolation Forest...")
    print(f"  Contamination: {CONTAMINATION}")
    print(f"  Estimators: {N_ESTIMATORS}")

    model = IsolationForest(
        contamination=CONTAMINATION,
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        n_jobs=N_JOBS,
        verbose=0,
    )

    model.fit(X)
    print("[TRAIN] Training complete")
    return model


def evaluate_model(model: IsolationForest, X: np.ndarray, y_true: np.ndarray,
                   features: list) -> dict:
    """
    Evaluate Isolation Forest.
    Returns: -1 for anomaly, 1 for normal.
    We map: -1 → 1 (fault), 1 → 0 (normal) to match our y labels.
    """
    print(f"\n[EVAL] Running predictions...")
    y_pred_raw = model.predict(X)  # -1 = anomaly, 1 = normal
    y_pred = np.where(y_pred_raw == -1, 1, 0)  # Map to our label scheme

    # Metrics
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0

    # Anomaly scores (lower = more anomalous)
    scores = model.decision_function(X)

    try:
        auc = roc_auc_score(y_true, -scores)  # Negative because lower score = more anomalous
    except Exception:
        auc = 0.0

    print(f"\n{'='*50}")
    print("ISOLATION FOREST RESULTS")
    print(f"{'='*50}")
    print(f"Total samples:    {len(y_true)}")
    print(f"Actual faults:    {y_true.sum()}")
    print(f"Predicted faults: {y_pred.sum()}")
    print(f"\nConfusion Matrix:")
    print(f"                 Pred-Normal  Pred-Fault")
    print(f"  Actual-Normal      {tn:4d}       {fp:4d}")
    print(f"  Actual-Fault       {fn:4d}       {tp:4d}")
    print(f"\nMetrics:")
    print(f"  Precision:  {precision:.3f}  (of predicted faults, how many were real?)")
    print(f"  Recall:     {recall:.3f}  (of real faults, how many did we catch?)")
    print(f"  F1-Score:   {f1:.3f}")
    print(f"  Specificity:{specificity:.3f}  (true negative rate)")
    print(f"  AUC-ROC:    {auc:.3f}")
    print(f"{'='*50}")

    # Feature importance (approximate via permutation)
    print(f"\n[EVAL] Feature importance (approximate):")
    baseline_score = np.mean(np.abs(scores))
    importances = []
    for i in range(X.shape[1]):
        X_permuted = X.copy()
        np.random.shuffle(X_permuted[:, i])
        permuted_scores = model.decision_function(X_permuted)
        importance = np.mean(np.abs(permuted_scores)) - baseline_score
        importances.append(importance)

    feat_imp = list(zip(features, importances))
    feat_imp.sort(key=lambda x: x[1], reverse=True)
    for feat, imp in feat_imp[:5]:
        print(f"  {feat:30s}: {imp:+.4f}")

    return {
        "model": "IsolationForest",
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": specificity,
        "auc": auc,
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }


def save_model(model: IsolationForest, metrics: dict):
    """Save trained model and metrics."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save model
    model_path = os.path.join(MODELS_DIR, f"isolation_forest_{timestamp}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"\n[SAVE] Model: {model_path}")

    # Save metrics
    metrics_path = os.path.join(MODELS_DIR, f"metrics_anomaly_{timestamp}.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[SAVE] Metrics: {metrics_path}")


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("NETWROXIA — Isolation Forest Anomaly Detection")
    print("=" * 60)

    # 1. Load data
    print("\n[1/3] Loading processed data...")
    X, y, features = load_latest_data()
    if X is None:
        return

    # 2. Train
    print("\n[2/3] Training Isolation Forest...")
    model = train_isolation_forest(X)

    # 3. Evaluate
    print("\n[3/3] Evaluating...")
    metrics = evaluate_model(model, X, y, features)

    # Save
    save_model(model, metrics)

    print("\n" + "=" * 60)
    print("DONE — Isolation Forest trained & saved")
    print("=" * 60)


if __name__ == "__main__":
    main()
