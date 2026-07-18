# ═══════════════════════════════════════════════════════════════════════════════
#              NETWROXIA — STAGE 1 HANDOFF DOCUMENT
#     Simulated Banking Network (Containerlab + FRRouting)
#     Ready for Stage 2: Telemetry Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

> **Generated:** 2026-07-13
> **Project:** Netwroxia — Air-Gapped Predictive NOC Copilot for Banking
> **Hackathon:** IBM Z Datathon 2026 | Wildcard Entry
> **Team:** Astro_X
> **User:** death-kid (BSc DSA Final Year)
> **Machine:** MacBook Air 2015, Zorin OS 16.3 x86_64, 8GB RAM
> **Workflow:** VS Code + terminal, chunk-by-chunk paste, NO file downloads

---

## 🎯 WHAT WAS BUILT IN STAGE 1

A fully functional 4-node simulated banking network using Containerlab + FRRouting:

```
                    ┌─────────────────┐
                    │   HO-Chennai    │  ← Head Office (Route Reflector)
                    │   10.255.0.1    │     Core Banking Server
                    │   AS 65001      │
                    └────────┬────────┘
                             │ eth1: 10.0.1.1/30
                             │
                    ┌────────▼────────┐
                    │  ZO-Bengaluru   │  ← Zonal Office (Branch Aggregator)
                    │   10.255.0.2    │
                    │   AS 65001      │
                    └────┬─────┬──────┘
                         │         │
              ┌──────────┘         └──────────┐
              │ eth2: 10.1.2.1/30             │ eth3: 10.1.3.1/30
      ┌───────▼───────┐           ┌────────▼────────┐
      │ BR-Koramangala│           │  BR-Whitefield  │
      │   10.255.0.3  │           │   10.255.0.4    │
      │   AS 65001    │           │   AS 65001      │
      │ ATM + Teller  │           │  ATM + Teller   │
      └───────────────┘           └─────────────────┘
          eth1: 10.1.2.2/30           eth1: 10.1.3.2/30
```

### Protocols Running
| Protocol | Purpose | Status |
|----------|---------|--------|
| OSPF | Internal routing, loopback distribution | ✅ ALL adjacencies FULL |
| iBGP (AS 65001) | MPLS VPN route exchange | ✅ ALL sessions UP |
| BGP Route Reflector | HO-Chennai reflects routes to all peers | ✅ Working |
| MPLS LDP | Configured in daemons (ready for Stage 2) | ✅ Ready |

### IP Addressing
| Link | Network | Node A IP | Node B IP |
|------|---------|-----------|-----------|
| HO ↔ ZO | 10.0.1.0/30 | 10.0.1.1 (HO) | 10.0.1.2 (ZO) |
| ZO ↔ BR-Kora | 10.1.2.0/30 | 10.1.2.1 (ZO) | 10.1.2.2 (Kora) |
| ZO ↔ BR-White | 10.1.3.0/30 | 10.1.3.1 (ZO) | 10.1.3.2 (White) |
| Loopback0 | 10.255.0.x/32 | Per-node | Per-node |

### Loopback IPs
| Node | Loopback0 |
|------|-----------|
| HO-Chennai | 10.255.0.1 |
| ZO-Bengaluru | 10.255.0.2 |
| BR-Koramangala | 10.255.0.3 |
| BR-Whitefield | 10.255.0.4 |

---

## 📁 EXACT FILE STRUCTURE (Stage 1)

```
/home/death-kid/IDE/netwroxia/
├── network/
│   ├── containerlab/
│   │   ├── topology.yml              ← LOCKED — 4-node Containerlab topology
│   │   └── frr-configs/
│   │       ├── daemons                ← LOCKED — FRR daemon flags
│   │       ├── ho-chennai.conf        ← LOCKED — HO: BGP RR + OSPF
│   │       ├── zo-bengaluru.conf      ← LOCKED — ZO: BGP CE + OSPF
│   │       ├── br-koramangala.conf    ← LOCKED — Branch: OSPF + BGP
│   │       └── br-whitefield.conf     ← LOCKED — Branch: OSPF + BGP
│   ├── traffic-gen/
│   │   └── inject_faults.py          ← LOCKED — tc netem fault injection
│   └── verify/
│       └── health_check.py           ← LOCKED — Full network verification
```

