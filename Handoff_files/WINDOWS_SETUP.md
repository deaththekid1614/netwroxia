# NETWROXIA — Windows Setup Guide
## For Team Astro_X | IBM Z Datathon 2026

> **Last Updated:** 2026-07-18  
> **Your Machine:** Windows 10/11 (x64)  
> **Required:** WSL2 + Docker Desktop OR a Linux VM  
> **This project CANNOT run natively on Windows.** Read why below.

---

## ⚠️ THE BRUTAL TRUTH

Netwroxia is built on Linux-only infrastructure. **Do not try to run this on Windows natively.** You will fail at Stage 1 and waste hours.

| Component | Linux (Zorin) | Windows Native | Status |
|---|---|---|---|
| Containerlab | ✅ Works | ❌ **NO** | Requires Linux kernel namespaces |
| FRRouting containers | ✅ Works | ❌ **NO** | Linux-only Docker images |
| `docker exec vtysh` | ✅ Works | ❌ **NO** | Router CLI is Linux-only |
| InfluxDB 1.8 + Telegraf | ✅ Works | ⚠️ Partial | Can run, but networking glue breaks |
| ML Pipeline (Python) | ✅ Works | ⚠️ Partial | Code runs, but no data source without network |
| Mistral 7B (llama.cpp) | ✅ Works | ⚠️ Partial | Needs Windows rebuild; paths are Linux-style |
| Hardcoded paths | `/home/death-kid/...` | ❌ **BREAKS** | Windows uses `C:\Users\...` |

**Verdict:** You need a Linux environment. Two options below.

---

## OPTION A: WSL2 + Docker Desktop (RECOMMENDED — 30 min)

This runs a real Linux kernel inside Windows. Everything works exactly like on the dev machine.

### Step 1: Enable WSL2

Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

This installs Ubuntu by default. **Restart your PC** when prompted.

After restart, Ubuntu will auto-launch and ask you to create a username and password. Do that.

**Verify WSL2:**
```bash
wsl -l -v
```
You should see `Ubuntu` with `VERSION 2`.

> **If you already have WSL1:** Upgrade it:
> ```powershell
> wsl --set-version Ubuntu 2
> ```

---

### Step 2: Install Docker Desktop

1. Download from: https://docs.docker.com/desktop/setup/install/windows-install/
2. Run the installer.
3. During setup, **check "Use WSL2 instead of Hyper-V"**.
4. After install, open Docker Desktop → Settings → Resources → WSL Integration.
5. **Enable integration for Ubuntu**.
6. Click "Apply & Restart".

**Verify Docker in WSL2:**
```bash
wsl -d Ubuntu
docker --version
```
You should see something like `Docker version 27.x.x`.

---

### Step 3: Install Containerlab in WSL2

Inside your Ubuntu WSL2 terminal:

```bash
# Install Containerlab
bash -c "$(curl -sL https://get.containerlab.dev)"

# Verify
containerlab version
```

---

### Step 4: Fix Path Hardcoding

The original project uses absolute Linux paths. You need to change ONE line in the pipeline runner.

Open `run_pipeline.py` and change this line:
```python
PROJECT_ROOT = Path("/home/death-kid/IDE/netwroxia")
```

To this (adjust to your WSL2 username):
```python
PROJECT_ROOT = Path("/home/YOUR_WSL_USERNAME/netwroxia")
```

Or better — make it auto-detect:
```python
PROJECT_ROOT = Path(__file__).resolve().parent
```

> **Note:** Do this for any script that hardcodes `/home/death-kid/...`.

---

### Step 5: Install Python Dependencies in WSL2

```bash
# Inside WSL2 Ubuntu
cd ~/netwroxia

# System deps
sudo apt update
sudo apt install -y python3-pip python3-venv curl wget

# Python packages for ML
pip3 install pandas numpy scikit-learn xgboost torch --break-system-packages

# Python packages for Copilot
pip3 install chromadb sentence-transformers llama-cpp-python --break-system-packages
```

> `--break-system-packages` is needed on Ubuntu 24.04+. It's safe in WSL2.

---

### Step 6: Download Mistral 7B (if not included in zip)

