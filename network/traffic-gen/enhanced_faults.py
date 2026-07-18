#!/usr/bin/env python3
"""
Netwroxia Stage 3 — enhanced_faults.py
Rich fault injection for ML training + demo.
Creates GRADUAL faults so LSTM can learn predictive patterns.
"""

import subprocess
import sys
import argparse
import time

NODES = {
    "ho-chennai": "clab-netwroxia-ho-chennai",
    "zo-bengaluru": "clab-netwroxia-zo-bengaluru",
    "br-koramangala": "clab-netwroxia-br-koramangala",
    "br-whitefield": "clab-netwroxia-br-whitefield",
}

# FIXED: eth0 is the only interface after restart
LINKS = {
    "ho-zo": ("ho-chennai", "eth0"),
    "zo-kora": ("zo-bengaluru", "eth0"),
    "zo-white": ("zo-bengaluru", "eth0"),
}


def run_in_container(container, cmd):
    full_cmd = ["docker", "exec", container, "sh", "-c", cmd]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def gradual_loss(link, start_pct=5, end_pct=100, duration_sec=300, step_sec=30):
    if link not in LINKS:
        print(f"Unknown link: {link}")
        return False
    
    node, iface = LINKS[link]
    container = NODES[node]
    
    steps = duration_sec // step_sec
    loss_values = [int(start_pct + (end_pct - start_pct) * (i / max(steps - 1, 1))) 
                   for i in range(steps)]
    
    print(f"🔄 Gradual loss on {link}: {start_pct}% → {end_pct}% over {duration_sec}s")
    
    for i, loss_pct in enumerate(loss_values):
        cmd = f"tc qdisc del dev {iface} root 2>/dev/null; tc qdisc add dev {iface} root netem loss {loss_pct}%"
        rc, out, err = run_in_container(container, cmd)
        if rc == 0:
            print(f"  Step {i+1}/{steps}: {loss_pct}% loss")
        else:
            print(f"  Step {i+1}/{steps}: FAILED - {err.strip()}")
        time.sleep(step_sec)
    
    print(f"✅ Gradual loss complete on {link}")
    return True


def gradual_latency(link, start_ms=10, end_ms=500, duration_sec=300, step_sec=30):
    if link not in LINKS:
        print(f"Unknown link: {link}")
        return False
    
    node, iface = LINKS[link]
    container = NODES[node]
    
    steps = duration_sec // step_sec
    lat_values = [int(start_ms + (end_ms - start_ms) * (i / max(steps - 1, 1))) 
                  for i in range(steps)]
    
    print(f"🔄 Gradual latency on {link}: {start_ms}ms → {end_ms}ms over {duration_sec}s")
    
    for i, lat_ms in enumerate(lat_values):
        cmd = f"tc qdisc del dev {iface} root 2>/dev/null; tc qdisc add dev {iface} root netem delay {lat_ms}ms"
        rc, out, err = run_in_container(container, cmd)
        if rc == 0:
            print(f"  Step {i+1}/{steps}: {lat_ms}ms delay")
        else:
            print(f"  Step {i+1}/{steps}: FAILED")
        time.sleep(step_sec)
    
    print(f"✅ Gradual latency complete on {link}")
    return True


def mixed_degradation(link, duration_sec=300):
    if link not in LINKS:
        print(f"Unknown link: {link}")
        return False
    
    node, iface = LINKS[link]
    container = NODES[node]
    
    print(f"🚨 MIXED DEGRADATION on {link}: 5min realistic failure")
    
    # Phase 1: Rising latency
    for lat in [10, 50, 100, 150, 200]:
        cmd = f"tc qdisc del dev {iface} root 2>/dev/null; tc qdisc add dev {iface} root netem delay {lat}ms"
        run_in_container(container, cmd)
        print(f"  Latency: {lat}ms")
        time.sleep(15)
    
    # Phase 2: Adding loss
    for loss in [5, 15, 30, 50]:
        cmd = f"tc qdisc change dev {iface} root netem delay 200ms loss {loss}%"
        run_in_container(container, cmd)
        print(f"  Loss: {loss}%")
        time.sleep(15)
    
    # Phase 3: Full outage
    cmd = f"tc qdisc change dev {iface} root netem loss 100%"
    run_in_container(container, cmd)
    print("  FULL OUTAGE: 100% loss")
    time.sleep(60)
    
    # Phase 4: Recovery
    cmd = f"tc qdisc del dev {iface} root 2>/dev/null"
    run_in_container(container, cmd)
    print("  RECOVERED")
    
    print(f"✅ Mixed degradation complete on {link}")
    return True


def reset_link(link):
    if link not in LINKS:
        print(f"Unknown link: {link}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    cmd = f"tc qdisc del dev {iface} root 2>/dev/null; echo cleared"
    run_in_container(container, cmd)
    print(f"✅ Reset {link}")
    return True


def reset_all():
    for name, container in NODES.items():
        cmd = "tc qdisc del dev eth0 root 2>/dev/null; echo done"
        run_in_container(container, cmd)
    print("✅ Reset all links")


def show_status():
    for name, container in NODES.items():
        print(f"\n📡 {name}:")
        rc, out, err = run_in_container(container, "tc qdisc show dev eth0")
        if out.strip():
            print(f"  eth0: {out.strip()}")
        else:
            print(f"  eth0: (no rules)")


def main():
    parser = argparse.ArgumentParser(description="Netwroxia Enhanced Fault Injection")
    parser.add_argument("action", choices=[
        "gradual-loss", "gradual-latency", "mixed", "reset", "reset-all", "status"
    ])
    parser.add_argument("--link", "-l", choices=list(LINKS.keys()))
    parser.add_argument("--duration", "-d", type=int, default=300, help="Duration in seconds")
    parser.add_argument("--start", type=int, default=5, help="Start value")
    parser.add_argument("--end", type=int, default=100, help="End value")

    args = parser.parse_args()

    if args.action == "gradual-loss":
        if not args.link:
            print("Usage: enhanced_faults.py gradual-loss -l ho-zo")
            sys.exit(1)
        gradual_loss(args.link, args.start, args.end, args.duration)

    elif args.action == "gradual-latency":
        if not args.link:
            print("Usage: enhanced_faults.py gradual-latency -l ho-zo")
            sys.exit(1)
        gradual_latency(args.link, args.start, args.end, args.duration)

    elif args.action == "mixed":
        if not args.link:
            print("Usage: enhanced_faults.py mixed -l ho-zo")
            sys.exit(1)
        mixed_degradation(args.link, args.duration)

    elif args.action == "reset":
        if not args.link:
            print("Usage: enhanced_faults.py reset -l ho-zo")
            sys.exit(1)
        reset_link(args.link)

    elif args.action == "reset-all":
        reset_all()

    elif args.action == "status":
        show_status()


if __name__ == "__main__":
    main()