#!/usr/bin/env python3
"""
Netwroxia Stage 3 — train_lstm.py
LSTM that predicts FAULT PROBABILITY and TIME-TO-IMPACT (TTI).
Not just "what is packet loss now" but "will there be a fault in 5 min?"
"""

import numpy as np
import pandas as pd
import json
import os
import glob
from datetime import datetime
from typing import Tuple, Optional, Dict

import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ── CONFIG ──────────────────────────────────────────────────────────────────
RAW_DIR = "ml/data/raw"
MODELS_DIR = "ml/models"

SEQUENCE_LENGTH = 15      # Look back 15 steps (~15 min of history)
PREDICTION_HORIZON = 5    # Predict fault 5 steps ahead (~5 min)
HIDDEN_SIZE = 32          # Slightly larger for complex patterns
NUM_LAYERS = 2            # 2 layers to capture trend
DROPOUT = 0.3             # Stronger dropout
BATCH_SIZE = 64
EPOCHS = 100
LEARNING_RATE = 0.001

# Fault definition
PACKET_LOSS_THRESHOLD = 50.0  # >50% = fault
LATENCY_THRESHOLD = 100.0   # >100ms = fault


class LSTMDataset(Dataset):
    def __init__(self, X, y_fault, y_tti):
        self.X = torch.FloatTensor(X)
        self.y_fault = torch.FloatTensor(y_fault)
        self.y_tti = torch.FloatTensor(y_tti)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y_fault[idx], self.y_tti[idx]


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
        self.fc_fault = nn.Linear(hidden_size, 1)   # Fault probability
        self.fc_tti = nn.Linear(hidden_size, 1)     # Time to impact (minutes)

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        last = lstm_out[:, -1, :]
        fault_prob = torch.sigmoid(self.fc_fault(last)).squeeze(-1)
        tti = torch.relu(self.fc_tti(last)).squeeze(-1)
        return fault_prob, tti


def load_ping_data():
    files = sorted(glob.glob(os.path.join(RAW_DIR, "ping_*.csv")))
    if not files:
        return None
    df = pd.read_csv(files[-1], parse_dates=["time"])
    print(f"[LOAD] Ping data: {len(df)} rows")
    return df


def build_sequences(df, router):
    """Build sequences where target = FAULT at horizon + TTI estimate."""
    router_df = df[df["router"] == router].copy().sort_values("time").reset_index(drop=True)
    if len(router_df) < SEQUENCE_LENGTH + PREDICTION_HORIZON + 20:
        return None, None, None, None, None

    # Features: latency, packet_loss, latency_rolling_mean, loss_rolling_mean, latency_trend
    router_df["latency_ma"] = router_df["average_response_ms"].fillna(0).rolling(3, min_periods=1).mean()
    router_df["loss_ma"] = router_df["percent_packet_loss"].fillna(0).rolling(3, min_periods=1).mean()
    router_df["latency_diff"] = router_df["average_response_ms"].fillna(0).diff().fillna(0)

    features = router_df[[
        "average_response_ms",
        "percent_packet_loss",
        "latency_ma",
        "loss_ma",
        "latency_diff"
    ]].fillna(0).values

    mean = features.mean(axis=0)
    std = features.std(axis=0) + 1e-8
    features_norm = (features - mean) / std

    X, y_fault, y_tti = [], [], []
    
    for i in range(len(features_norm) - SEQUENCE_LENGTH - PREDICTION_HORIZON):
        seq = features_norm[i:i + SEQUENCE_LENGTH]
        
        # Look at the FUTURE window to determine if fault occurs
        future_start = i + SEQUENCE_LENGTH
        future_end = future_start + PREDICTION_HORIZON
        
        future_loss = router_df["percent_packet_loss"].iloc[future_start:future_end].fillna(0).values
        future_lat = router_df["average_response_ms"].iloc[future_start:future_end].fillna(0).values
        
        # FAULT = any packet_loss > 50% OR latency > 100ms in future window
        is_fault = int(np.any(future_loss > PACKET_LOSS_THRESHOLD) or 
                       np.any(future_lat > LATENCY_THRESHOLD))
        
        # TTI = steps until first fault in future window (or max if no fault)
        fault_indices = np.where((future_loss > PACKET_LOSS_THRESHOLD) | 
                                  (future_lat > LATENCY_THRESHOLD))[0]
        if len(fault_indices) > 0:
            tti = fault_indices[0]  # Steps until fault
        else:
            tti = PREDICTION_HORIZON  # No fault predicted
        
        X.append(seq)
        y_fault.append(is_fault)
        y_tti.append(tti)

    return np.array(X), np.array(y_fault), np.array(y_tti), mean, std


