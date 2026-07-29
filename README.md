# NETWROXIA

Autonomous, air-gapped AI NOC Copilot for banking networks — prediction, explanation, and automated remediation.

This repository contains a 4-stage pipeline that simulates a banking WAN, collects telemetry, runs ML inference to predict faults and Time-To-Impact (TTI), and produces an offline LLM-based Copilot analysis. A Streamlit dashboard provides a mission-control UI for live monitoring and drill-down.

---

**Quick summary**

- Stage 1: Simulated banking network (Containerlab + FRR)
- Stage 2: Telemetry collection (Telegraf → InfluxDB 1.8)
- Stage 3: ML analytics (XGBoost classifier + PyTorch LSTM forecaster)
- Stage 4: Offline Copilot (Mistral 7B via llama-cpp-python + ChromaDB RAG)
- Dashboard: Streamlit UI at `dashboard/app.py`

---

## Table of Contents

- Overview
- Quick Start
- Project layout (detailed)
- Dashboard (files + run instructions)
- Pipeline: Run individual stages
- Data & models
- Developer notes & troubleshooting
- Team

---

## Overview

Netwroxia predicts network faults 5–10 minutes ahead, explains root causes in banking terminology, and can trigger pre-planned remediation actions. Designed for air-gapped environments: all models and tooling run locally with no cloud dependencies.

Key outcomes:
- Early detection (minutes of lead time)
- Structured actionable Copilot output (JSON)
- Local, explainable LLM responses with RAG context (runbooks, RBI circulars, incident history)

---

## Quick Start (one command)

Prerequisites

- Docker & Docker Compose
- Containerlab (for network simulation)
- Python 3.10+ and pip
- 8GB+ RAM recommended
- ~6GB free disk space

Optional (recommended for the Copilot and dashboard):

```bash
pip install -r copilot/requirements.txt  # install copilot deps
pip install streamlit pandas requests streamlit-autorefresh
```

Run the full pipeline (from repo root):

```bash
sudo python3 run_pipeline.py
```

After run completes, launch the dashboard:

```bash
streamlit run dashboard/app.py
```

Note: the pipeline prints a ready-to-run dashboard command as part of its summary.

---

## Project layout (files you should know)

Top-level important files/folders:

- `run_pipeline.py` — orchestrates all 4 stages end-to-end
- `docker-compose.yml` — InfluxDB + Telegraf service definitions for local testing
- `network/` — Containerlab topology and fault injection utilities
  - `network/containerlab/topology.yml`
  - `network/traffic-gen/inject_faults.py`
- `telemetry/` — Telegraf configs and InfluxDB init scripts
- `ml/` — ML training and inference
  - `ml/data/fetch_metrics.py`
  - `ml/data/feature_engineer.py`
  - `ml/models/train_ensemble.py` (XGBoost)
  - `ml/models/train_lstm.py` (LSTM)
  - `ml/inference/predict.py` — writes `ml/inference/latest_prediction.json`
- `copilot/` — offline LLM + RAG code
  - `copilot/run_copilot.py` — main prompt builder + RAG + inference
  - `copilot/llm/` — llama-cpp helper, model download script, model files
  - `copilot/llm/latest_copilot_response.json` — last Copilot output
- `dashboard/` — Streamlit UI (full app + components)
  - `dashboard/app.py` — main Streamlit app
  - `dashboard/components/` — alert_card.py, metric_chart.py, topology_graph.py, live_feed.py, status_badge.py
  - `dashboard/utils/` — `influx_client.py`, `pipeline_runner.py`

This README focuses on making the above runnable and discoverable.

---

## Dashboard — what it is and how to run it

What: a Streamlit-based mission control UI that shows:
- Overview: current router health, overall status
- Metrics: time-series charts for ping, BGP/OSPF, container metrics
- Topology: 4-node simulated bank topology visualization
- Predictions: latest ML predictions and TTI
- Copilot: structured LLM diagnosis + recommended actions

