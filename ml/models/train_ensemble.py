#!/usr/bin/env python3
"""
Netwroxia Stage 3 — train_ensemble.py (REGULARIZED)
Trains XGBoost classifier with strong regularization to prevent overfitting.
"""

import numpy as np
import pandas as pd
import json
import os
import glob
import pickle
from datetime import datetime
from typing import Tuple, Optional

from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, average_precision_score
)

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    print("[WARN] XGBoost not installed. Using RandomForest fallback.")
    from sklearn.ensemble import RandomForestClassifier

# ── CONFIG ──────────────────────────────────────────────────────────────────
PROCESSED_DIR = "ml/data/processed"
MODELS_DIR = "ml/models"

TEST_SIZE = 0.2
RANDOM_STATE = 42
N_SPLITS = 5  # Cross-validation folds

# REGULARIZED XGBoost params (prevents overfitting)
XGB_PARAMS = {
    "n_estimators": 100,        # Reduced from 200
    "max_depth": 3,             # SHALLOW — was 6, now 3
    "learning_rate": 0.05,      # Slower learning
    "subsample": 0.6,           # Random 60% of rows per tree
    "colsample_bytree": 0.6,    # Random 60% of features per tree
    "colsample_bylevel": 0.6,
    "reg_alpha": 1.0,           # L1 regularization
    "reg_lambda": 2.0,          # L2 regularization (stronger)
    "min_child_weight": 10,     # Require 10+ samples per leaf
    "gamma": 0.5,               # Min loss reduction to split
    "scale_pos_weight": 5,      # Slightly reduced from 7
    "random_state": RANDOM_STATE,
    "n_jobs": 2,
    "eval_metric": "logloss",
}

# RandomForest fallback (also regularized)
RF_PARAMS = {
    "n_estimators": 100,
    "max_depth": 5,
    "min_samples_leaf": 10,
    "min_samples_split": 20,
    "class_weight": "balanced",
    "random_state": RANDOM_STATE,
    "n_jobs": 2,
}


def load_latest_data() -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[list]]:
    """Load the most recent X, y, and feature names."""
    X_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "X_*.npy")))
    y_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "y_*.npy")))
    feat_files = sorted(glob.glob(os.path.join(PROCESSED_DIR, "features_*.json")))

    if not X_files or not y_files:
        print("[ERROR] No processed data found. Run feature_engineer.py first.")
        return None, None, None

    X = np.load(X_files[-1], allow_pickle=True).astype(np.float32)
    y = np.load(y_files[-1], allow_pickle=True).astype(np.int32)
    features = json.load(open(feat_files[-1])) if feat_files else []

    print(f"[LOAD] X shape: {X.shape}")
    print(f"[LOAD] y shape: {y.shape}")
    print(f"[LOAD] Class distribution: normal={np.sum(y==0)}, fault={np.sum(y==1)}")
    print(f"[LOAD] Features: {features}")

    return X, y, features


def cross_validate(X: np.ndarray, y: np.ndarray) -> dict:
    """5-fold stratified cross-validation to detect overfitting."""
    print(f"\n[CV] Running {N_SPLITS}-fold stratified cross-validation...")

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=RANDOM_STATE)
    fold_scores = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(X, y), 1):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        if HAS_XGBOOST:
            model = xgb.XGBClassifier(**XGB_PARAMS)
            model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
        else:
            model = RandomForestClassifier(**RF_PARAMS)
            model.fit(X_tr, y_tr)

        y_pred = model.predict(X_val)
        y_proba = model.predict_proba(X_val)[:, 1]

        # Metrics
        tn, fp, fn, tp = confusion_matrix(y_val, y_pred).ravel()
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0

        try:
            auc = roc_auc_score(y_val, y_proba)
        except Exception:
            auc = 0.0

        fold_scores.append({
            "fold": fold,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "auc": auc,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        })

        print(f"  Fold {fold}: P={prec:.3f} R={rec:.3f} F1={f1:.3f} AUC={auc:.3f}")

    # Aggregate
    avg_prec = np.mean([s["precision"] for s in fold_scores])
    avg_rec = np.mean([s["recall"] for s in fold_scores])
    avg_f1 = np.mean([s["f1"] for s in fold_scores])
    avg_auc = np.mean([s["auc"] for s in fold_scores])

    # Std dev (overfitting indicator)
    std_f1 = np.std([s["f1"] for s in fold_scores])

    print(f"\n[CV] Average across {N_SPLITS} folds:")
    print(f"  Precision: {avg_prec:.3f}")
    print(f"  Recall:    {avg_rec:.3f}")
    print(f"  F1:        {avg_f1:.3f}")
    print(f"  AUC:       {avg_auc:.3f}")
    print(f"  F1 StdDev: {std_f1:.3f}  (high = unstable/overfitting)")

    return {
        "fold_scores": fold_scores,
        "avg_precision": avg_prec,
        "avg_recall": avg_rec,
        "avg_f1": avg_f1,
        "avg_auc": avg_auc,
        "std_f1": std_f1,
    }


def train_final_model(X_train: np.ndarray, y_train: np.ndarray,
                      X_val: np.ndarray, y_val: np.ndarray) -> object:
    """Train final model with early stopping on validation set."""
    if HAS_XGBOOST:
        print(f"\n[TRAIN] Training final XGBoost with early stopping...")
        print(f"  Max depth: {XGB_PARAMS['max_depth']} (shallow)")
        print(f"  Reg alpha: {XGB_PARAMS['reg_alpha']} (L1)")
        print(f"  Reg lambda: {XGB_PARAMS['reg_lambda']} (L2)")
        print(f"  Min child weight: {XGB_PARAMS['min_child_weight']}")

        model = xgb.XGBClassifier(**XGB_PARAMS)
        
        # Use eval_set for early stopping (compatible with older XGBoost)
        try:
            model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                early_stopping_rounds=20,
                verbose=False,
            )
            print(f"[TRAIN] Best iteration: {model.best_iteration}")
        except TypeError:
            # Older XGBoost version — no early_stopping_rounds
            print("[TRAIN] Early stopping not supported in this XGBoost version.")
            print("[TRAIN] Training without early stopping...")
            model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    else:
        print(f"\n[TRAIN] Training final RandomForest...")
        model = RandomForestClassifier(**RF_PARAMS)
        model.fit(X_train, y_train)

    print("[TRAIN] Training complete")
    return model