**⚠️ CRITICAL: These 8 files are LOCKED. Do NOT modify them in Stage 2.**
Stage 2 adds NEW files in `telemetry/`, `docker-compose.yml`, etc. It does NOT touch `network/`.

---

## ✅ VERIFICATION RESULTS (Last Run: 2026-07-13)

### Container Status
```
clab-netwroxia-ho-chennai      running   172.20.20.12
clab-netwroxia-zo-bengaluru    running   172.20.20.13
clab-netwroxia-br-koramangala  running   172.20.20.11
clab-netwroxia-br-whitefield   running   172.20.20.14
```

### Ping Tests (All Passed)
| Test | Avg Latency | Status |
|------|-------------|--------|
| HO → ZO direct | 0.10ms | ✅ |
| HO → ZO loopback | 0.10ms | ✅ |
| HO → BR-Kora loopback | 0.12ms | ✅ |
| HO → BR-White loopback | 0.11ms | ✅ |
| BR-Kora → HO loopback | 0.12ms | ✅ |
| BR-White → HO loopback | 0.13ms | ✅ |
| ZO → BR-Kora direct | 0.06ms | ✅ |
| ZO → BR-White direct | 0.18ms | ✅ |

### OSPF Neighbors (All FULL)
| Router | Neighbor ID | State | Interface |
|--------|-------------|-------|-----------|
| ho-chennai | 10.255.0.2 | Full | eth1 |
| zo-bengaluru | 10.255.0.1 | Full | eth1 |
| zo-bengaluru | 10.255.0.3 | Full | eth2 |
| zo-bengaluru | 10.255.0.4 | Full | eth3 |
| br-koramangala | 10.255.0.2 | Full | eth1 |
| br-whitefield | 10.255.0.2 | Full | eth1 |

### BGP Summary (All UP)
| Router | Peer | State | Prefixes Received |
|--------|------|-------|-------------------|
| ho-chennai | 10.255.0.2 | UP | 2 |
| ho-chennai | 10.255.0.3 | UP | 1 |
| ho-chennai | 10.255.0.4 | UP | 1 |
| zo-bengaluru | 10.255.0.1 | UP | 2 |
| br-koramangala | 10.255.0.1 | UP | 3 |
| br-whitefield | 10.255.0.1 | UP | 3 |

### Fault Injection (Verified Working)
| Scenario | Command | Result |
|----------|---------|--------|
| Add 100ms latency | `python3 inject_faults.py latency -l ho-zo -v 100` | ✅ Ping shows ~100ms |
| Reset fault | `python3 inject_faults.py reset -l ho-zo` | ✅ Ping back to ~0.1ms |
| Check status | `python3 inject_faults.py status` | ✅ Shows all tc rules |

---

## 🔧 ESSENTIAL COMMANDS FOR NEXT CHAT

### Start/Stop Network
```bash
cd /home/death-kid/IDE/netwroxia/network/containerlab
sudo containerlab deploy -t topology.yml    # Start
sudo containerlab destroy -t topology.yml   # Stop
sudo containerlab inspect -t topology.yml   # Check status
```

### Enter Router CLI
```bash
docker exec -it clab-netwroxia-ho-chennai vtysh
docker exec -it clab-netwroxia-zo-bengaluru vtysh
docker exec -it clab-netwroxia-br-koramangala vtysh
docker exec -it clab-netwroxia-br-whitefield vtysh
```

### Quick Checks
```bash
# BGP
docker exec -it clab-netwroxia-ho-chennai vtysh -c "show ip bgp summary"

# OSPF
docker exec -it clab-netwroxia-ho-chennai vtysh -c "show ip ospf neighbor"

# Running config
docker exec -it clab-netwroxia-ho-chennai vtysh -c "show running-config"

# Full health check
cd /home/death-kid/IDE/netwroxia/network/verify
python3 health_check.py
```

---

## 🚀 STAGE 2: TELEMETRY PIPELINE — WHAT TO BUILD

### Goal
Collect metrics from all 4 routers and store them in InfluxDB. This is the "eyes and ears" of Netwroxia.

