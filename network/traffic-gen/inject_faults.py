#!/usr/bin/env python3
"""
Netwroxia Stage 1 — Fault Injection Script
Simulates network issues for ML training data + demo purposes.
"""

import subprocess
import sys
import argparse

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
    """Run a command inside a Docker container."""
    full_cmd = ["docker", "exec", container, "sh", "-c", cmd]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def add_latency(link, ms):
    """Add latency to a link."""
    if link not in LINKS:
        print(f"Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    cmd = f"tc qdisc add dev {iface} root netem delay {ms}ms || tc qdisc change dev {iface} root netem delay {ms}ms"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Added {ms}ms latency on {link} ({node}:{iface})")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def add_loss(link, percent):
    """Add packet loss to a link."""
    if link not in LINKS:
        print(f"Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    cmd = f"tc qdisc add dev {iface} root netem loss {percent}% || tc qdisc change dev {iface} root netem loss {percent}%"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Added {percent}% packet loss on {link} ({node}:{iface})")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def add_congestion(link, rate):
    """Rate-limit a link."""
    if link not in LINKS:
        print(f"Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    cmd = f"tc qdisc add dev {iface} root tbf rate {rate} burst 32kbit latency 400ms || tc qdisc change dev {iface} root tbf rate {rate} burst 32kbit latency 400ms"
    rc, out, err = run_in_container(container, cmd)
    if rc == 0:
        print(f"✅ Rate-limited {link} to {rate} ({node}:{iface})")
        return True
    else:
        print(f"❌ Failed: {err.strip()}")
        return False


def reset_link(link):
    """Remove all tc rules from a link."""
    if link not in LINKS:
        print(f"Unknown link: {link}. Available: {list(LINKS.keys())}")
        return False
    node, iface = LINKS[link]
    container = NODES[node]
    cmd = f"tc qdisc del dev {iface} root 2>/dev/null; echo cleared"
    rc, out, err = run_in_container(container, cmd)
    print(f"✅ Reset {link} ({node}:{iface})")
    return True


def reset_all():
    """Clear all tc rules from all nodes."""
    for name, container in NODES.items():
        cmd = "tc qdisc del dev eth0 root 2>/dev/null; echo done"
        run_in_container(container, cmd)
    print("✅ Reset all links")


def show_status():
    """Show current tc rules on all interfaces."""
    for name, container in NODES.items():
        print(f"\n📡 {name}:")
        rc, out, err = run_in_container(container, "tc qdisc show dev eth0")
        if out.strip():
            print(f"  eth0: {out.strip()}")
        else:
            print(f"  eth0: (no rules)")


def main():
    parser = argparse.ArgumentParser(description="Netwroxia Fault Injection")
    parser.add_argument("action", choices=["latency", "loss", "congestion", "reset", "reset-all", "status"])
    parser.add_argument("--link", "-l", choices=list(LINKS.keys()), help="Link to target")
    parser.add_argument("--value", "-v", type=str, help="Value: ms for latency, % for loss, rate for congestion (e.g. 1mbit)")

    args = parser.parse_args()

    if args.action == "latency":
        if not args.link or not args.value:
            print("Usage: inject_faults.py latency -l ho-zo -v 100")
            sys.exit(1)
        add_latency(args.link, args.value)

    elif args.action == "loss":
        if not args.link or not args.value:
            print("Usage: inject_faults.py loss -l ho-zo -v 5")
            sys.exit(1)
        add_loss(args.link, args.value)

    elif args.action == "congestion":
        if not args.link or not args.value:
            print("Usage: inject_faults.py congestion -l ho-zo -v 1mbit")
            sys.exit(1)
        add_congestion(args.link, args.value)

    elif args.action == "reset":
        if not args.link:
            print("Usage: inject_faults.py reset -l ho-zo")
            sys.exit(1)
        reset_link(args.link)

    elif args.action == "reset-all":
        reset_all()

    elif args.action == "status":
        show_status()


if __name__ == "__main__":
    main()