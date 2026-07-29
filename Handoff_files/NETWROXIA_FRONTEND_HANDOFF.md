# ═══════════════════════════════════════════════════════════════════════════
#                    NETWROXIA — FRONTEND (DASHBOARD) HANDOFF
#           Stage 6: NOC Dashboard — Streamlit UI, "Mission Control"
#                   IBM Z Datathon 2026 | Wildcard Entry
# ═══════════════════════════════════════════════════════════════════════════



## 📌 IDENTITY

| Field | Value |
|---|---|
| **Project** | Netwroxia — Air-Gapped Predictive NOC Copilot for Banking |
| **This deliverable** | Streamlit dashboard ("Stage 6 — The Face") |
| **Framework** | Streamlit (Python) |
| **Python** | 3.12.3 (dev/build env) — components were previously compiled under 3.8 too (`__pycache__/*.cpython-38.pyc` present in zip; safe to delete, regenerated automatically) |
| **Expected project root (hardcoded)** | `/home/death-kid/IDE/netwroxia/` |
| **Entry point** | `dashboard/app.py` |
| **Run command** | `streamlit run dashboard/app.py` (from inside `/home/death-kid/IDE/netwroxia/`) |

---

## 📁 WHAT'S IN THE ZIP

```
dashboard/
├── app.py                          # Main Streamlit app — 927 lines, single page, 5 tabs
├── assets/
│   └── logo.jpeg                   # 1254×1254 JPEG (app.py looks for netwroxia_logo.png /
│                                    #   logo.png instead — see "Known Gaps" below)
├── components/
│   ├── status_badge.py             # Router health badge (🟢🟡🔴) + render_router_card()
│   ├── alert_card.py               # Renders one prediction card from latest_prediction.json
│   ├── metric_chart.py             # 631 lines — all Plotly time-series charts (Metrics tab)
│   ├── live_feed.py                # Live event feed detection + mini sparklines
│   └── topology_graph.py           # NetworkX + Plotly topology map (Network tab)
└── utils/
    ├── influx_client.py            # Read-only InfluxDB 1.8 client
    └── pipeline_runner.py          # Subprocess runner that triggers ML + Copilot stages
```

**Not included in this zip:** `dashboard/pages/` exists but is **empty** — the
originally-planned multi-page structure (`topology.py`, `alerts.py`,
`copilot_chat.py`, `metrics.py`, `playbooks.py`, `compliance.py`) was never
built as separate pages. Instead, everything was consolidated into a
**single-page, tab-based** `app.py`. This is a deliberate simplification, not
a missing file.

---

## 🖥️ WHAT THE DASHBOARD ACTUALLY DOES

### Layout
One page, wide layout, dark "mission-control" theme (Inter + JetBrains Mono
fonts, cyan/purple gradient accents, `#0a0e1a` background). Sidebar is
collapsed by default — everything lives in the main pane.

**Top → bottom:**
1. **Header bar** — logo tile, "NETWROXIA" title/tagline, live HH:MM:SS
   clock (ticked client-side via a 0×0-height iframe + `setInterval`, not a
   server rerun), "AIR-GAPPED · OFFLINE" pill, "LIVE" pill, branding pills.
2. **Status bar** — 5 `st.metric` tiles: System Status, Routers at Risk,
   Last Update, Prediction (Available/None), Copilot (Available/None).
3. **🚀 RUN PIPELINE button** — triggers the full ML + Copilot subprocess
   chain (see `pipeline_runner.py` below), shows a spinner (~60s), then
   `st.rerun()`s the page and fires `st.balloons()` on success.
4. **5 tabs**: `🏠 Overview` · `🌐 Network` · `🔮 Predictions` · `🤖 Copilot`
   · `📊 Metrics`

### Auto-refresh
Uses `streamlit_autorefresh` (`st_autorefresh(interval=1000, ...)`) to rerun
the whole script every **1 second**, so router cards, jittered latency
values, and the event feed all feel "live." If that package isn't
installed, it silently falls back to a `<meta http-equiv="refresh" content="1">`
tag (full page reload, loses scroll position) — see Known Gaps.

### Tabs, in detail

**🏠 Overview**
- "Router Health" section: one card per router (`nx-router` custom HTML/CSS
  block, not a component call) showing Latency, Packet Loss, OSPF
  neighbours, BGP state, and a Fault Probability bar.
- "Live Event Feed": either real detected events (via `live_feed.py`) or a
  synthesized chronological feed built from the current router states
  (`_synthesize_events()` in `app.py`) — guarantees the feed is never empty.
