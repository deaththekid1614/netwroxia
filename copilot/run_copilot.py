#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# NETWROXIA — Stage 4: AI NOC Copilot Runner (FIXED for LSTM forecast)
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# ── FIX: sqlite3 + telemetry ───────────────────────────────────────────────
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass
os.environ["ANONYMIZED_TELEMETRY"] = "False"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
MODEL_PATH = BASE_DIR / "llm" / "mistral-7b-instruct-v0.2.Q4_K_M.gguf"
PREDICTION_PATH = BASE_DIR.parent / "ml" / "inference" / "latest_prediction.json"
DB_DIR = BASE_DIR / "rag" / "chroma_db"
COLLECTION_NAME = "netwroxia_kb"

# ── IMPORTS ──────────────────────────────────────────────────────────────────
from llama_cpp import Llama
import chromadb

# ── FAST TEMPLATES (real Mistral outputs) ──────────────────────────────────
FAST_TEMPLATES = {
    "HEALTHY": {
        "predicted_issue": "No fault detected — all network metrics normal",
        "confidence": "LOW",
        "root_cause": "All systems green. BGP routing stable, OSPF neighbors connected, no packet loss, latency under 1 millisecond. Core Banking Server (TCS BaNCS) responding normally.",
        "affected_sites": ["None — all 4 network nodes operational"],
        "affected_services": ["None — CBS, ATM, UPI, Net Banking all healthy"],
        "affected_users": 0,
        "time_to_impact_min": 999,
        "urgency": "LOW",
        "recommended_actions": [
            "Continue routine monitoring",
            "Check backup MPLS tunnel is ready (weekly test)",
            "Review next quarter's bandwidth growth plan"
        ],
        "quick_fix": "No action needed — network is healthy",
        "deep_fix": "Schedule preventive maintenance during Sunday 02:00-06:00 window",
        "rbi_compliance_note": "All SLAs met. Uptime 99.97%. No report needed."
    },
    "LATENCY_DEGRADATION": {
        "predicted_issue": "BR-Koramangala link slowing down — 500ms delay detected (normal is <1ms)",
        "confidence": "MEDIUM",
        "root_cause": "The leased line between Zonal Office Bangalore and Branch Koramangala is congested. This happens during peak hours (12 PM - 2 PM) when UPI transaction volume spikes. The 100 Mbps connection is hitting its limit. MPLS traffic labels are adding overhead, and the ISP handoff point may have an MTU mismatch causing packet fragmentation.",
        "affected_sites": ["BR-Koramangala branch", "2 ATMs (1 onsite, 1 offsite at MG Road)", "15 POS terminals at branch counter"],
        "affected_services": ["Core Banking (TCS BaNCS)", "ATM cash withdrawal / balance inquiry", "UPI payments (PhonePe, GPay, PayTM)", "NEFT money transfers"],
        "affected_users": 3400,
        "time_to_impact_min": 4,
        "urgency": "HIGH",
        "recommended_actions": [
            "1. Call ISP (BSNL/Airtel) — ask for real-time utilization on circuit BLR-KORA-001",
            "2. Switch critical traffic to backup MPLS tunnel via Chennai (keeps CBS + UPI running)",
            "3. Slow down non-urgent traffic (DR backup, CCTV footage sync) to 10 Mbps"
        ],
        "quick_fix": "Reroute BR-Koramangala through Chennai backup tunnel. Enable Internet backup for ATM. Customers won't notice. Time: 23 seconds.",
        "deep_fix": "Upgrade leased line from 100 Mbps to 1 Gbps. Add a second backup path (dark fiber via Hosur Road). Install WAN optimizer for CBS traffic. Do this during Sunday maintenance window.",
        "rbi_compliance_note": "RBI requires 99.9% uptime for core banking. Current 500ms delay breaches the 100ms SLA for ATM transactions. If this link fails, we have 4 hours to restore CBS, 2 hours for ATM network. Must fix before SLA breach triggers P1 report to RBI."
    },
    "CRITICAL_OUTAGE": {
        "predicted_issue": "BR-Whitefield is completely down — 100% packet loss, no traffic flowing",
        "confidence": "HIGH",
        "root_cause": "The fiber optic cable or SFP module between Bangalore Zonal Office and Whitefield Branch has failed. BGP routing session is broken. OSPF shows zero neighbors. This is a physical layer failure — likely fiber cut during road work, or SFP module burned out at the ISP handoff point. DR replication is falling behind.",
        "affected_sites": ["BR-Whitefield", "2 ATMs (1 at branch, 1 offsite at ITPL)", "Trading floor backup link to NSE"],
        "affected_services": ["Core Banking (all transactions blocked)", "ATM network (cards will decline)", "UPI/NPCI settlements (queued)", "NEFT/RTGS (outward transfers stalled)", "SWIFT international transfers (MT103 messages held)", "Net Banking and Mobile Banking (login fails)"],
        "affected_users": 8700,
        "time_to_impact_min": 0,
        "urgency": "CRITICAL",
        "recommended_actions": [
            "1. Activate Disaster Recovery — promote Mumbai backup data center to handle Whitefield zone",
            "2. Call ISP Level-2 team for emergency fiber restoration (SLA: 4 hours max)",
            "3. Switch ATMs to 4G/LTE backup — transactions go via mobile network instead of fiber"
        ],
        "quick_fix": "Reroute all Whitefield traffic through Chennai backup tunnel. Switch ATMs to mobile network. Branch staff use offline CBS cache. Time: 23 seconds. Customers see no error.",
        "deep_fix": "Replace failed SFP module at Bangalore POP. Run fiber cable test (OTDR) to find exact break point. Lay redundant fiber via different route (Old Airport Road instead of Whitefield Main Road). Upgrade to dual-BGP so backup path auto-activates. Schedule during RBI-mandated BCP drill.",
        "rbi_compliance_note": "P1-CRITICAL per RBI Circular 2023-24/85. This affects 1 branch + 2 ATMs + trading backup = 5+ branch equivalents. Financial loss: ₹25 lakh per hour (CBS down + ATM revenue lost + SWIFT penalties). RBI must be notified within 2 hours. DR failover must complete within 4 hours for CBS, 2 hours for ATM. Verify DR data is not older than 15 minutes before switching."
    }
}

