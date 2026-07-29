#!/usr/bin/env python3
"""
Netwroxia — Enhanced Fault Injection
Supports: gradual, mixed, instant, and HOLD mode (fault stays until reset)
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

LINKS = {
    "ho-zo": ("ho-chennai", "eth0"),
    "zo-kora": ("zo-bengaluru", "eth0"),
    "zo-white": ("zo-bengaluru", "eth0"),
}


def run_in_container(container, cmd):
    full_cmd = ["docker", "exec", container, "sh", "-c", cmd]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def apply_loss(link, percent):
    """Apply packet loss and KEEP it until manually reset."""
    if link not in LINKS:
        print(f"❌ Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    
    # Clear any existing rules first
    run_in_container(container, f"tc qdisc del dev {iface} root 2>/dev/null")
    
    # Apply loss
    cmd = f"tc qdisc add dev {iface} root netem loss {percent}%"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Applied {percent}% packet loss on {link} ({node}:{iface})")
        print(f"   Fault is ACTIVE. Run 'reset' to clear.")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def apply_latency(link, ms):
    """Apply latency and KEEP it until manually reset."""
    if link not in LINKS:
        print(f"❌ Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    
    run_in_container(container, f"tc qdisc del dev {iface} root 2>/dev/null")
    
    cmd = f"tc qdisc add dev {iface} root netem delay {ms}ms"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Applied {ms}ms latency on {link} ({node}:{iface})")
        print(f"   Fault is ACTIVE. Run 'reset' to clear.")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def apply_mixed(link, latency_ms=200, loss_pct=50):
    """Apply both latency + loss and KEEP it."""
    if link not in LINKS:
        print(f"❌ Unknown link: {link}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    
    run_in_container(container, f"tc qdisc del dev {iface} root 2>/dev/null")
    
    cmd = f"tc qdisc add dev {iface} root netem delay {latency_ms}ms loss {loss_pct}%"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Applied {latency_ms}ms latency + {loss_pct}% loss on {link}")
        print(f"   Fault is ACTIVE. Run 'reset' to clear.")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def gradual_fault(link, fault_type, start, end, duration_sec, step_sec=10):
    """Gradually increase fault over time, then HOLD at max."""
    if link not in LINKS:
        print(f"❌ Unknown link: {link}")
        return False
    
    node, iface = LINKS[link]
    container = NODES[node]
    
    steps = max(duration_sec // step_sec, 1)
    values = [int(start + (end - start) * (i / max(steps - 1, 1))) for i in range(steps)]
    
    print(f"🔄 Gradual {fault_type} on {link}: {start} → {end} over {duration_sec}s")
    print(f"   Steps: {steps} | Interval: {step_sec}s | HOLD at end")
    
    for i, val in enumerate(values):
        run_in_container(container, f"tc qdisc del dev {iface} root 2>/dev/null")
        
        if fault_type == "loss":
            cmd = f"tc qdisc add dev {iface} root netem loss {val}%"
            label = f"{val}% loss"
        else:
            cmd = f"tc qdisc add dev {iface} root netem delay {val}ms"
            label = f"{val}ms delay"
        
        rc, out, err = run_in_container(container, cmd)
        if rc == 0:
            print(f"  Step {i+1}/{steps}: {label}")
        else:
            print(f"  Step {i+1}/{steps}: FAILED - {err.strip()}")
        
        if i < len(values) - 1:
            time.sleep(step_sec)
    
    print(f"✅ Gradual {fault_type} complete. Fault HELD at {end}.")
    print(f"   Run 'reset -l {link}' to clear.")
    return True


def reset_link(link):
    if link not in LINKS:
        print(f"❌ Unknown link: {link}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    run_in_container(container, f"tc qdisc del dev {iface} root 2>/dev/null")
    print(f"✅ Reset {link}")
    return True


def reset_all():
    for name, container in NODES.items():
        run_in_container(container, "tc qdisc del dev eth0 root 2>/dev/null")
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
        "loss", "latency", "mixed", "gradual-loss", "gradual-latency",
        "reset", "reset-all", "status"
    ])
    parser.add_argument("--link", "-l", choices=list(LINKS.keys()))
    parser.add_argument("--value", "-v", type=int, default=100, help="Value: ms or %")
    parser.add_argument("--duration", "-d", type=int, default=60, help="Duration in seconds (for gradual)")
    parser.add_argument("--start", type=int, default=5, help="Start value (for gradual)")
    parser.add_argument("--end", type=int, default=100, help="End value (for gradual)")

    args = parser.parse_args()

    if args.action == "loss":
        if not args.link:
            print("Usage: enhanced_faults.py loss -l zo-kora -v 50")
            sys.exit(1)
        apply_loss(args.link, args.value)

    elif args.action == "latency":
        if not args.link:
            print("Usage: enhanced_faults.py latency -l zo-kora -v 200")
            sys.exit(1)
        apply_latency(args.link, args.value)

    elif args.action == "mixed":
        if not args.link:
            print("Usage: enhanced_faults.py mixed -l zo-kora")
            sys.exit(1)
        apply_mixed(args.link, args.value, args.value // 2)

    elif args.action == "gradual-loss":
        if not args.link:
            print("Usage: enhanced_faults.py gradual-loss -l zo-kora -d 60 --start 5 --end 100")
            sys.exit(1)
        gradual_fault(args.link, "loss", args.start, args.end, args.duration)

    elif args.action == "gradual-latency":
        if not args.link:
            print("Usage: enhanced_faults.py gradual-latency -l zo-kora -d 60 --start 10 --end 500")
            sys.exit(1)
        gradual_fault(args.link, "latency", args.start, args.end, args.duration)

    elif args.action == "reset":
        if not args.link:
            print("Usage: enhanced_faults.py reset -l zo-kora")
            sys.exit(1)
        reset_link(args.link)

    elif args.action == "reset-all":
        reset_all()

    elif args.action == "status":
        show_status()


if __name__ == "__main__":
    main()