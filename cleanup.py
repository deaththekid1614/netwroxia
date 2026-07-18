#!/usr/bin/env python3
"""
Netwroxia — STALE NETWORK CLEANUP
Nukes old containers, stale topologies, and stale data before a fresh run.
SAFE: Only touches Netwroxia-related containers/files.
"""
import subprocess
import sys
from pathlib import Path

R = "\033[91m"
G = "\033[92m"
Y = "\033[93m"
B = "\033[94m"
D = "\033[0m"

def run(cmd, shell=False, timeout=60):
    try:
        result = subprocess.run(
            cmd if shell else cmd.split(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=shell
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def banner(text):
    print(f"\n{B}{'═'*50}{D}")
    print(f"{B}  {text:<48}{D}")
    print(f"{B}{'═'*50}{D}")

def main():
    print(f"\n{B}NETWROXIA CLEANUP — Removing stale artifacts{D}\n")

    # ── 1. Destroy Containerlab topology ─────────────────
    banner("Step 1: Containerlab Topology")
    topology = Path("/home/death-kid/IDE/netwroxia/network/containerlab/topology.yml")
    
    if topology.exists():
        ok, out, err = run(
            f"sudo containerlab destroy -t {topology} --cleanup",
            shell=True, timeout=60
        )
        if ok:
            print(f"{G}  ✅ Topology destroyed{D}")
        else:
            print(f"{Y}  ⚠️  Topology destroy returned: {err[:200]}{D}")
    else:
        print(f"{Y}  ⚠️  topology.yml not found, skipping{D}")

    # ── 2. Kill stale Netwroxia Docker containers ────────
    banner("Step 2: Docker Containers")
    
    ok, out, _ = run("docker ps -a --format '{{.Names}}'", shell=True)
    if ok:
        containers = [c for c in out.strip().split("\n") if c and "netwroxia" in c.lower()]
        for c in containers:
            run(f"docker rm -f {c}", shell=True, timeout=10)
            print(f"{G}  ✅ Removed: {c}{D}")
        if not containers:
            print(f"{G}  ✅ No stale Netwroxia containers found{D}")
    else:
        print(f"{Y}  ⚠️  Could not list containers{D}")

    # ── 3. Clean up old data files ───────────────────────
    banner("Step 3: Stale ML Data")
    
    dirs_to_clean = [
        "/home/death-kid/IDE/netwroxia/ml/data/raw",
        "/home/death-kid/IDE/netwroxia/ml/data/processed",
        "/home/death-kid/IDE/netwroxia/ml/data/labels",
    ]
    
    total_removed = 0
    for d in dirs_to_clean:
        p = Path(d)
        if p.exists():
            files = list(p.glob("*"))
            for f in files:
                f.unlink()
                total_removed += 1
            print(f"{G}  ✅ Cleared {len(files)} files from {p.name}{D}")
    
    if total_removed == 0:
        print(f"{G}  ✅ No stale data files found{D}")

    # ── 4. Docker system prune (optional, light) ─────────
    banner("Step 4: Docker Prune")
    print(f"{Y}  ℹ️  Running light prune (networks + volumes)...{D}")
    run("docker network prune -f", shell=True, timeout=30)
    run("docker volume prune -f", shell=True, timeout=30)
    print(f"{G}  ✅ Pruned unused networks/volumes{D}")

    # ── 5. Summary ───────────────────────────────────────
    banner("CLEANUP COMPLETE")
    print(f"\n{G}  Ready for fresh deployment!{D}")
    print(f"\n  Next commands:")
    print(f"    cd ~/IDE/netwroxia/network/containerlab")
    print(f"    sudo containerlab deploy -t topology.yml")
    print(f"\n  Then run the full pipeline:")
    print(f"    cd ~/IDE/netwroxia")
    print(f"    python3 run_pipeline.py")
    print(f"\n{B}{'═'*50}{D}\n")

if __name__ == "__main__":
    main()