- "Latest Copilot Insight": a condensed card (issue, root cause, quick fix,
  deep fix) pulled from real copilot output if present, else a synthesized
  fallback (`_synthesize_copilot_insight()`).

**🌐 Network** → `topology_graph.render_topology_tab()`
- NetworkX + Plotly graph of the 4-node topology (fixed layout, not
  force-directed): `HO-Chennai → ZO-Bengaluru → {BR-Koramangala, BR-Whitefield}`.
- Node color driven by `latest_prediction.json`, with a hard-down override
  (forces red if BGP is down **and** OSPF neighbours are 0, or packet loss
  is 100%, regardless of what the ML model's `combined_alert` label says).
- Hover tooltips show full per-router metrics.
- Static legend: 🟢 Healthy / 🟡 Warning / 🔴 Critical / ⚫ No Data.

**🔮 Predictions** → `alert_card.render_all_alerts()`
- One expandable card per router straight from `latest_prediction.json`:
  XGBoost fault probability bar, LSTM future-fault bar + time-to-impact,
  raw metrics, top contributing feature.
- Shows `st.info("No predictions available. Run the pipeline first.")` if
  the file doesn't exist yet.

**🤖 Copilot**
- Full structured incident cards (one `st.expander` per copilot response):
  confidence / urgency / affected users / time-to-impact tiles, affected
  sites & services, root cause, recommended actions list, quick fix, deep
  fix, and an optional RBI compliance note.
- Falls back to the same synthesized insight as the Overview tab if no real
  copilot output exists yet, so the tab is never empty after first pipeline
  run.

**📊 Metrics** → `metric_chart.render_metrics_tab()`
- Plotly time-series: ping latency, packet loss, OSPF neighbour count, BGP
  state, container CPU %, container memory % — all per-router, colour-coded
  consistently (`_style_for(router)`).
- Has its own optional auto-refresh loop and a demo-data generator
  (`_generate_demo_timeline()`) used when InfluxDB has no data yet, so
  charts render something even before telemetry exists.
- Publishes a `shared_router_snapshot` into `st.session_state` so **every
  other tab reads the exact same latency/packet-loss/OSPF/status values**
  the Metrics tab computed — this is the single source of truth used by
  `derive_router_state()` in `app.py`.

---

## 🔌 HOW IT TALKS TO THE BACKEND

The frontend is **read-mostly** — it reads telemetry and ML/Copilot output
files, and only writes by shelling out to the pipeline scripts.

### 1. Live telemetry → `utils/influx_client.py`
- Read-only queries against **InfluxDB 1.8** at `http://localhost:8086`,
  database `netwroxia` (hardcoded — no env var yet).
- Measurements queried: `ping`, `ospf_neighbors`, `bgp_peer`,
  `docker_container_cpu`, `docker_container_mem`.
- `get_latest_by_router()` returns the newest row per router across all
  five measurements — this is the snapshot every tab starts from.
- Router identity is resolved three different ways depending on the
  measurement's tag: `_ip_to_router()` (IP → router name, for `ping`),
  `_container_to_router()` (Containerlab container name → router name, for
  CPU/mem), `_normalize_router()` (string normalization, for OSPF/BGP).

### 2. ML predictions → `ml/inference/latest_prediction.json`
Read by `alert_card.py`, `topology_graph.py`, and `app.py`. Expected shape:
```json
{
  "timestamp": "...",
  "overall_status": "CRITICAL | WARNING | HEALTHY",
  "routers_at_risk": 1,
  "predictions": [
    {
      "router": "BR-Whitefield",
      "combined_alert": "NORMAL | SUSPECTED_FAULT | CRITICAL | HIGH_CONFIDENCE_FAULT",
      "top_feature": "...",
      "xgboost": { "predicted_fault": true, "fault_probability": 0.97, "confidence": "HIGH", "status": "..." },
      "lstm_forecast": { "predicted_future_fault": true, "future_fault_probability": 0.9, "time_to_impact": "4.2 min", "status": "..." },
      "raw_metrics": { "latency_ms": 45.0, "packet_loss_pct": 100.0, "ospf_neighbors": 0, "bgp_established": false }
    }
  ]
}
```

### 3. Copilot output → `copilot/llm/latest_copilot_response.json`
Read by `app.py`'s Copilot tab. Accepts either a raw list of response
objects, or a dict with `responses` / `results` / `data` keys, or a single
flat object (auto-normalized in `app.py`).

### 4. Pipeline execution → `utils/pipeline_runner.py`
The "🚀 RUN PIPELINE" button runs these four scripts **in order** via
`subprocess.run(..., cwd=PROJECT_ROOT, timeout=120)` per step:

| Step | Script |
|---|---|
| 📡 Fetch Metrics | `ml/data/fetch_metrics.py` |
| 🔧 Engineer Features | `ml/data/feature_engineer.py` |
| 🔮 Run Prediction | `ml/inference/predict.py` |
| 🤖 Run Copilot | `copilot/run_copilot.py --fast` |

If any step's return code is non-zero, the whole run is marked failed and
`app.py` prints the failing step + first 200 chars of stderr. **These
backend scripts are not part of this zip** — the dashboard assumes they
exist at those paths and are executable.

### Hardcoded paths (same value in 3 files — see Known Gaps)
```
PROJECT_ROOT = Path("/home/death-kid/IDE/netwroxia")
```
Appears in `pipeline_runner.py`, `alert_card.py`, `topology_graph.py`.

---

## 🧠 KEY DESIGN DECISION: `derive_router_state()` (app.py)

This is the most important function to understand before touching the
frontend. Because telemetry, ML predictions, and the Metrics tab's own
shared snapshot can all disagree (or be missing/synthetic), `app.py`
computes **one unified per-router state** that every tab reads from,
instead of each tab computing its own:

- **Latency** — prefers live telemetry, falls back through the Metrics
  shared snapshot, then the prediction JSON, then a static profile. Three
  specific routers (`HO-Chennai`, `ZO-Bengaluru`, `BR-Koramangala`) are
  intentionally **jittered ±12% around a fixed baseline** every refresh
  tick rather than showing a raw/locked number, so the UI visibly "breathes."
- **Packet loss** — rejects clearly-implausible readings (e.g. 100% loss
  reported for a router whose baseline profile says it should be healthy)
  and falls back to the profile instead.
- **OSPF neighbours** — same idea: `0` neighbours is treated as
  implausible for a router whose profile expects OSPF adjacencies, and
  falls back to the profile.
- **Fault probability** — cross-checked against packet loss so a router at
  100% loss can never show a low "risk" number, and vice versa.
- **Status (HEALTHY/WARNING/CRITICAL)** — derived from all of the above
  together, not just the ML model's own label.

The result is written back into `st.session_state["shared_router_snapshot"]`
so Overview / Network / Predictions / Copilot all agree with each other and
with the Metrics tab.

### `ROUTER_PROFILE` — the demo's "ground truth" fallback
```python
ROUTERS = ["HO-Chennai", "ZO-Bengaluru", "BR-Koramangala", "BR-Whitefield"]

ROUTER_PROFILE = {
    "HO-Chennai":     {"packet_loss_pct": 0.3,  "ospf_neighbors": 3, "bgp_established": True,  "fault_prob": 0.04, "latency_ms": 3.0},
    "ZO-Bengaluru":   {"packet_loss_pct": 1.8,  "ospf_neighbors": 1, "bgp_established": True,  "fault_prob": 0.15, "latency_ms": 8.0},
    "BR-Koramangala": {"packet_loss_pct": 8.5,  "ospf_neighbors": 1, "bgp_established": True,  "fault_prob": 0.48, "latency_ms": 14.0},
    "BR-Whitefield":  {"packet_loss_pct": 100.0,"ospf_neighbors": 0, "bgp_established": False, "fault_prob": 0.97, "latency_ms": 45.0},
}
```

---


## ✅ HOW TO RUN IT LOCALLY

```bash
# from /home/death-kid/IDE/netwroxia/ (or wherever PROJECT_ROOT is)
pip install streamlit streamlit-autorefresh pandas requests plotly networkx numpy

streamlit run dashboard/app.py
```

Dashboard works standalone (with synthesized fallbacks) even if:
- InfluxDB isn't running yet, or
- `ml/inference/latest_prediction.json` / `copilot/llm/latest_copilot_response.json`
  don't exist yet.

To see **real** data instead of fallbacks, the backend stages (Containerlab
network, Telegraf → InfluxDB pipeline, ML models, Copilot LLM) need to be
running per the original `NETWROXIA_HANDOFF.md` plan, and
`ml/data/fetch_metrics.py`, `ml/data/feature_engineer.py`,
`ml/inference/predict.py`, `copilot/run_copilot.py` need to exist at the
paths `pipeline_runner.py` expects.


**END OF FRONTEND HANDOFF**
** Generated from actual code inspection | 2026-07-29**
