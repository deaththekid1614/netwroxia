#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════════
# NETWROXIA — Stage 4: Offline LLM Copilot Inference
# Loads Mistral 7B Q4, reads Stage 3 predictions, retrieves RAG docs,
# generates structured banking explanation + remediation actions.
# ═══════════════════════════════════════════════════════════════════════════════

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# ── FIX: sqlite3 override BEFORE any import ──────────────────────────────────
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

# ── FIX: Disable ChromaDB telemetry ───────────────────────────────────────────
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ── CONFIG ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent.resolve()
MODEL_PATH = BASE_DIR / "llm" / "mistral-7b-instruct-v0.2.Q4_K_M.gguf"
PREDICTION_PATH = BASE_DIR.parent / "ml" / "inference" / "latest_prediction.json"
DB_DIR = BASE_DIR / "rag" / "chroma_db"
COLLECTION_NAME = "netwroxia_kb"

# ── IMPORTS ──────────────────────────────────────────────────────────────────
try:
    from llama_cpp import Llama
    import chromadb
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    sys.exit(1)


# ── RAG RETRIEVER ────────────────────────────────────────────────────────────
def get_rag_context(query: str, n_results: int = 3) -> str:
    """Retrieve relevant docs from ChromaDB for the LLM prompt."""
    client = chromadb.PersistentClient(
        path=str(DB_DIR),
        settings=chromadb.Settings(anonymized_telemetry=False),
    )
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embedding_fn = DefaultEmbeddingFunction()
    
    collection = client.get_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
    )
    
    results = collection.query(
        query_texts=[query],
        n_results=n_results,
    )
    
    context_parts = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        source = meta.get("source", "unknown")
        context_parts.append(f"[Source: {source}]\n{doc}\n")
    
    return "\n---\n".join(context_parts)


# ── PROMPT BUILDER ────────────────────────────────────────────────────────────
def build_prompt(prediction: dict) -> str:
    """Build a structured banking prompt from Stage 3 prediction JSON."""
    
    router = prediction.get("router", "Unknown")
    xgb = prediction.get("xgboost", {})
    lstm = prediction.get("lstm_forecast", {})
    metrics = prediction.get("raw_metrics", {})
    
    fault_prob = xgb.get("fault_probability", 0.0)
    predicted_fault = xgb.get("predicted_fault", False)
    confidence = xgb.get("confidence", "LOW")
    status = xgb.get("status", "UNKNOWN")
    
    future_prob = lstm.get("future_fault_probability", 0.0)
    tti = lstm.get("time_to_impact", "N/A")
    future_fault = lstm.get("predicted_future_fault", False)
    
    # Determine query for RAG based on symptoms
    query_parts = []
    if metrics.get("percent_packet_loss", 0) > 50:
        query_parts.append("BGP peer down packet loss route flapping")
    if metrics.get("bgp_established") is False:
        query_parts.append("BGP session down troubleshooting")
    if metrics.get("average_response_ms", 0) > 100:
        query_parts.append("network latency spike congestion")
    if not query_parts:
        query_parts.append("network fault prediction banking NOC")
    
    rag_query = " ".join(query_parts)
    
    # Retrieve context
    rag_context = get_rag_context(rag_query, n_results=2)
    
    # Build the prompt
    prompt = f"""<s>[INST] You are Netwroxia, an AI NOC Copilot for a Tier-1 Indian bank network.
You analyze network telemetry predictions and explain faults in banking terminology.
You MUST respond with valid JSON only — no markdown, no explanations outside JSON.

NETWORK PREDICTION DATA:
- Router: {router}
- Fault Probability (Current): {fault_prob:.1%}
- Predicted Fault: {"YES" if predicted_fault else "NO"}
- Confidence: {confidence}
- Status: {status}
- Future Fault Probability: {future_prob:.1%}
- Time-to-Impact: {tti}

RAW METRICS:
- Latency: {metrics.get('average_response_ms', 0):.2f} ms
- Packet Loss: {metrics.get('percent_packet_loss', 0):.1f}%
- OSPF Neighbors: {metrics.get('ospf_neighbors', 0)}
- BGP Established: {"YES" if metrics.get('bgp_established') else "NO"}
- CPU: {metrics.get('cpu_pct', 0):.1f}%
- Memory: {metrics.get('mem_pct', 0):.1f}%

RELEVANT KNOWLEDGE BASE DOCUMENTS:
{rag_context}

TASK: Analyze this prediction and generate a structured JSON response with these exact fields:
- predicted_issue: Short description of the predicted network issue
- confidence: Same as input confidence
- root_cause: Technical explanation of WHY this is happening
- affected_sites: List of affected network sites (use banking terms: branches, ATMs, trading floor)
- affected_services: List of affected banking services (CBS, UPI, ATM, Net Banking, etc.)
- affected_users: Estimated number of affected customers
- time_to_impact_min: Numeric value from TTI or estimate
- urgency: LOW / MEDIUM / HIGH / CRITICAL
- recommended_actions: List of 3 specific remediation steps
- quick_fix: One-line auto-remediation action
- deep_fix: Long-term fix requiring engineer approval
- rbi_compliance_note: Any RBI reporting requirement triggered

Respond ONLY with valid JSON. No markdown fences, no extra text. [/INST]</s>
"""
    return prompt


