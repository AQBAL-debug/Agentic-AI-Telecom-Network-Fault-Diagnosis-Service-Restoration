"""
engines/correlation.py
----------------------
WHAT IT DOES:
    Groups raw alarms into meaningful incidents (the Alarm Correlation engine).

    Method (rule + topology based, fully explainable):
      1. DUPLICATES  - same device + same alarm type + same interface within the window
                       -> marked "duplicate" (hidden in incident view, never deleted).
      2. CLUSTERING  - union-find: two alarms join the same group when
                       |time difference| <= CORRELATION_WINDOW_SEC  AND
                       the devices are topologically related (same device, upstream/
                       downstream, or share a nearby common parent).
      3. PRIMARY     - inside a group the "primary suspected event" is the alarm on the
                       most-upstream device (it is an ancestor of the most other alarmed
                       devices), tie-broken by earliest timestamp and alarm type priority.
                       Everything else = "consequential".
      4. INDEPENDENT - a group with a single, unrelated alarm = independent incident.
      5. ALARM STORM - if a group exceeds STORM_THRESHOLD alarms it is flagged as a storm
                       and summarised (counts per device / type) instead of a flat list.
"""
from collections import defaultdict, Counter
from ..config import settings

# lower number = more likely to be a root/primary alarm type
TYPE_PRIORITY = {"power_failure": 0, "device_restart": 1, "node_unreachable": 1, "interface_down": 2,
                 "crc_errors": 3, "bgp_neighbor_down": 3, "high_cpu": 3, "high_utilization": 4,
                 "packet_loss": 4, "high_latency": 4, "high_jitter": 5, "backhaul_lost": 6,
                 "service_unavailable": 7}


class UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def mark_duplicates(alarms: list, window: int | None = None):
    """alarms: list of dicts sorted by timestamp. Sets role='duplicate' + duplicate_of."""
    window = window or settings.CORRELATION_WINDOW_SEC
    last_seen = {}
    for a in alarms:
        key = (a["device"], a["alarm_type"], a.get("interface", ""))
        prev = last_seen.get(key)
        if prev and (a["timestamp"] - prev["timestamp"]).total_seconds() <= window * 5:
            a["role"], a["duplicate_of"] = "duplicate", prev["id"]
        else:
            last_seen[key] = a
    return alarms


def correlate(alarms: list, topo, window: int | None = None):
    """
    alarms -> list of dicts {id, timestamp, device, alarm_type, severity, interface, role?}
    topo   -> engines.topology.Topology
    returns list of groups:
      {alarm_ids, primary_id, consequential_ids, duplicate_ids, devices, storm, storm_summary, reasoning}
    """
    window = window or settings.CORRELATION_WINDOW_SEC
    alarms = sorted(alarms, key=lambda a: a["timestamp"])
    mark_duplicates(alarms, window)
    uniq = [a for a in alarms if a.get("role") != "duplicate"]
    n = len(uniq)
    uf = UnionFind(n)
    rel_cache = {}

    def related(d1, d2):
        k = (d1, d2) if d1 <= d2 else (d2, d1)
        if k not in rel_cache:
            rel_cache[k] = topo.related(d1, d2)
        return rel_cache[k]

    for i in range(n):
        for j in range(i + 1, n):
            dt = (uniq[j]["timestamp"] - uniq[i]["timestamp"]).total_seconds()
            if dt > window:
                break                       # sorted by time -> nothing later can match i
            if related(uniq[i]["device"], uniq[j]["device"]):
                uf.union(i, j)

    groups = defaultdict(list)
    for i, a in enumerate(uniq):
        groups[uf.find(i)].append(a)

    # attach duplicates to the group of the alarm they duplicate
    id_to_root = {a["id"]: uf.find(i) for i, a in enumerate(uniq)}
    for a in alarms:
        if a.get("role") == "duplicate":
            root = id_to_root.get(a["duplicate_of"])
            if root is not None:
                groups[root].append(a)
                id_to_root[a["id"]] = root

    result = []
    for members in groups.values():
        unique = [m for m in members if m.get("role") != "duplicate"]
        devices = sorted({m["device"] for m in unique})

        def rank(m):
            dn = len(topo.downstream(m["device"]) & set(devices))
            return (-dn, TYPE_PRIORITY.get(m["alarm_type"], 5), m["timestamp"])

        primary = min(unique, key=rank)
        conseq = [m["id"] for m in unique if m["id"] != primary["id"]]
        dups = [m["id"] for m in members if m.get("role") == "duplicate"]
        storm = len(members) >= settings.STORM_THRESHOLD
        reasoning = [f"{len(unique)} unique alarms within {window}s window on topologically related devices"
                     if len(unique) > 1 else "Single alarm with no related alarms in the time window"]
        if len(unique) > 1:
            dn = topo.downstream(primary["device"]) & set(devices)
            reasoning.append(f"{primary['device']} is upstream of {len(dn)} other alarmed device(s): {', '.join(sorted(dn)) or '-'}")
            reasoning.append(f"Primary alarm {primary['alarm_type']} at {primary['timestamp'].strftime('%H:%M:%S')} "
                             f"is {'the earliest' if primary['timestamp'] == min(m['timestamp'] for m in unique) else 'not the earliest but most upstream'}")
        if dups:
            reasoning.append(f"{len(dups)} duplicate/repeated alarm(s) suppressed from view (kept for audit)")
        result.append({
            "alarm_ids": [m["id"] for m in members],
            "primary_id": primary["id"],
            "primary_device": primary["device"],
            "primary_type": primary["alarm_type"],
            "consequential_ids": conseq,
            "duplicate_ids": dups,
            "devices": devices,
            "independent": len(unique) == 1,
            "storm": storm,
            "storm_summary": {
                "total_alarms": len(members),
                "by_device": dict(Counter(m["device"] for m in members).most_common()),
                "by_type": dict(Counter(m["alarm_type"] for m in members).most_common()),
            } if storm else {},
            "first_time": min(m["timestamp"] for m in members),
            "last_time": max(m["timestamp"] for m in members),
            "severity": "critical" if any(m["severity"] == "critical" for m in members) else "major",
            "reasoning": reasoning,
        })
    result.sort(key=lambda g: g["first_time"])
    return result
