"""
engines/impact.py
-----------------
WHAT IT DOES:
    Service-impact calculation used by the Service Impact Analysis Agent.
    Given the suspected failed device(s)/link(s) it uses the topology to find:
      * UNAVAILABLE devices  -> lost every path to the core
      * DEGRADED devices     -> still reachable but running on a backup path (redundancy used)
      * affected SERVICES    -> unavailable if any dependency is down/isolated,
                                degraded if a dependency is only running on redundancy
      * customer counts      -> summed ONLY where the data exists; unknown counts are
                                reported as "unknown" and NEVER invented.
"""


def analyze_impact(topo, services: list, failed_nodes=(), failed_edges=(), observed_down=()):
    failed_nodes, failed_edges = set(failed_nodes), set(map(tuple, failed_edges))
    isolated = topo.isolated_if_failed(failed_nodes, failed_edges) | set(observed_down)
    degraded = topo.degraded_if_failed(failed_nodes, failed_edges) - isolated
    down = isolated | failed_nodes

    svc_rows, known_customers, unknown_customer_services = [], 0, []
    for s in services:
        deps = set(s.depends_on)
        if deps & down:
            state, why = "unavailable", f"depends on {', '.join(sorted(deps & down))} (down/isolated)"
        elif deps & degraded:
            state, why = "degraded", f"depends on {', '.join(sorted(deps & degraded))} (running on redundant path)"
        else:
            continue
        if s.customers is None:
            unknown_customer_services.append(s.id)
        else:
            known_customers += s.customers
        svc_rows.append({"service_id": s.id, "name": s.name, "type": s.service_type, "region": s.region,
                         "status": state, "reason": why,
                         "customers": s.customers if s.customers is not None else "unknown"})

    affected_links = []
    for u, v, e in topo.g.edges(data=True):
        if u in down or v in down or (u, v) in failed_edges:
            affected_links.append({"link": e["id"], "from": u, "to": v, "backup": e["backup"]})

    redundancy = []
    for n in sorted(degraded):
        redundancy.append(f"{n} lost a path but remains connected via a redundant/backup link")
    for n in sorted(isolated):
        redundancy.append(f"{n}: no redundant path available")

    return {
        "failed_elements": sorted(failed_nodes) + [f"{a}->{b}" for a, b in failed_edges],
        "unavailable_devices": sorted(isolated - failed_nodes),
        "degraded_devices": sorted(degraded),
        "affected_base_stations": sorted(d for d in down | degraded if d.startswith("BS-")),
        "affected_links": affected_links,
        "affected_services": svc_rows,
        "service_groups": sorted({r["type"] for r in svc_rows}),
        "regions": sorted({r["region"] for r in svc_rows}),
        "redundancy": redundancy or ["No redundancy impact detected"],
        "customers_known_total": known_customers,
        "services_with_unknown_customers": unknown_customer_services,
        "summary": (f"{len(down - failed_nodes) + len(degraded)} network element(s) affected; "
                    f"{sum(r['status'] == 'unavailable' for r in svc_rows)} service(s) unavailable, "
                    f"{sum(r['status'] == 'degraded' for r in svc_rows)} degraded. "
                    f"Known customers impacted: {known_customers}"
                    + (f" (+ unknown for {len(unknown_customer_services)} service(s))" if unknown_customer_services else "")),
    }