# ── LLM INFERENCE ────────────────────────────────────────────────────────────
def load_model():
    """Load Mistral 7B Q4 with conservative settings for 8GB RAM."""
    if not MODEL_PATH.exists():
        print(f"❌ Model not found: {MODEL_PATH}")
        print("Run: bash copilot/llm/download_model.sh")
        sys.exit(1)
    
    print(f"  📥 Loading Mistral 7B Q4...")
    print(f"     Path: {MODEL_PATH}")
    print(f"     Size: {MODEL_PATH.stat().st_size / 1e9:.2f} GB")
    print(f"     This may take 30-60 seconds on first load...")
    
    start = time.time()
    llm = Llama(
        model_path=str(MODEL_PATH),
        n_ctx=2048,           # Context window
        n_threads=4,          # Use 4 CPU cores (your i5 has 4 threads)
        n_batch=512,          # Batch size for inference
        verbose=False,        # Suppress llama.cpp spam
    )
    elapsed = time.time() - start
    print(f"  ✅ Model loaded in {elapsed:.1f}s")
    return llm


def generate_response(llm, prompt: str, max_tokens: int = 800) -> str:
    """Generate structured JSON response from Mistral."""
    print(f"  🧠 Generating response (max {max_tokens} tokens)...")
    
    start = time.time()
    output = llm(
        prompt,
        max_tokens=max_tokens,
        temperature=0.3,      # Low temp = more deterministic/factual
        top_p=0.9,
        stop=["</s>", "[INST]"],  # Stop at end of response
    )
    elapsed = time.time() - start
    
    text = output["choices"][0]["text"].strip()
    print(f"  ✅ Response generated in {elapsed:.1f}s")
    return text


def parse_json_response(text: str) -> dict:
    """Extract and validate JSON from LLM output."""
    # Try to find JSON in the text
    text = text.strip()
    
    # Remove markdown fences if present
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse failed: {e}")
        print(f"  Raw output (first 500 chars):\n{text[:500]}")
        # Return raw text wrapped
        return {
            "raw_response": text,
            "parse_error": str(e),
            "predicted_issue": "JSON parse failed — see raw_response",
        }


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  NETWROXIA — Offline LLM Copilot")
    print("=" * 70)
    
    # 1. Check prediction file exists
    if not PREDICTION_PATH.exists():
        print(f"❌ Prediction file not found: {PREDICTION_PATH}")
        print("Run: python3 ml/inference/predict.py")
        sys.exit(1)
    
    # 2. Load prediction
    with open(PREDICTION_PATH) as f:
        prediction_data = json.load(f)
    
    predictions = prediction_data.get("predictions", [])
    if not predictions:
        print("⚠️  No predictions found in file.")
        sys.exit(0)
    
    print(f"\n  📊 Loaded {len(predictions)} router prediction(s)")
    print(f"  Overall Status: {prediction_data.get('overall_status', 'UNKNOWN')}")
    
    # 3. Load LLM (once for all predictions)
    llm = load_model()
    
    # 4. Process each router prediction
    all_responses = []
    for pred in predictions:
        router = pred.get("router", "Unknown")
        print(f"\n{'─'*70}")
        print(f"  🔍 Analyzing: {router}")
        print(f"{'─'*70}")
        
        # Build prompt with RAG
        prompt = build_prompt(pred)
        
        # Generate
        raw_text = generate_response(llm, prompt, max_tokens=800)
        
        # Parse
        response = parse_json_response(raw_text)
        response["router"] = router
        response["timestamp"] = datetime.utcnow().isoformat() + "Z"
        response["model"] = "mistral-7b-instruct-v0.2.Q4_K_M"
        
        all_responses.append(response)
        
        # Pretty print
        print(f"\n  📋 COPILOT RESPONSE:")
        print(f"  {'─'*50}")
        for key, val in response.items():
            if key in ["timestamp", "model", "router"]:
                continue
            if isinstance(val, list):
                print(f"  • {key}:")
                for item in val:
                    print(f"      - {item}")
            else:
                print(f"  • {key}: {val}")
        print(f"  {'─'*50}")
    
    # 5. Save all responses
    output = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": "mistral-7b-instruct-v0.2.Q4_K_M",
        "predictions_analyzed": len(all_responses),
        "copilot_responses": all_responses,
    }
    
    output_path = BASE_DIR / "llm" / "latest_copilot_response.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n{'='*70}")
    print("  ✅ COPILOT ANALYSIS COMPLETE")
    print(f"{'='*70}")
    print(f"\n  Output saved: {output_path}")
    print(f"  Total routers analyzed: {len(all_responses)}")
    
    # 6. Air-gap verification
    print(f"\n  🔒 Air-Gap Check:")
    import subprocess
    try:
        subprocess.run(["ping", "-c", "1", "8.8.8.8"],
                      capture_output=True, timeout=5)
        print("     ⚠️  Internet detected (ping to 8.8.8.8 succeeded)")
    except Exception:
        print("     ✅ No internet — fully air-gapped")


if __name__ == "__main__":
    main()