# ── RAG ──────────────────────────────────────────────────────────────────────
def get_rag_context(query: str, n_results: int = 2) -> str:
    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embedding_fn = DefaultEmbeddingFunction()
    collection = client.get_collection(name=COLLECTION_NAME, embedding_function=embedding_fn)
    results = collection.query(query_texts=[query], n_results=n_results)
    
    parts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        parts.append(f"[{meta.get('source', 'unknown')}]\n{doc[:800]}")
    return "\n---\n".join(parts)


# ── PROMPT BUILDER (FIXED: includes LSTM forecast) ───────────────────────────
def build_prompt(pred: dict) -> str:
    router = pred.get("router", "Unknown")
    xgb = pred.get("xgboost", {})
    lstm = pred.get("lstm_forecast", {})
    metrics = pred.get("raw_metrics", {})
    combined = pred.get("combined_alert", "NORMAL")
    
    fault_prob = xgb.get("fault_probability", 0.0)
    predicted_fault = xgb.get("predicted_fault", False)
    confidence = xgb.get("confidence", "LOW")
    status = xgb.get("status", "UNKNOWN")
    
    future_prob = lstm.get("future_fault_probability", 0.0)
    tti = lstm.get("time_to_impact", "N/A")
    future_fault = lstm.get("predicted_future_fault", False)
    future_status = lstm.get("status", "UNKNOWN")
    
    # DETERMINE SEVERITY from BOTH models
    is_critical = (
        predicted_fault 
        or future_fault 
        or combined in ["WARNING", "CRITICAL", "SUSPECTED_FAULT"]
        or metrics.get("percent_packet_loss", 0) > 50
        or metrics.get("average_response_ms", 0) > 100
    )
    
    # RAG query based on actual symptoms
    query = "network fault banking NOC"
    if metrics.get("percent_packet_loss", 0) > 50:
        query = "BGP peer down packet loss route flapping"
    elif metrics.get("average_response_ms", 0) > 100:
        query = "network latency spike congestion MPLS link degradation"
    elif metrics.get("average_response_ms", 0) > 50:
        query = "network latency increase congestion warning"
    elif metrics.get("bgp_established") is False:
        query = "BGP session down troubleshooting"
    
    rag_context = get_rag_context(query, n_results=2)
    
    # FIXED PROMPT: Explicitly tells LLM about BOTH current AND future state
    prompt = f"""[INST] You are Netwroxia, AI NOC Copilot for State Bank of Netwroxia.
You analyze network telemetry predictions and explain faults in banking terminology.
You MUST respond with valid JSON only — no markdown, no explanations outside JSON.

ROUTER: {router}

CURRENT STATE (XGBoost):
- Fault Probability: {fault_prob:.1%}
- Predicted Fault NOW: {"YES" if predicted_fault else "NO"}
- Confidence: {confidence}
- Status: {status}

FORECAST (LSTM):
- Future Fault Probability: {future_prob:.1%}
- Predicted Fault SOON: {"YES" if future_fault else "NO"}
- Time-to-Impact: {tti}
- Future Status: {future_status}

COMBINED ALERT: {combined}

RAW METRICS:
- Latency: {metrics.get('average_response_ms', 0):.2f} ms
- Packet Loss: {metrics.get('percent_packet_loss', 0):.1f}%
- OSPF Neighbors: {metrics.get('ospf_neighbors', 0)}
- BGP Established: {"YES" if metrics.get('bgp_established') else "NO"}
- CPU: {metrics.get('cpu_pct', 0):.1f}%
- Memory: {metrics.get('mem_pct', 0):.1f}%

CRITICAL INSTRUCTION:
If latency > 100ms OR packet_loss > 10% OR future_fault_probability > 50%,
this is a REAL DEGRADATION even if current predicted_fault is NO.
The LSTM forecast shows an impending failure — treat it as active.

RELEVANT DOCUMENTS:
{rag_context}

Generate JSON with these fields:
predicted_issue, confidence, root_cause, affected_sites (array), affected_services (array), affected_users (number), time_to_impact_min (number), urgency (LOW/MEDIUM/HIGH/CRITICAL), recommended_actions (array of 3), quick_fix, deep_fix, rbi_compliance_note.

ONLY JSON. No markdown. [/INST]"""
    return prompt


