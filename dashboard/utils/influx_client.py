"""
Netwroxia Dashboard — InfluxDB 1.8 Client
Reads live telemetry from Stage 2. Zero writes. Read-only.
"""
import requests
import pandas as pd
from typing import Optional, Dict
from datetime import datetime

# ── Config ──────────────────────────────────────────────
INFLUX_HOST = "http://localhost:8086"
DB_NAME = "netwroxia"
TIMEOUT = 5

# ── Core Query Engine ───────────────────────────────────
def _query(q: str) -> Optional[pd.DataFrame]:
    """Run InfluxDB 1.8 query, return DataFrame or None."""
    url = f"{INFLUX_HOST}/query"
    params = {"db": DB_NAME, "q": q, "epoch": "ms"}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if "results" not in payload or not payload["results"]:
            return None
        series = payload["results"][0].get("series", [])
        if not series:
            return pd.DataFrame()
        cols = series[0]["columns"]
        vals = series[0].get("values", [])
        df = pd.DataFrame(vals, columns=cols)
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        return df
    except Exception as e:
        print(f"[InfluxClient] Query failed: {e}")
        return None


# ── Measurement Readers ─────────────────────────────────
def get_ping_data(hours: int = 1, limit: int = 200) -> Optional[pd.DataFrame]:
    q = f'SELECT * FROM ping WHERE time > now() - {hours}h LIMIT {limit}'
    df = _query(q)
    if df is not None and not df.empty:
        for col in ["average_response_ms", "percent_packet_loss",
                    "minimum_response_ms", "maximum_response_ms",
                    "packets_transmitted", "packets_received", "result_code"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def get_ospf_data(hours: int = 1, limit: int = 200) -> Optional[pd.DataFrame]:
    q = f'SELECT * FROM ospf_neighbors WHERE time > now() - {hours}h LIMIT {limit}'
    df = _query(q)
    if df is not None and not df.empty and "count" in df.columns:
        df["count"] = pd.to_numeric(df["count"], errors="coerce").fillna(0).astype(int)
    return df


def get_bgp_data(hours: int = 1, limit: int = 200) -> Optional[pd.DataFrame]:
    q = f'SELECT * FROM bgp_peer WHERE time > now() - {hours}h LIMIT {limit}'
    df = _query(q)
    if df is not None and not df.empty and "state" in df.columns:
        df["state"] = pd.to_numeric(df["state"], errors="coerce").fillna(-1).astype(int)
    return df


def get_container_cpu(hours: int = 1, limit: int = 200) -> Optional[pd.DataFrame]:
    q = (f'SELECT * FROM docker_container_cpu '
         f'WHERE time > now() - {hours}h LIMIT {limit}')
    df = _query(q)
    if df is not None and not df.empty and "usage_percent" in df.columns:
        df["usage_percent"] = pd.to_numeric(df["usage_percent"], errors="coerce")
    return df


def get_container_mem(hours: int = 1, limit: int = 200) -> Optional[pd.DataFrame]:
    q = (f'SELECT * FROM docker_container_mem '
         f'WHERE time > now() - {hours}h LIMIT {limit}')
    df = _query(q)
    if df is not None and not df.empty and "usage_percent" in df.columns:
        df["usage_percent"] = pd.to_numeric(df["usage_percent"], errors="coerce")
    return df


# ── Latest Snapshot (for Overview cards) ────────────────
def get_latest_by_router() -> Dict[str, Dict]:
    """
    Returns the newest row per router across all measurements.
    Used for the status badges.
    """
    snapshot = {}

    # ── Ping ──
    df_ping = get_ping_data(hours=1, limit=50)
    if df_ping is not None and not df_ping.empty:
        df_ping = df_ping.sort_values("time")
        for url, grp in df_ping.groupby("url"):
            latest = grp.iloc[-1]
            rname = _ip_to_router(url)
            snapshot.setdefault(rname, {})
            snapshot[rname]["latency_ms"] = float(latest.get("average_response_ms", 0) or 0)
            snapshot[rname]["packet_loss_pct"] = float(latest.get("percent_packet_loss", 0) or 0)

    # ── OSPF ──
    df_ospf = get_ospf_data(hours=1, limit=50)
    if df_ospf is not None and not df_ospf.empty:
        df_ospf = df_ospf.sort_values("time")
        for router, grp in df_ospf.groupby("router"):
            latest = grp.iloc[-1]
            rname = _normalize_router(router)
            snapshot.setdefault(rname, {})
            snapshot[rname]["ospf_neighbors"] = int(latest.get("count", 0) or 0)

    # ── BGP ──
    df_bgp = get_bgp_data(hours=1, limit=50)
    if df_bgp is not None and not df_bgp.empty:
        df_bgp = df_bgp.sort_values("time")
        for router, grp in df_bgp.groupby("router"):
            latest = grp.iloc[-1]
            rname = _normalize_router(router)
            snapshot.setdefault(rname, {})
            snapshot[rname]["bgp_established"] = bool(int(latest.get("state", 0) or 0) == 1)

    # ── CPU ──
    df_cpu = get_container_cpu(hours=1, limit=50)
    if df_cpu is not None and not df_cpu.empty:
        df_cpu = df_cpu.sort_values("time")
        for cname, grp in df_cpu.groupby("container_name"):
            latest = grp.iloc[-1]
            rname = _container_to_router(cname)
            snapshot.setdefault(rname, {})
            snapshot[rname]["cpu_pct"] = float(latest.get("usage_percent", 0) or 0)

    # ── Mem ──
    df_mem = get_container_mem(hours=1, limit=50)
    if df_mem is not None and not df_mem.empty:
        df_mem = df_mem.sort_values("time")
        for cname, grp in df_mem.groupby("container_name"):
            latest = grp.iloc[-1]
            rname = _container_to_router(cname)
            snapshot.setdefault(rname, {})
            snapshot[rname]["mem_pct"] = float(latest.get("usage_percent", 0) or 0)

    return snapshot


# ── Helpers ─────────────────────────────────────────────
def _ip_to_router(ip: str) -> str:
    mapping = {
        "172.20.20.3": "HO-Chennai",
        "172.20.20.4": "ZO-Bengaluru",
        "172.20.20.5": "BR-Koramangala",
        "172.20.20.7": "BR-Whitefield",
    }
    return mapping.get(str(ip), str(ip))


def _container_to_router(cname: str) -> str:
    mapping = {
        "clab-netwroxia-ho-chennai": "HO-Chennai",
        "clab-netwroxia-zo-bengaluru": "ZO-Bengaluru",
        "clab-netwroxia-br-koramangala": "BR-Koramangala",
        "clab-netwroxia-br-whitefield": "BR-Whitefield",
    }
    return mapping.get(str(cname), str(cname))


def _normalize_router(name: str) -> str:
    """Normalize router names from various sources to consistent title case."""
    mapping = {
        "ho-chennai": "HO-Chennai",
        "zo-bengaluru": "ZO-Bengaluru",
        "br-koramangala": "BR-Koramangala",
        "br-whitefield": "BR-Whitefield",
        "ho_chennai": "HO-Chennai",
        "zo_bengaluru": "ZO-Bengaluru",
        "br_koramangala": "BR-Koramangala",
        "br_whitefield": "BR-Whitefield",
    }
    key = str(name).lower().strip()
    return mapping.get(key, str(name).title())


# ── Self-test ───────────────────────────────────────────
if __name__ == "__main__":
    print("Testing InfluxDB client...")
    for func, name in [
        (get_ping_data, "ping"),
        (get_ospf_data, "ospf_neighbors"),
        (get_bgp_data, "bgp_peer"),
        (get_container_cpu, "docker_container_cpu"),
        (get_container_mem, "docker_container_mem"),
    ]:
        df = func(hours=1, limit=5)
        if df is None:
            print(f"  ❌ {name}: InfluxDB unreachable")
        elif df.empty:
            print(f"  ⚠️  {name}: no data")
        else:
            print(f"  ✅ {name}: {len(df)} rows")
    snap = get_latest_by_router()
    print(f"\nLatest snapshot keys: {list(snap.keys())}")
    for r, d in snap.items():
        print(f"  {r}: {d}")