### Architecture
```
FRR Routers (4 nodes)
    │
    ▼
Telegraf (Collector)
    ├── SNMP plugin → Interface stats, CPU, memory
    ├── Exec plugin → vtysh commands (BGP state, OSPF neighbors)
    └── Socket listener → Custom metrics
    │
    ▼
InfluxDB 1.8 (Time-Series DB)
    │
    ├──→ Stage 3 ML Pipeline (reads metrics)
    └──→ Stage 6 Streamlit Dashboard (queries metrics)
```

### Why This Stack (Lightweight for 8GB RAM)
| Tool | Why |
|------|-----|
| **InfluxDB 1.8** | Lighter than 2.x, no token auth hassle, proven stable |
| **Telegraf** | One config file, SNMP + exec + socket plugins, push to InfluxDB |
| **NO Grafana** | Stage 6 Streamlit dashboard handles ALL visualization |
| **NO Kafka** | Overkill for 4 routers. Direct Telegraf → InfluxDB is fine. |

### Files to Create (NEW — do not touch Stage 1 files)
```
netwroxia/
├── docker-compose.yml              # InfluxDB + Telegraf services
├── telemetry/
│   ├── telegraf/
│   │   └── telegraf.conf           # SNMP + exec plugin config
│   └── influxdb/
│       └── init-scripts/
│           └── init.iql              # DB creation, retention policy
```

### Metrics to Collect
| Metric | Source | Frequency | Why |
|--------|--------|-----------|-----|
| Interface utilization | SNMP ifHCInOctets/ifHCOutOctets | 10s | Link saturation detection |
| Interface errors/drops | SNMP ifInErrors/ifOutErrors | 10s | Fault detection |
| CPU usage | SNMP hrProcessorLoad | 30s | Router overload |
| Memory usage | SNMP hrStorageUsed | 30s | Resource exhaustion |
| BGP peer state | Exec (vtysh) | 30s | Routing instability |
| OSPF neighbor count | Exec (vtysh) | 30s | Adjacency health |
| Ping latency | Exec (ping) | 10s | End-to-end path health |

### Telegraf SNMP Config Approach
FRRouting has limited SNMP support. Use **exec plugin** with `vtysh` commands instead:
```toml
[[inputs.exec]]
  commands = [
    "docker exec clab-netwroxia-ho-chennai vtysh -c 'show ip bgp summary'",
    "docker exec clab-netwroxia-ho-chennai vtysh -c 'show ip ospf neighbor'",
  ]
  timeout = "10s"
  data_format = "json"  # or parse with regex
```

**Alternative:** Use `inputs.snmp` for basic interface stats (if FRR supports it) + `inputs.exec` for BGP/OSPF state.

### Docker Compose Services
```yaml
services:
  influxdb:
    image: influxdb:1.8
    ports:
      - "8086:8086"
    volumes:
      - ./telemetry/influxdb/init-scripts:/docker-entrypoint-initdb.d
      - influxdb-data:/var/lib/influxdb

  telegraf:
    image: telegraf:latest
    volumes:
      - ./telemetry/telegraf/telegraf.conf:/etc/telegraf/telegraf.conf:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro  # For docker exec
    depends_on:
      - influxdb
```

### InfluxDB Init Script
```sql
CREATE DATABASE netwroxia;
CREATE RETENTION POLICY one_week ON netwroxia DURATION 7d REPLICATION 1 DEFAULT;
```

### Stage 2 Success Criteria
1. [ ] `docker-compose up` starts InfluxDB + Telegraf without errors
2. [ ] Telegraf connects to InfluxDB (check logs: `docker logs netwroxia-telegraf-1`)
3. [ ] Metrics appear in InfluxDB: `SHOW MEASUREMENTS ON netwroxia`
4. [ ] At least 3 metric types flowing: interface, BGP state, ping latency
5. [ ] Data persists for >5 minutes (retention policy working)
6. [ ] `health_check.py` still passes (Stage 1 not broken)

---

## ⚠️ CRITICAL WARNINGS FOR STAGE 2 CHAT