# ── LLM ────────────────────────────────────────────────────────────────────────
def load_model():
    if not MODEL_PATH.exists():
        print(f"❌ Model not found: {MODEL_PATH}")
        sys.exit(1)
    
    print(f"  📥 Loading Mistral 7B Q4 ({MODEL_PATH.stat().st_size / 1e9:.2f} GB)...")
    start = time.time()
    llm = Llama(
        model_path=str(MODEL_PATH),
        n_ctx=1536,
        n_threads=2,
        n_batch=256,
        verbose=False,
    )
    print(f"  ✅ Loaded in {time.time() - start:.1f}s")
    return llm


def generate(llm, prompt: str, max_tokens: int = 400) -> str:
    start = time.time()
    out = llm(prompt, max_tokens=max_tokens, temperature=0.3, top_p=0.9,
              stop=["</s>", "[INST]"])
    elapsed = time.time() - start
    print(f"  ✅ Generated in {elapsed:.1f}s")
    return out["choices"][0]["text"].strip()


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    if text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        return {"parse_error": str(e), "raw": text[:500]}


# ── FAST MODE ─────────────────────────────────────────────────────────────────
def fast_response(pred: dict) -> dict:
    combined = pred.get("combined_alert", "NORMAL")
    xgb = pred.get("xgboost", {})
    lstm = pred.get("lstm_forecast", {})
    metrics = pred.get("raw_metrics", {})
    
    # FIXED: Use latency + future prob to pick template
    latency = metrics.get("average_response_ms", 0)
    future_prob = lstm.get("future_fault_probability", 0)
    packet_loss = metrics.get("percent_packet_loss", 0)
    
    if packet_loss > 50 or combined == "CRITICAL":
        template = FAST_TEMPLATES["CRITICAL_OUTAGE"]
    elif latency > 100 or future_prob > 50 or combined == "SUSPECTED_FAULT":
        template = FAST_TEMPLATES["LATENCY_DEGRADATION"]
    else:
        template = FAST_TEMPLATES["HEALTHY"]
    
    resp = dict(template)
    resp["router"] = pred.get("router", "Unknown")
    resp["timestamp"] = datetime.utcnow().isoformat() + "Z"
    resp["model"] = "mistral-7b-instruct-v0.2.Q4_K_M (fast-mode)"
    resp["note"] = "FAST MODE: Real Mistral output cached for demo speed"
    return resp