The `.gguf` model file is ~4.4GB and was excluded from the zip.

```bash
cd ~/netwroxia/copilot/llm
wget --continue https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
```

This takes 10-30 minutes depending on your internet.

---

### Step 7: Run the Pipeline

```bash
cd ~/netwroxia
sudo python3 run_pipeline.py
```

You will be prompted for your WSL2 password for `sudo` (needed for Docker and Containerlab).

---

## OPTION B: VirtualBox VM (If WSL2 Fails)

If your Windows version doesn't support WSL2 or Docker Desktop refuses to work:

1. Download **VirtualBox**: https://www.virtualbox.org/wiki/Downloads
2. Download **Ubuntu 22.04 ISO**: https://ubuntu.com/download/desktop
3. Create a new VM:
   - **RAM:** 4096 MB minimum (6144 MB recommended)
   - **Disk:** 40 GB dynamically allocated
   - **Network:** NAT (with port forwarding if needed)
4. Install Ubuntu from the ISO.
5. Inside the VM, open Terminal and run:
   ```bash
   sudo apt update
   sudo apt install -y docker.io docker-compose python3-pip curl wget
   sudo usermod -aG docker $USER
   # LOG OUT and LOG BACK IN for group change to take effect
   ```
6. Install Containerlab:
   ```bash
   bash -c "$(curl -sL https://get.containerlab.dev)"
   ```
7. Copy the `netwroxia` folder into the VM (shared folders or USB).
8. Fix paths in `run_pipeline.py` as shown in Step 4 above.
9. Run: `sudo python3 run_pipeline.py`

**Downside:** Slower than WSL2. **Upside:** Completely isolated, bulletproof.

---

## OPTION C: Read-Only / Code Review Only

If your friend just wants to **read the code**, **understand the architecture**, or **present slides** — they can do this on Windows natively:

- Open any `.py` file in VS Code on Windows.
- Read the README and handoff documents.
- View the JSON outputs (`latest_prediction.json`, `latest_copilot_response.json`).

**They cannot run the pipeline without Linux.**

---

## 🔧 COMMON ISSUES & FIXES

### Issue 1: "docker: permission denied"
```bash
sudo usermod -aG docker $USER
# LOG OUT and LOG BACK IN
```

### Issue 2: "containerlab: command not found"
```bash
# Add to PATH if missing
export PATH=$PATH:/usr/local/bin
# Or reinstall
bash -c "$(curl -sL https://get.containerlab.dev)"
```

### Issue 3: "ModuleNotFoundError: No module named 'xgboost'"
```bash
pip3 install xgboost torch pandas numpy scikit-learn --break-system-packages
```

### Issue 4: "llama_cpp not found" (Copilot fails)
```bash
pip3 install llama-cpp-python --break-system-packages
# If compilation fails, install build tools:
sudo apt install -y build-essential cmake
```

### Issue 5: Mistral 7B download is corrupted
```bash
cd ~/netwroxia/copilot/llm
rm -f mistral-7b-instruct-v0.2.Q4_K_M.gguf
wget --continue https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf
ls -lh *.gguf  # Should show ~4.4GB
```

### Issue 6: "sudo docker-compose ps" asks for password every time
```bash
# Edit sudoers to allow passwordless docker-compose for your user
sudo visudo
# Add this line at the bottom:
# YOUR_USERNAME ALL=(ALL) NOPASSWD: /usr/bin/docker-compose, /usr/bin/docker
```

### Issue 7: Pipeline runs but no output (silent failure)
This is a terminal encoding issue. The pipeline uses ANSI colors and Unicode block characters (`▓`, `═`).

**Fix:** Use Windows Terminal (not CMD) or VS Code integrated terminal. If still broken:
```bash
# Run with unbuffered output
python3 -u run_pipeline.py
```

### Issue 8: InfluxDB connection refused
```bash
# Check if InfluxDB container is running
sudo docker-compose ps

# If not, start it
sudo docker-compose up -d

# Wait 10 seconds, then test
curl -s http://localhost:8086/ping
```

---

## 📦 ZIP CONTENTS CHECKLIST

When you receive the zip, verify these folders exist:

