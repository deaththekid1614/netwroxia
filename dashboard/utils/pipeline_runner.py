"""
Netwroxia Dashboard — Pipeline Runner
Executes Stage 3 (ML) + Stage 4 (Copilot) via subprocess.
Safe: read-only on Stages 1-2, writes only to ml/ and copilot/ output files.
"""
import subprocess
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime

# ── Paths ───────────────────────────────────────────────
PROJECT_ROOT = Path("/home/death-kid/IDE/netwroxia")
ML_DATA = PROJECT_ROOT / "ml" / "data"
ML_MODELS = PROJECT_ROOT / "ml" / "models"
ML_INFERENCE = PROJECT_ROOT / "ml" / "inference"
COPILOT = PROJECT_ROOT / "copilot"

# ── Pipeline Steps ──────────────────────────────────────
STEPS = [
    ("📡 Fetch Metrics",     ["python3", str(ML_DATA / "fetch_metrics.py")]),
    ("🔧 Engineer Features", ["python3", str(ML_DATA / "feature_engineer.py")]),
    ("🔮 Run Prediction",    ["python3", str(ML_INFERENCE / "predict.py")]),
    ("🤖 Run Copilot",       ["python3", str(COPILOT / "run_copilot.py"), "--fast"]),
]

# ── Runner ──────────────────────────────────────────────
def run_pipeline(verbose: bool = True) -> Tuple[bool, List[Dict]]:
    """
    Runs the full prediction + copilot pipeline.
    Returns (all_success, list_of_step_results).
    """
    results = []
    all_ok = True

    for name, cmd in STEPS:
        step = {"name": name, "cmd": " ".join(cmd), "success": False, "output": "", "error": ""}
        if verbose:
            print(f"\n{'='*50}\n{name}\n{'='*50}")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                timeout=120,  # 2 min per step max
            )
            step["output"] = proc.stdout
            step["error"] = proc.stderr
            step["success"] = (proc.returncode == 0)
            if not step["success"]:
                all_ok = False
            if verbose:
                print(proc.stdout[-800:] if len(proc.stdout) > 800 else proc.stdout)
                if proc.stderr:
                    print(f"[STDERR] {proc.stderr[-400:]}")
        except subprocess.TimeoutExpired:
            step["error"] = "TIMEOUT (>120s)"
            all_ok = False
            if verbose:
                print("❌ TIMEOUT")
        except Exception as e:
            step["error"] = str(e)
            all_ok = False
            if verbose:
                print(f"❌ Exception: {e}")

        step["timestamp"] = datetime.utcnow().isoformat() + "Z"
        results.append(step)

    return all_ok, results


def get_prediction_json() -> Dict:
    """Read latest Stage 3 prediction."""
    path = ML_INFERENCE / "latest_prediction.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def get_copilot_json() -> Dict:
    """Read latest Stage 4 copilot response."""
    path = COPILOT / "llm" / "latest_copilot_response.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def get_pipeline_status() -> Dict:
    """Quick status check without running pipeline."""
    pred = get_prediction_json()
    copilot = get_copilot_json()
    return {
        "prediction_exists": bool(pred),
        "copilot_exists": bool(copilot),
        "overall_status": pred.get("overall_status", "UNKNOWN"),
        "routers_at_risk": pred.get("routers_at_risk", 0),
        "prediction_timestamp": pred.get("timestamp", "Never"),
        "copilot_timestamp": copilot.get("timestamp", "Never"),
    }


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Testing pipeline runner...")
    status = get_pipeline_status()
    print(f"Current status: {status}")
    print("\n--- Running full pipeline (this will take ~30 sec) ---")
    ok, results = run_pipeline(verbose=True)
    print(f"\nPipeline result: {'✅ ALL OK' if ok else '❌ SOME FAILED'}")
    for r in results:
        print(f"  {r['name']}: {'✅' if r['success'] else '❌'}")
