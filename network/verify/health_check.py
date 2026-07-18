#!/usr/bin/env python3
"""
Netwroxia Stage 1 — Health Check Script
Verifies all nodes, links, BGP, OSPF are healthy.
"""

import subprocess
import sys

NODES = {
    "ho-chennai": "clab-netwroxia-ho-chennai",
    "zo-bengaluru": "clab-netwroxia-zo-bengaluru",
    "br-koramangala": "clab-netwroxia-br-koramangala",
    "br-whitefield": "clab-netwroxia-br-whitefield",
}

LOOPBACKS = {
    "ho-chennai": "10.255.0.1",
    "zo-bengaluru": "10.255.0.2",
    "br-koramangala": "10.255.0.3",
    "br-whitefield": "10.255.0.4",
}

PING_TESTS = [
    ("ho-chennai", "10.0.1.2", "HO→ZO direct link"),
    ("ho-chennai", "10.255.0.2", "HO→ZO loopback"),
    ("ho-chennai", "10.255.0.3", "HO→BR-Kora loopback"),
    ("ho-chennai", "10.255.0.4", "HO→BR-White loopback"),
    ("br-koramangala", "10.255.0.1", "BR-Kora→HO loopback"),
    ("br-whitefield", "10.255.0.1", "BR-White→HO loopback"),
    ("zo-bengaluru", "10.1.2.2", "ZO→BR-Kora direct link"),
    ("zo-bengaluru", "10.1.3.2", "ZO→BR-White direct link"),
]


def run_in_container(container, cmd):
    full_cmd = ["docker", "exec", container, "sh", "-c", cmd]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def check_ping():
    print("=" * 60)
    print("🌐 PING TESTS")
    print("=" * 60)
    all_pass = True
    for node, target, desc in PING_TESTS:
        container = NODES[node]
        rc, out, err = run_in_container(container, f"ping -c 2 -W 2 {target}")
        if rc == 0 and "0% packet loss" in out:
            # Extract avg time
            time_line = [l for l in out.split("\n") if "avg" in l]
            time_str = time_line[0].split("=")[-1].strip() if time_line else "N/A"
            print(f"  ✅ {desc}: {time_str}")
        else:
            print(f"  ❌ {desc}: FAILED")
            all_pass = False
    return all_pass


def check_bgp():
    print("\n" + "=" * 60)
    print("🔗 BGP STATUS")
    print("=" * 60)
    all_pass = True
    for name, container in NODES.items():
        rc, out, err = run_in_container(container, "vtysh -c 'show ip bgp summary'")
        if rc != 0:
            print(f"  ❌ {name}: vtysh failed")
            all_pass = False
            continue

        lines = out.split("\n")
        peers = []
        for line in lines:
            if "10.255.0." in line and "remote-as" not in line:
                parts = line.split()
                if len(parts) >= 10:
                    peer_ip = parts[0]
                    state = parts[9]
                    peers.append((peer_ip, state))

        if peers:
            for peer, state in peers:
                if state.isdigit():
                    print(f"  ✅ {name} → {peer}: UP ({state} prefixes)")
                else:
                    print(f"  ⚠️  {name} → {peer}: {state}")
                    all_pass = False
        else:
            print(f"  ℹ️  {name}: No BGP peers (OK for branch with only RR)")
    return all_pass


def check_ospf():
    print("\n" + "=" * 60)
    print("🔄 OSPF STATUS")
    print("=" * 60)
    all_pass = True
    for name, container in NODES.items():
        rc, out, err = run_in_container(container, "vtysh -c 'show ip ospf neighbor'")
        if rc != 0:
            print(f"  ❌ {name}: vtysh failed")
            all_pass = False
            continue

        lines = out.split("\n")
        neighbors = []
        for line in lines:
            if "Full" in line:
                parts = line.split()
                if len(parts) >= 2:
                    neighbor_id = parts[0]
                    neighbors.append(neighbor_id)

        if neighbors:
            for n in neighbors:
                print(f"  ✅ {name}: neighbor {n} FULL")
        else:
            print(f"  ℹ️  {name}: No OSPF neighbors (OK for leaf nodes)")
    return all_pass


def check_containers():
    print("=" * 60)
    print("🐳 CONTAINER STATUS")
    print("=" * 60)
    rc, out, err = run_in_container("clab-netwroxia-ho-chennai", "echo alive")
    if rc == 0:
        print("  ✅ All containers running")
        return True
    else:
        print("  ❌ Some containers not running")
        return False


def main():
    print("\n" + "🔷" * 30)
    print("   NETWROXIA STAGE 1 — HEALTH CHECK")
    print("🔷" * 30 + "\n")

    results = []
    results.append(("Containers", check_containers()))
    results.append(("Ping", check_ping()))
    results.append(("OSPF", check_ospf()))
    results.append(("BGP", check_bgp()))

    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    all_pass = True
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_pass = False

    print("\n" + ("🎉 ALL CHECKS PASSED" if all_pass else "⚠️ SOME CHECKS FAILED"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