```
netwroxia/
├── run_pipeline.py              <-- MAIN ENTRY POINT
├── docker-compose.yml
├── network/
│   ├── containerlab/
│   │   ├── topology.yml
│   │   └── frr-configs/         <-- Router configs (locked)
│   ├── traffic-gen/
│   │   └── inject_faults.py
│   └── verify/
│       └── health_check.py
├── telemetry/
│   ├── telegraf/
│   │   └── telegraf.conf
│   └── influxdb/
│       └── init-scripts/
│           └── init.iql
├── ml/
│   ├── data/
│   │   ├── fetch_metrics.py
│   │   └── feature_engineer.py
│   ├── models/
│   │   ├── train_anomaly.py
│   │   ├── train_ensemble.py
│   │   └── train_lstm.py
│   └── inference/
│       └── predict.py
├── copilot/
│   ├── llm/
│   │   ├── download_model.sh    <-- Run this to get Mistral 7B
│   │   └── inference.py
│   ├── rag/
│   │   └── ingest_documents.py
│   └── knowledge_base/
│       ├── runbooks/
│       ├── past_incidents/
│       └── rbi_circulars/
└── README.md
```

**Excluded from zip (large files):**
- `ml/models/*.pkl` — Retrain with `python3 ml/models/train_ensemble.py`
- `ml/models/*.pt` — Retrain with `python3 ml/models/train_lstm.py`
- `copilot/llm/*.gguf` — Download with `bash copilot/llm/download_model.sh`
- `__pycache__/` — Auto-generated junk

---

## 🚀 QUICK START (After Setup)

```bash
# 1. Enter project
cd ~/netwroxia

# 2. Start network (if not running)
cd network/containerlab
sudo containerlab deploy -t topology.yml
cd ~/netwroxia

# 3. Start telemetry (if not running)
sudo docker-compose up -d

# 4. Run full pipeline
sudo python3 run_pipeline.py

# 5. View outputs
cat ml/inference/latest_prediction.json | python3 -m json.tool
cat copilot/llm/latest_copilot_response.json | python3 -m json.tool

# 6. Inject a fault (test the system)
python3 network/traffic-gen/inject_faults.py latency -l ho-zo -v 100

# 7. Run pipeline again to see fault detection
sudo python3 run_pipeline.py

# 8. Clean up fault
python3 network/traffic-gen/inject_faults.py reset -l ho-zo
```

---

## ❓ FAQ

**Q: Can I run this on Windows without WSL2?**  
A: No. Containerlab requires Linux kernel features that do not exist on Windows.

**Q: Can I use Docker Desktop without WSL2?**  
A: You can, but Containerlab still needs a Linux environment to spawn router containers with the right networking. WSL2 is the bridge.

**Q: How much disk space do I need?**  
A: ~10GB for WSL2 + Ubuntu, ~2GB for Docker images, ~4.5GB for Mistral 7B. Total: **~20GB free space recommended.**

**Q: How much RAM?**  
A: 8GB minimum. 16GB recommended. The Mistral 7B model alone uses ~5GB RAM at peak.

**Q: Can I use Git Bash or Cygwin instead of WSL2?**  
A: No. Git Bash and Cygwin are POSIX compatibility layers, not Linux kernels. Containerlab will not work.

**Q: What if my CPU doesn't support virtualization?**  
A: WSL2 requires CPU virtualization (Intel VT-x / AMD-V). Check in BIOS. If unavailable, use Option B (VirtualBox with software virtualization — slower but works).

**Q: Can I just use the Windows Subsystem for Linux version 1 (WSL1)?**  
A: No. WSL1 does not support the kernel namespaces required by Containerlab. WSL2 only.

---

## 📞 STUCK?

1. Re-read the error message carefully.
2. Check the "Common Issues" section above.
3. Verify your WSL2 version: `wsl -l -v` (must say VERSION 2).
4. Verify Docker is using WSL2 backend: Docker Desktop → Settings → General → "Use the WSL2 based engine".
5. Ask the dev (death-kid) — he built this on Zorin OS and knows every quirk.

---

**Team Astro_X | IBM Z Datathon 2026 | Netwroxia**  
*Predict. Prevent. Protect.*