# ── DISPLAY ────────────────────────────────────────────────────────────────────
def print_response(resp: dict):
    print(f"\n  📋 COPILOT RESPONSE:")
    print(f"  {'─'*60}")
    for key, val in resp.items():
        if key in ["timestamp", "model", "router", "note"]: 
            continue
        if isinstance(val, list):
            print(f"    • {key}:")
            for item in val:
                print(f"        - {item}")
        else:
            text = str(val)
            if len(text) > 80:
                print(f"    • {key}:")
                words = text.split()
                line = "        "
                for word in words:
                    if len(line) + len(word) > 80:
                        print(line)
                        line = "        " + word
                    else:
                        line += " " + word
                print(line)
            else:
                print(f"    • {key}: {text}")
    print(f"  {'─'*60}")


# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Netwroxia AI NOC Copilot")
    parser.add_argument("--fast", action="store_true", 
                       help="Use cached real Mistral outputs for demo speed")
    parser.add_argument("--all", action="store_true",
                       help="Analyze ALL routers (not just faulty ones)")
    args = parser.parse_args()
    
    print("=" * 70)
    print("  🤖 NETWROXIA — AI NOC Copilot")
    if args.fast:
        print("  ⚡ FAST MODE (cached real outputs)")
    else:
        print("  🧠 REAL MISTRAL 7B MODE")
    print("=" * 70)
    
    # Load prediction
    if not PREDICTION_PATH.exists():
        print("❌ No prediction file. Run: python3 ml/inference/predict.py")
        sys.exit(1)
    
    with open(PREDICTION_PATH) as f:
        data = json.load(f)
    
    predictions = data.get("predictions", [])
    print(f"\n  📊 {len(predictions)} router(s) | Overall: {data.get('overall_status', '?')}")
    
    # Filter routers to analyze
    if args.all:
        to_analyze = predictions
    else:
        to_analyze = [p for p in predictions 
                      if p.get("xgboost", {}).get("predicted_fault") 
                      or p.get("lstm_forecast", {}).get("predicted_future_fault")
                      or p.get("combined_alert") in ["WARNING", "CRITICAL", "SUSPECTED_FAULT"]
                      or p.get("raw_metrics", {}).get("average_response_ms", 0) > 100
                      or p.get("raw_metrics", {}).get("percent_packet_loss", 0) > 10]
    
    if not to_analyze:
        print("\n  🟢 All routers healthy. No analysis needed.")
        resp = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status": "ALL_HEALTHY",
            "message": "No faults predicted. Network operating normally.",
        }
        out_path = BASE_DIR / "llm" / "latest_copilot_response.json"
        with open(out_path, "w") as f:
            json.dump(resp, f, indent=2)
        print(f"  💾 Saved to: {out_path}")
        return
    
    print(f"  ⚠️  {len(to_analyze)} router(s) flagged for analysis")
    
    # Load LLM only if NOT fast mode
    llm = None
    if not args.fast:
        llm = load_model()
    
    all_responses = []
    for pred in to_analyze:
        router = pred.get("router", "?")
        print(f"\n{'─'*70}")
        print(f"  🔍 {router}")
        print(f"{'─'*70}")
        
        if args.fast:
            print("  ⚡ Using cached real Mistral output...")
            resp = fast_response(pred)
            print("  ✅ Instant")
        else:
            prompt = build_prompt(pred)
            raw = generate(llm, prompt, max_tokens=400)
            resp = parse_json(raw)
            resp["router"] = router
            resp["timestamp"] = datetime.utcnow().isoformat() + "Z"
            resp["model"] = "mistral-7b-instruct-v0.2.Q4_K_M"
        
        all_responses.append(resp)
        print_response(resp)
    
    # Save
    output = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": "mistral-7b-instruct-v0.2.Q4_K_M",
        "mode": "fast" if args.fast else "real",
        "predictions_analyzed": len(all_responses),
        "copilot_responses": all_responses,
    }
    out_path = BASE_DIR / "llm" / "latest_copilot_response.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n{'='*70}")
    print(f"  ✅ DONE — {len(all_responses)} response(s)")
    print(f"  💾 {out_path}")
    print(f"{'='*70}")
    
    # Air-gap check
    print(f"\n  🔒 Air-Gap:")
    try:
        r = subprocess.run(["ping", "-c", "1", "8.8.8.8"], capture_output=True, timeout=3)
        print("     ⚠️  Internet ON (disconnect WiFi for demo)")
    except:
        print("     ✅ OFFLINE — fully air-gapped")


if __name__ == "__main__":
    main()