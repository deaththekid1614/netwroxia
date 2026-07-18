# BGP Troubleshooting Runbook — Netwroxia NOC
## Document ID: RB-BGP-001
## Last Updated: 2026-07-15

---

### Symptom: BGP Peer Down / Route Flapping

#### Impact Assessment
- **Severity:** HIGH — Routing blackholes, traffic loss
- **Affected Services:** CBS queries, ATM transactions, UPI payments
- **SLA Risk:** RBI mandates 99.9% uptime for core banking

#### Root Causes (Ranked by Frequency)
1. **Interface congestion** (45%) — Link utilization &gt;90% causes BGP hold timer expiry
2. **MTU mismatch** (25%) — MPLS labels add bytes; default 1500 MTU drops BGP packets
3. **AS path loop** (15%) — Misconfigured route reflector or duplicate AS numbers
4. **TCP session reset** (10%) — Firewall or ACL blocking port 179
5. **Hardware failure** (5%) — NIC or cable fault

#### Diagnostic Commands
```bash
# Check BGP peer state
vtysh -c "show ip bgp summary"
vtysh -c "show ip bgp neighbors &lt;peer_ip&gt;"

# Check interface stats
vtysh -c "show interface eth1"
vtysh -c "show ip route"

# Check for drops
docker exec &lt;router&gt; vtysh -c "show interface eth1" | grep drops