1. **DO NOT modify any file in `network/` directory.** Stage 1 is LOCKED.
2. **Test Stage 1 health before starting Stage 2:**
   ```bash
   cd /home/death-kid/IDE/netwroxia/network/verify
   python3 health_check.py
   ```
   If this fails, fix Stage 1 FIRST before adding Stage 2.
3. **Use InfluxDB 1.8, NOT 2.x.** 2.x requires tokens and buckets — unnecessary complexity.
4. **Telegraf needs Docker socket access** to run `docker exec` for vtysh commands. Mount `/var/run/docker.sock`.
5. **Start with ONE router's metrics.** Get HO-Chennai working first, then add others.
6. **User's machine has 8GB RAM.** InfluxDB 1.8 default memory is ~200MB. Telegraf ~50MB. Total Stage 2 overhead <500MB.
7. **User works chunk-by-chunk in VS Code.** Give one file at a time. Wait for "pasted, next" before next chunk.
8. **No sudo in configs.** Only `sudo docker-compose up` and `sudo containerlab deploy`.
9. **If anything breaks, STOP.** Do not add more files. Fix the broken file, test, then continue.
10. **Bob (IBM) is LAST RESORT.** Use only for complex cross-file debugging. Test everything in terminal first.

---

## 🧪 STAGE 2 TESTING CHECKLIST

After each file paste, run these:

```bash
# After docker-compose.yml
cd /home/death-kid/IDE/netwroxia
sudo docker-compose up -d
sudo docker-compose ps
sudo docker-compose logs influxdb
sudo docker-compose logs telegraf

# After telegraf.conf
sudo docker-compose restart telegraf
sudo docker-compose logs telegraf --tail 50

# After init script
sudo docker-compose restart influxdb
docker exec -it netwroxia-influxdb-1 influx -database netwroxia -execute "SHOW MEASUREMENTS"

# Final verification
cd /home/death-kid/IDE/netwroxia/network/verify
python3 health_check.py  # Stage 1 must still pass
```

---

## 📊 STAGE 2 → STAGE 3 HANDOFF PREVIEW

Stage 3 will need:
- InfluxDB query examples to pull training data
- Metric schema (what fields exist, what they mean)
- Fault injection timestamps (from `inject_faults.py`) as ground truth labels
- At least 24 hours of metrics (or simulated time-compressed data)

**Stage 2 must document:**
- Exact metric names in InfluxDB
- Field names and data types
- Sample queries for Stage 3 ML pipeline

---

## 🎯 PROJECT CONTEXT (For New Chat)

**What is Netwroxia?**
An autonomous, air-gapped offline AI NOC Copilot for banking networks. It predicts failures 5-10 minutes before impact and auto-remediates with zero downtime.

**6 Stages:**
1. ✅ Simulated Banking Network (DONE)
2. ⏳ Telemetry Pipeline (NEXT)
3. Predictive Analytics Engine (ML)
4. Offline LLM Copilot (Mistral 7B)
5. Zero-Downtime Auto-Remediation
6. NOC Dashboard (Streamlit)

**Why Banking?**
- ₹1 min downtime = ₹50 lakh loss (HFT trading)
- RBI mandates 99.9% uptime
- Air-gap constraint — banks CANNOT use cloud AI
- ATM networks must be 24/7

**User Profile:**
- Final year BSc DSA student
- Building for IBM Z Datathon 2026
- Previous project: 7-stage exoplanet pipeline (92.3% accuracy, Team Astro_X)
- Highly technical, hands-on, gets frustrated with vague answers
- Works in VS Code on MacBook Air + Zorin OS

---

## 🔗 QUICK REFERENCE

| Command | Purpose |
|---------|---------|
| `sudo containerlab deploy -t topology.yml` | Start network |
| `sudo containerlab destroy -t topology.yml` | Stop network |
| `docker exec -it clab-netwroxia-XXX vtysh` | Enter router CLI |
| `python3 health_check.py` | Full network verification |
| `python3 inject_faults.py status` | Check fault injection state |
| `sudo docker-compose up -d` | Start Stage 2 services |

---

**END OF STAGE 1 HANDOFF**
**Status: COMPLETE | Next: Stage 2 Telemetry Pipeline**
**Files Locked: 8 | Tests Passed: 100%**
