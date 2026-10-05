"""
engines/topology.py
-------------------
WHAT IT DOES:
    Builds the network topology as a NetworkX directed graph
    (edge direction = upstream -> downstream, i.e. core towards access).

    Key functions used by the agents:
      upstream(dev)             -> every device between dev and the core
      downstream(dev)           -> every device below dev
      isolated_if_failed(nodes) -> devices that lose ALL paths to the core if `nodes` fail
                                   (this automatically accounts for redundant/backup links)
      degraded_if_failed(nodes) -> devices still reachable but which lost a path (redundancy used)
      localize(...)             -> RANKED fault-location hypotheses with evidence
                                   (used by the Topology & Fault Localization Agent)

WHY NETWORKX: the topology is small/medium, graph algorithms (ancestors, reachability,
shortest paths) are built in, and it runs in-memory with zero extra infrastructure.
The graph is rebuilt from PostgreSQL tables, so the DB stays the source of truth.
"""
import networkx as nx


class Topology:
    def __init__(self, devices: list, links: list):
        self.g = nx.DiGraph()
        for d in devices:
            self.g.add_node(d.id, type=d.device_type, layer=d.layer, region=d.region, status=d.status)
        for l in links:
            self.g.add_edge(l.source, l.target, id=l.id, backup=l.is_backup, status=l.status,
                            src_if=l.source_interface, dst_if=l.target_interface)
        # roots = devices with no upstream (internet gateway / core)
        self.roots = [n for n in self.g.nodes if self.g.in_degree(n) == 0]

    # ---------------- basic queries ----------------
    def upstream(self, dev):
        return nx.ancestors(self.g, dev) if dev in self.g else set()

    def downstream(self, dev):
        return nx.descendants(self.g, dev) if dev in self.g else set()

    def path_to_core(self, dev):
        """Primary (non-backup preferred) path from root to device."""
        best = None
        for r in self.roots:
            try:
                for p in nx.all_simple_paths(self.g, r, dev):
                    backup_hops = sum(self.g.edges[p[i], p[i + 1]]["backup"] for i in range(len(p) - 1))
                    if best is None or (backup_hops, len(p)) < best[0]:
                        best = ((backup_hops, len(p)), p)
            except nx.NetworkXError:
                pass
        return best[1] if best else [dev]

    def link_between(self, a, b):
        if self.g.has_edge(a, b):
            return self.g.edges[a, b]
        if self.g.has_edge(b, a):
            return self.g.edges[b, a]
        return None

    def related(self, a, b, max_hops=3):
        """Two devices are topologically related if one is upstream of the other
        or they share a non-root upstream parent within max_hops."""
        if a == b:
            return True
        if a not in self.g or b not in self.g:
            return False
        if b in self.upstream(a) or a in self.upstream(b):
            return True
        shared = (self.upstream(a) & self.upstream(b)) - set(self.roots)
        und = self.g.to_undirected(as_view=True)
        for s in shared:
            if s.startswith("CR"):       # sharing only the core is not enough evidence
                continue
            try:
                if nx.shortest_path_length(und, a, s) <= max_hops and nx.shortest_path_length(und, b, s) <= max_hops:
                    return True
            except nx.NetworkXNoPath:
                continue
        return False

    # ---------------- failure simulation ----------------
    def isolated_if_failed(self, failed_nodes=(), failed_edges=()):
        h = self.g.copy()
        h.remove_nodes_from([n for n in failed_nodes if n in h])
        h.remove_edges_from([e for e in failed_edges if h.has_edge(*e)])
        reachable = set()
        for r in self.roots:
            if r in h:
                reachable |= {r} | nx.descendants(h, r)
        return set(self.g.nodes) - reachable - set(failed_nodes)

    def degraded_if_failed(self, failed_nodes=(), failed_edges=()):
        """Devices still connected, but that lost one of their paths (running on redundancy)."""
        isolated = self.isolated_if_failed(failed_nodes, failed_edges)
        degraded = set()
        for n in self.g.nodes:
            if n in isolated or n in failed_nodes:
                continue
            for parent in self.g.predecessors(n):
                if parent in failed_nodes or parent in isolated or (parent, n) in failed_edges:
                    degraded.add(n)
        return degraded

    # ---------------- fault localization ----------------
    def localize(self, alarmed: dict, first_alarm_device: str | None = None, alarm_ifaces: dict | None = None):
        """
        alarmed -> {device: [alarm types]} for every device with an active alarm in the incident
        Returns ranked hypotheses. Each candidate (device or link) is scored by:
          coverage   = share of alarmed devices that this single failure explains
          precision  = share of devices this failure would isolate that are actually alarming
                       (penalises candidates that would also take down healthy devices)
          own_alarm  = candidate itself reports an alarm
          first      = candidate raised the earliest alarm
        """
        alarm_ifaces = alarm_ifaces or {}
        affected = set(alarmed)
        candidates = set()
        for d in affected:
            candidates |= {d} | (self.upstream(d) - set(self.roots))
        hyps = []
        for c in candidates:
            iso = self.isolated_if_failed([c]) | {c}
            degraded_healthy = self.degraded_if_failed([c]) - affected
            explained = affected & iso
            coverage = len(explained) / max(1, len(affected))
            # healthy devices that would lose redundancy also count (half weight) against the candidate
            precision = len(explained) / max(1, len(iso) + 0.5 * len(degraded_healthy))
            own = c in affected
            score = 0.5 * coverage + 0.25 * precision + (0.15 if own else 0) + (0.10 if c == first_alarm_device else 0)
            healthy_lost = sorted(iso - affected - {c})
            h = self._hyp("device", c, score, coverage, explained, healthy_lost, own, alarmed, first_alarm_device)
            if degraded_healthy:
                h["contradicting_evidence"].append(f"A full failure of {c} would also force {', '.join(sorted(degraded_healthy))} onto backup paths, but they report no alarms")
            hyps.append(h)

        # candidate links: uplink of every candidate device (failure of the cable/fiber itself)
        for c in list(candidates):
            for p in (self.g.predecessors(c) if c in self.g else []):
                e = self.g.edges[p, c]
                iso = self.isolated_if_failed(failed_edges=[(p, c)])
                ends = {x for x in (p, c) if x in affected}          # a cut link explains alarms on BOTH ends
                explained = affected & (iso | ends)
                coverage = len(explained) / max(1, len(affected))
                precision = len(explained) / max(1, len(iso | {c} | ends))
                both_ends = (p in affected and c in affected)
                if_alarm = any(t in ("interface_down", "crc_errors") for t in alarmed.get(c, []) + alarmed.get(p, []))
                src_match = e["src_if"] and e["src_if"] in alarm_ifaces.get(p, set())
                dst_match = e["dst_if"] and e["dst_if"] in alarm_ifaces.get(c, set())
                if src_match and dst_match:
                    bonus = 0.25          # both link interfaces reported down = strong span evidence
                elif src_match or dst_match:
                    bonus = 0.10
                else:
                    bonus = 0.15 if both_ends else 0.05 if if_alarm else 0
                score = 0.5 * coverage + 0.25 * precision + bonus
                if e["backup"] or coverage == 0:
                    continue
                h = self._hyp("link", e["id"], score, coverage, explained, sorted(iso - affected), if_alarm, alarmed, first_alarm_device)
                h["endpoints"] = [p, c]
                h["interfaces"] = [f"{p}:{e['src_if']}", f"{c}:{e['dst_if']}"]
                if src_match or dst_match:
                    h["evidence"].insert(0, "Alarm raised on the exact link interface(s): " +
                                         ", ".join(x for x, ok in [(f"{p}:{e['src_if']}", src_match), (f"{c}:{e['dst_if']}", dst_match)] if ok))
                if both_ends:
                    h["evidence"].insert(0, f"Both link ends ({p}, {c}) report alarms - typical of a physical span failure")
                hyps.append(h)

        # add uplink-interface evidence to device hypotheses
        for h in hyps:
            if h["type"] == "device" and h["location"] in self.g:
                for p in self.g.predecessors(h["location"]):
                    e = self.g.edges[p, h["location"]]
                    if e["dst_if"] in alarm_ifaces.get(h["location"], set()):
                        h["evidence"].insert(0, f"Alarmed interface {e['dst_if']} is the UPLINK of {h['location']} towards {p}")
        hyps.sort(key=lambda h: (-h["score"], h["type"] != "device"))
        for i, h in enumerate(hyps):
            nxt = hyps[i + 1]["score"] if i + 1 < len(hyps) else 0
            margin = h["score"] - nxt
            h["score"] = round(h["score"], 3)
            if i == 0:
                h["confidence"] = "high" if h["score"] >= 0.8 and margin >= 0.08 else "medium"
            else:
                h["confidence"] = "medium" if h["score"] >= 0.7 else "low"
        return hyps[:6]

    def _hyp(self, kind, cid, score, coverage, explained, healthy_lost, own, alarmed, first):
        ev = []
        if own and kind == "device":
            ev.append(f"{cid} itself raised: {', '.join(sorted(set(alarmed.get(cid, []))))}")
        if cid == first:
            ev.append(f"{cid} raised the earliest alarm in the incident")
        if explained:
            ev.append(f"A failure here explains {len(explained)}/{len(alarmed)} alarming devices: {', '.join(sorted(explained))}")
        dn = sorted(self.downstream(cid)) if kind == "device" else []
        if dn:
            ev.append(f"Downstream dependants per topology: {', '.join(dn)}")
        contra = []
        if healthy_lost:
            contra.append(f"Would also isolate devices with NO alarms: {', '.join(healthy_lost)}")
        if coverage < 1:
            contra.append(f"Does not explain {len(alarmed) - len(explained)} alarming device(s)")
        return {"type": kind, "location": cid, "score": score, "coverage": round(coverage, 2),
                "explained_devices": sorted(explained), "evidence": ev, "contradicting_evidence": contra}