def evaluate_model(model, X_test: np.ndarray, y_test: np.ndarray,
                   X_train: np.ndarray, y_train: np.ndarray,
                   features: list, cv_results: dict) -> dict:
    """Evaluate model on held-out test set."""
    print(f"\n[EVAL] Running predictions on TEST set...")

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    # Metrics
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0

    try:
        auc = roc_auc_score(y_test, y_proba)
    except Exception:
        auc = 0.0

    try:
        ap = average_precision_score(y_test, y_proba)
    except Exception:
        ap = 0.0

    # Train metrics (overfitting check)
    y_train_pred = model.predict(X_train)
    train_acc = np.mean(y_train_pred == y_train)
    train_f1 = 2 * (np.sum(y_train_pred & y_train) / np.sum(y_train_pred)) * \
               (np.sum(y_train_pred & y_train) / np.sum(y_train)) if np.sum(y_train) > 0 else 0

    print(f"\n{'='*60}")
    print("XGBOOST ENSEMBLE RESULTS (REGULARIZED)")
    print(f"{'='*60}")
    print(f"Test samples:     {len(y_test)}")
    print(f"Actual faults:    {y_test.sum()}")
    print(f"Predicted faults: {y_pred.sum()}")

    print(f"\nConfusion Matrix (TEST SET):")
    print(f"                 Pred-Normal  Pred-Fault")
    print(f"  Actual-Normal      {tn:4d}       {fp:4d}")
    print(f"  Actual-Fault       {fn:4d}       {tp:4d}")

    print(f"\nMetrics:")
    print(f"  Precision:   {precision:.3f}")
    print(f"  Recall:      {recall:.3f}")
    print(f"  F1-Score:    {f1:.3f}")
    print(f"  Specificity: {specificity:.3f}")
    print(f"  AUC-ROC:     {auc:.3f}")
    print(f"  Avg Precision:{ap:.3f}")
    print(f"\nOverfitting Check:")
    print(f"  Train Acc:   {train_acc:.3f}")
    print(f"  Test F1:     {f1:.3f}")
    print(f"  CV F1 (avg): {cv_results['avg_f1']:.3f}")
    print(f"  CV F1 (std): {cv_results['std_f1']:.3f}")
    print(f"  Gap (train-test): {abs(train_acc - (tp+tn)/len(y_test)):.3f}")

    print(f"\nClassification Report:")
    print(classification_report(y_test, y_pred, target_names=["Normal", "Fault"]))

    # Feature importance
    print(f"\n[EVAL] Feature Importance:")
    importances = model.feature_importances_
    feat_imp = list(zip(features, importances))
    feat_imp.sort(key=lambda x: x[1], reverse=True)
    for feat, imp in feat_imp:
        bar = "█" * int(imp * 50)
        print(f"  {feat:30s}: {imp:.4f} {bar}")

    print(f"{'='*60}")

    return {
        "model": "XGBoost_Regularized" if HAS_XGBOOST else "RandomForest",
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "specificity": specificity,
        "auc": auc,
        "avg_precision": ap,
        "train_acc": train_acc,
        "cv_avg_f1": cv_results["avg_f1"],
        "cv_std_f1": cv_results["std_f1"],
        "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn),
    }


def save_model(model, metrics: dict):
    """Save trained model and metrics."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    model_type = "xgboost_reg" if HAS_XGBOOST else "randomforest"
    model_path = os.path.join(MODELS_DIR, f"{model_type}_{timestamp}.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"\n[SAVE] Model: {model_path}")

    metrics_path = os.path.join(MODELS_DIR, f"metrics_ensemble_reg_{timestamp}.json")
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[SAVE] Metrics: {metrics_path}")


# ── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("NETWROXIA — XGBoost Ensemble (REGULARIZED)")
    print("=" * 60)

    # 1. Load data
    print("\n[1/5] Loading processed data...")
    X, y, features = load_latest_data()
    if X is None:
        return

    # 2. Cross-validation FIRST (detect overfitting before final train)
    print("\n[2/5] Cross-validation...")
    cv_results = cross_validate(X, y)

    # 3. Split: train/val/test
    print("\n[3/5] Splitting train/val/test...")
    X_temp, X_test, y_temp, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp, y_temp, test_size=0.2, random_state=RANDOM_STATE, stratify=y_temp
    )
    print(f"  Train: {len(X_train)} samples ({np.sum(y_train)} faults)")
    print(f"  Val:   {len(X_val)} samples ({np.sum(y_val)} faults)")
    print(f"  Test:  {len(X_test)} samples ({np.sum(y_test)} faults)")

    # 4. Train final model
    print("\n[4/5] Training final model with early stopping...")
    model = train_final_model(X_train, y_train, X_val, y_val)

    # 5. Evaluate on held-out test
    print("\n[5/5] Evaluating on held-out test set...")
    metrics = evaluate_model(model, X_test, y_test, X_train, y_train, features, cv_results)

    # Save
    save_model(model, metrics)

    print("\n" + "=" * 60)
    print("DONE — Regularized ensemble trained & saved")
    print("=" * 60)


if __name__ == "__main__":
    main()