def train_model(X_train, yf_train, yt_train, X_val, yf_val, yt_val):
    device = torch.device("cpu")
    input_size = X_train.shape[2]
    
    model = LSTMPredictor(input_size).to(device)
    
    train_ds = LSTMDataset(X_train, yf_train, yt_train)
    val_ds = LSTMDataset(X_val, yf_val, yt_val)
    
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE)
    
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
    
    bce_loss = nn.BCELoss()
    mse_loss = nn.MSELoss()
    
    best_val_loss = float("inf")
    best_state = None
    patience = 0
    max_patience = 20

    print(f"\n[TRAIN] Training LSTM Predictor...")
    print(f"  Input: {input_size} features")
    print(f"  Hidden: {HIDDEN_SIZE}, Layers: {NUM_LAYERS}")
    print(f"  Seq len: {SEQUENCE_LENGTH}, Horizon: {PREDICTION_HORIZON}")
    print(f"  Target: FAULT in {PREDICTION_HORIZON} steps + TTI")

    for epoch in range(EPOCHS):
        model.train()
        train_loss = 0.0
        
        for X_batch, yf_batch, yt_batch in train_loader:
            X_batch = X_batch.to(device)
            yf_batch = yf_batch.to(device)
            yt_batch = yt_batch.to(device)
            
            optimizer.zero_grad()
            pred_fault, pred_tti = model(X_batch)
            
            loss = bce_loss(pred_fault, yf_batch) + 0.1 * mse_loss(pred_tti, yt_batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()
        
        train_loss /= len(train_loader)
        
        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for X_batch, yf_batch, yt_batch in val_loader:
                X_batch = X_batch.to(device)
                yf_batch = yf_batch.to(device)
                yt_batch = yt_batch.to(device)
                pred_fault, pred_tti = model(X_batch)
                loss = bce_loss(pred_fault, yf_batch) + 0.1 * mse_loss(pred_tti, yt_batch)
                val_loss += loss.item()
        
        val_loss /= len(val_loader)
        scheduler.step(val_loss)
        
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = model.state_dict().copy()
            patience = 0
        else:
            patience += 1
        
        if (epoch + 1) % 10 == 0:
            print(f"  Epoch {epoch+1:3d}: train={train_loss:.4f}, val={val_loss:.4f}")
        
        if patience >= max_patience:
            print(f"[TRAIN] Early stopping at epoch {epoch+1}")
            break
    
    if best_state:
        model.load_state_dict(best_state)
    
    print(f"[TRAIN] Best val_loss: {best_val_loss:.4f}")
    return model


def evaluate(model, X_test, yf_test, yt_test, mean, std):
    device = torch.device("cpu")
    model.eval()
    
    X_t = torch.FloatTensor(X_test).to(device)
    with torch.no_grad():
        pred_fault, pred_tti = model(X_t)
    
    pred_fault = pred_fault.cpu().numpy()
    pred_tti = pred_tti.cpu().numpy()
    
    # Binary predictions
    pred_binary = (pred_fault > 0.5).astype(int)
    
    # Metrics
    tp = np.sum((pred_binary == 1) & (yf_test == 1))
    fp = np.sum((pred_binary == 1) & (yf_test == 0))
    fn = np.sum((pred_binary == 0) & (yf_test == 1))
    tn = np.sum((pred_binary == 0) & (yf_test == 0))
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    # TTI accuracy (only for actual faults)
    fault_mask = yf_test == 1
    if np.sum(fault_mask) > 0:
        tti_mae = np.mean(np.abs(pred_tti[fault_mask] - yt_test[fault_mask]))
    else:
        tti_mae = 0.0
    
    print(f"\n{'='*60}")
    print("LSTM FAULT PREDICTION RESULTS")
    print(f"{'='*60}")
    print(f"Total test samples: {len(yf_test)}")
    print(f"Actual future faults: {np.sum(yf_test)}")
    print(f"Predicted faults: {np.sum(pred_binary)}")
    print(f"\nConfusion Matrix:")
    print(f"                 Pred-Normal  Pred-Fault")
    print(f"  Actual-Normal      {tn:4d}       {fp:4d}")
    print(f"  Actual-Fault       {fn:4d}       {tp:4d}")
    print(f"\nMetrics:")
    print(f"  Precision: {precision:.3f}")
    print(f"  Recall:    {recall:.3f}")
    print(f"  F1:        {f1:.3f}")
    print(f"\nTime-to-Impact (TTI):")
    print(f"  MAE: {tti_mae:.2f} steps (~{tti_mae:.1f} min)")
    print(f"{'='*60}")
    
    return {
        "precision": precision, "recall": recall, "f1": f1,
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "tti_mae": tti_mae
    }


def save_model(model, metrics, mean, std):
    os.makedirs(MODELS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    path = os.path.join(MODELS_DIR, f"lstm_predictor_{ts}.pt")
    torch.save({
        "model_state": model.state_dict(),
        "mean": mean, "std": std,
        "hidden_size": HIDDEN_SIZE,
        "num_layers": NUM_LAYERS,
        "sequence_length": SEQUENCE_LENGTH,
        "horizon": PREDICTION_HORIZON,
    }, path)
    print(f"\n[SAVE] Model: {path}")
    
    mpath = os.path.join(MODELS_DIR, f"metrics_lstm_predictor_{ts}.json")
    with open(mpath, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"[SAVE] Metrics: {mpath}")


def main():
    print("=" * 60)
    print("NETWROXIA — LSTM Fault Predictor + TTI")
    print("=" * 60)
    
    df = load_ping_data()
    if df is None:
        return
    
    print("\n[2/5] Building sequences...")
    all_X, all_yf, all_yt = [], [], []
    stats = {}
    
    for router in df["router"].dropna().unique():
        print(f"  {router}...")
        result = build_sequences(df, router)
        if result[0] is not None and len(result[0]) > 0:
            X, yf, yt, mean, std = result
            all_X.append(X)
            all_yf.append(yf)
            all_yt.append(yt)
            stats[router] = {"mean": mean, "std": std, "count": len(X)}
            print(f"    {len(X)} sequences, faults: {np.sum(yf)}/{len(yf)}")
    
    if not all_X:
        print("[ERROR] No sequences")
        return
    
    X = np.concatenate(all_X)
    yf = np.concatenate(all_yf)
    yt = np.concatenate(all_yt)
    
    print(f"\n[OK] Total: {len(X)} sequences")
    print(f"     Fault rate: {np.mean(yf)*100:.1f}%")
    
    # Stratified split to preserve fault ratio
    from sklearn.model_selection import train_test_split
    
    # First: split into train+val and test (15% test)
    X_temp, X_test, yf_temp, yf_test, yt_temp, yt_test = train_test_split(
        X, yf, yt, test_size=0.15, random_state=42, stratify=yf
    )
    
    # Second: split train+val into train and val (15% val of total = ~17.6% of temp)
    X_train, X_val, yf_train, yf_val, yt_train, yt_val = train_test_split(
        X_temp, yf_temp, yt_temp, test_size=0.176, random_state=42, stratify=yf_temp
    )
    
    print(f"\n[3/5] Split: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")
    
    # Train
    print("\n[4/5] Training...")
    model = train_model(X_train, yf_train, yt_train, X_val, yf_val, yt_val)
    
    # Evaluate
    print("\n[5/5] Evaluating...")
    first = list(stats.keys())[0]
    metrics = evaluate(model, X_test, yf_test, yt_test, stats[first]["mean"], stats[first]["std"])
    
    save_model(model, metrics, stats[first]["mean"], stats[first]["std"])
    
    print("\n" + "=" * 60)
    print("DONE — LSTM Fault Predictor trained")
    print("=" * 60)


if __name__ == "__main__":
    main()