Where: `dashboard/app.py` is the Streamlit entrypoint.

Key utilities:
- `dashboard/utils/influx_client.py` — queries InfluxDB 1.8 (defaults to `http://localhost:8086`, DB name `netwroxia`)
- `dashboard/utils/pipeline_runner.py` — reads `ml/inference/latest_prediction.json` and `copilot/llm/latest_copilot_response.json` so the UI can display latest outputs
- UI components: `dashboard/components/*` are reusable renderers for cards/charts/topology.

Run steps (recommended):

1. Start telemetry services (InfluxDB + Telegraf):

```bash
# From repo root
sudo docker-compose up -d
```

2. Ensure `netwroxia` database exists in InfluxDB (init scripts under `telemetry/influxdb/init-scripts/`)

3. Launch Streamlit UI:

```bash
streamlit run dashboard/app.py
```

Helpful installs (if not present):

```bash
pip install streamlit pandas requests streamlit-autorefresh
```

Notes:
- Dashboard expects InfluxDB to be reachable at `http://localhost:8086` and database `netwroxia`.
- The dashboard pulls prediction/copilot JSON files from disk — running `run_pipeline.py` or `ml/inference/predict.py` + `copilot/run_copilot.py` beforehand populates them.

---

## Pipeline: run stages individually

Stage 1 — Network

```bash
cd network/containerlab
sudo containerlab deploy -t topology.yml
```

Stage 2 — Telemetry

```bash
cd telemetry
# start the docker-compose defined InfluxDB + Telegraf stack
sudo docker-compose up -d
```

Stage 3 — ML

```bash
# fetch metrics, feature-engineer, train models (optional), run inference
python3 ml/data/fetch_metrics.py
python3 ml/data/feature_engineer.py
python3 ml/models/train_ensemble.py   # optional: training
python3 ml/models/train_lstm.py      # optional: training
python3 ml/inference/predict.py      # produces ml/inference/latest_prediction.json
```

Stage 4 — Copilot (offline LLM)

```bash
# prepare embeddings and run copilot
python3 copilot/rag/ingest_documents.py  # build ChromaDB from runbooks and documents
python3 copilot/run_copilot.py           # produces copilot/llm/latest_copilot_response.json
```

One-command pipeline:

```bash
sudo python3 run_pipeline.py
```

---

## Data & models

- ML artifacts: `ml/models/` and `ml/inference/latest_prediction.json`.
- Copilot model (quantized gguf) stored in repo (if present): `copilot/llm/mistral-7b-instruct-v0.2.Q4_K_M.gguf`.
- RAG corpus: Markdown runbooks and RBI circulars in `copilot/knowledge_base/` and ingestion code in `copilot/rag/`.

If you need to re-download or update the local GGUF model, see `copilot/llm/download_model.sh`.

---

## Developer notes & troubleshooting

- Database unreachable: dashboard will print InfluxDB query errors. Verify `dashboard/utils/influx_client.py` host/DB or start docker-compose.
- No predictions: ensure `ml/inference/predict.py` runs and outputs `ml/inference/latest_prediction.json`.
- Copilot slow: CPU-only LLM inference with `llama-cpp-python` can be slow on low-end CPUs — use `--fast` mode in `copilot/run_copilot.py` for short demos.

Useful commands (quick checks):

```bash
# view latest prediction
cat ml/inference/latest_prediction.json | python3 -m json.tool
# view latest copilot analysis
cat copilot/llm/latest_copilot_response.json | python3 -m json.tool
```

---

## Contributing / Next steps I can take for you

- Create `dashboard/requirements.txt` with pinned versions (I can add this).
- Add a small `Makefile` for local dev tasks (start telemetry, run pipeline, launch dashboard).
- Commit these README changes and open a Git commit for you.

Tell me which you want next and I will do it.

---

## Team

Team Astro_X — IBM Z Datathon 2026

---
