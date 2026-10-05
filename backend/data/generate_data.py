"""
generate_data.py
----------------
WHAT IT DOES:
    Creates the SYNTHETIC telecom dataset used by the whole project
    (no real telecom hardware is needed). Run once:  python data/generate_data.py

    Output files (in backend/data/):
      topology.json            -> 20 network elements + links (core / aggregation / access)
      services.json            -> services and which devices they depend on
      historical_incidents.json-> 14 past incidents (for similarity retrieval)
      telemetry_history.csv    -> 24 h of 5-minute metrics for every device,
                                  with LABELLED anomalies (congestion, degradation,
                                  CPU spikes, telemetry glitches) used to train and
                                  evaluate the anomaly-detection model.
    The SOP / troubleshooting documents live in data/sop_docs/*.md (hand written).
"""
import json, random
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
rng = np.random.default_rng(42)
random.seed(42)

# ------------------------------------------------------------------ topology
# layer: 0 = internet/core, 1 = aggregation, 2 = access/edge
DEVICES = [
    # id,        name,                        type,                 layer, region,      vendor,   model,          services
    ("GW-INT-01", "Internet Gateway 01",      "internet_gateway",   0, "Core-DC",   "Juniper", "MX960",        ["SVC-CORE"]),
    ("CR-01",     "Core Router 01",           "core_router",        0, "Core-DC",   "Cisco",   "ASR 9906",     ["SVC-CORE"]),
    ("CR-02",     "Core Router 02",           "core_router",        0, "Core-DC",   "Juniper", "PTX10008",     ["SVC-CORE"]),
    ("AR-01",     "Aggregation Router 01",    "aggregation_router", 1, "North",     "Cisco",   "ASR 920",      []),
    ("AR-02",     "Aggregation Router 02",    "aggregation_router", 1, "East",      "Nokia",   "7750 SR-1",    []),
    ("AR-03",     "Aggregation Router 03",    "aggregation_router", 1, "South",     "Huawei",  "NE40E-X8",     []),
    ("SW-301",    "Access Switch 301",        "switch",             2, "South",     "Huawei",  "S6730",        []),
    ("BS-101",    "Base Station 101",         "base_station",       2, "North",     "Ericsson","RBS 6630",     ["SVC-BS-101"]),
    ("BS-102",    "Base Station 102",         "base_station",       2, "North",     "Ericsson","RBS 6630",     ["SVC-BS-102"]),
    ("ENT-GW-101","Enterprise Gateway 101",   "enterprise_gw",      2, "North",     "Cisco",   "ISR 4451",     ["E-101"]),
    ("BS-201",    "Base Station 201",         "base_station",       2, "East",      "Nokia",   "AirScale",     ["SVC-BS-201"]),
    ("BS-202",    "Base Station 202",         "base_station",       2, "East",      "Nokia",   "AirScale",     ["SVC-BS-202"]),
    ("BS-203",    "Base Station 203",         "base_station",       2, "East",      "Nokia",   "AirScale",     ["SVC-BS-203"]),
    ("ENT-GW-201","Enterprise Gateway 201",   "enterprise_gw",      2, "East",      "Juniper", "SRX1500",      ["E-201"]),
    ("BS-301",    "Base Station 301",         "base_station",       2, "South",     "Huawei",  "BBU5900",      ["SVC-BS-301"]),
    ("BS-302",    "Base Station 302",         "base_station",       2, "South",     "Huawei",  "BBU5900",      ["SVC-BS-302"]),
    ("BS-303",    "Base Station 303",         "base_station",       2, "South",     "Huawei",  "BBU5900",      ["SVC-BS-303"]),
    ("BS-304",    "Base Station 304",         "base_station",       2, "South",     "Huawei",  "BBU5900",      ["SVC-BS-304"]),
]

# (source=upstream, target=downstream, src_if, dst_if, type, capacity, is_backup)
LINKS = [
    ("GW-INT-01", "CR-01", "xe-0/0/0", "Te0/0/0/0", "fiber", 100000, False),
    ("GW-INT-01", "CR-02", "xe-0/0/1", "et-0/0/0",  "fiber", 100000, False),
    ("CR-01", "CR-02",     "Te0/0/0/5", "et-0/0/5", "fiber", 100000, False),
    ("CR-01", "AR-01",     "Te0/0/0/1", "GE-0/0/24", "fiber", 10000, False),
    ("CR-01", "AR-02",     "Te0/0/0/2", "1/1/1",    "fiber", 10000, False),
    ("CR-02", "AR-02",     "et-0/0/2",  "1/1/2",    "fiber", 10000, True),   # backup uplink for AR-02 (redundant)
    ("CR-02", "AR-03",     "et-0/0/3",  "GE0/1/0",  "fiber", 10000, False),
    ("AR-01", "BS-101",    "GE-0/0/1",  "eth0",     "fiber", 1000, False),
    ("AR-01", "BS-102",    "GE-0/0/2",  "eth0",     "microwave", 1000, False),
    ("AR-01", "ENT-GW-101","GE-0/0/3",  "Gi0/0/0",  "fiber", 1000, False),
    ("AR-02", "BS-201",    "1/2/1",     "eth0",     "fiber", 1000, False),
    ("AR-02", "BS-202",    "1/2/2",     "eth0",     "fiber", 1000, False),
    ("AR-02", "BS-203",    "1/2/3",     "eth0",     "microwave", 1000, False),
    ("AR-02", "ENT-GW-201","1/2/4",     "ge-0/0/0", "fiber", 1000, False),
    ("AR-03", "SW-301",    "GE0/2/0",   "XGE0/0/1", "fiber", 10000, False),
    ("SW-301", "BS-301",   "GE0/0/1",   "eth0",     "fiber", 1000, False),
    ("SW-301", "BS-302",   "GE0/0/2",   "eth0",     "fiber", 1000, False),
    ("SW-301", "BS-303",   "GE0/0/3",   "eth0",     "fiber", 1000, False),
    ("AR-02", "BS-303",    "1/2/5",     "eth1",     "microwave", 1000, True),  # BS-303 dual-homed (redundant)
    ("AR-03", "BS-304",    "GE0/2/1",   "eth0",     "fiber", 1000, False),
]

SERVICES = [
    # id, name, type, region, depends_on(devices), customers (None = unknown -> never invented)
    ("SVC-CORE",   "Core IP Transport",           "core_transport",  "Core-DC", ["GW-INT-01", "CR-01", "CR-02"], None),
    ("SVC-BS-101", "LTE/5G Access - Site 101",    "mobile_access",   "North",   ["BS-101", "AR-01", "CR-01"], 4200),
    ("SVC-BS-102", "LTE/5G Access - Site 102",    "mobile_access",   "North",   ["BS-102", "AR-01", "CR-01"], 3100),
    ("E-101",      "Enterprise Link E-101 (Bank)","enterprise_link", "North",   ["ENT-GW-101", "AR-01", "CR-01"], None),
    ("SVC-BS-201", "LTE/5G Access - Site 201",    "mobile_access",   "East",    ["BS-201", "AR-02"], 2800),
    ("SVC-BS-202", "LTE/5G Access - Site 202",    "mobile_access",   "East",    ["BS-202", "AR-02"], 2500),
    ("SVC-BS-203", "LTE/5G Access - Site 203",    "mobile_access",   "East",    ["BS-203", "AR-02"], None),
    ("E-201",      "Enterprise Link E-201 (Hospital)","enterprise_link","East", ["ENT-GW-201", "AR-02"], None),
    ("SVC-BS-301", "LTE/5G Access - Site 301",    "mobile_access",   "South",   ["BS-301", "SW-301", "AR-03", "CR-02"], 1900),
    ("SVC-BS-302", "LTE/5G Access - Site 302",    "mobile_access",   "South",   ["BS-302", "SW-301", "AR-03", "CR-02"], 2200),
    ("SVC-BS-303", "LTE/5G Access - Site 303",    "mobile_access",   "South",   ["BS-303", "SW-301", "AR-03"], 1500),
    ("SVC-BS-304", "LTE/5G Access - Site 304",    "mobile_access",   "South",   ["BS-304", "AR-03", "CR-02"], None),
]

HISTORICAL = [
    ("INC-NET-032", "2026-03-14", "Fiber uplink failure on aggregation router caused loss of three downstream sites",
     "aggregation_router", "interface_down on aggregation uplink followed by backhaul_lost and service_unavailable on 3 downstream base stations",
     "Fiber cut on uplink span due to civil works", "physical_link_failure",
     "Field team dispatched, fiber spliced; traffic restored after OTDR test", 3, 185),
    ("INC-NET-041", "2026-04-02", "Aggregation router SFP failure isolated two base stations",
     "aggregation_router", "interface_down with rising CRC errors then backhaul_lost on 2 base stations",
     "Faulty SFP optic module on access-facing interface", "interface_failure",
     "SFP replaced under approved MOP, interface errors cleared", 2, 95),
    ("INC-NET-047", "2026-04-19", "Configuration change on aggregation router dropped downstream connectivity",
     "aggregation_router", "interface_down after config commit; bgp_neighbor_down; backhaul_lost on downstream sites",
     "Incorrect VLAN configuration pushed during change window", "configuration_issue",
     "Configuration rolled back to last known good after CAB approval", 2, 40),
    ("INC-NET-052", "2026-05-06", "Core link congestion during evening peak",
     "core_router", "high_utilization, high_latency and packet_loss on core uplink; no interface down",
     "Traffic growth exceeded link capacity during peak hours", "network_congestion",
     "Traffic engineering: load shared onto backup path, capacity upgrade ticket raised", 0, 120),
    ("INC-NET-058", "2026-05-21", "Base station power outage",
     "base_station", "power_failure, node_unreachable on one base station; upstream router healthy",
     "Commercial power failure at site, battery depleted", "power_failure",
     "Power restored by utility; generator dispatched for resilience", 0, 210),
    ("INC-NET-063", "2026-06-03", "Aggregation router reboot after software crash",
     "aggregation_router", "node_unreachable then device_restart on aggregation router; all downstream backhaul_lost briefly",
     "Software process crash (routing daemon) triggered watchdog reboot", "software_failure",
     "Device recovered automatically; vendor TAC case opened, patch scheduled", 3, 25),
    ("INC-NET-066", "2026-06-17", "Microwave backhaul degradation due to rain fade",
     "base_station", "high_packet_loss and high_jitter on microwave link, link flapping",
     "Heavy rain attenuation on microwave hop", "physical_link_failure",
     "Adaptive modulation adjusted, monitored until weather cleared", 1, 75),
    ("INC-NET-071", "2026-07-02", "False packet loss alarm from faulty probe",
     "aggregation_router", "packet_loss reported 100% by one probe while interface counters and services normal",
     "Telemetry probe misconfiguration", "telemetry_issue",
     "Probe reconfigured; no network impact", 0, 30),
    ("INC-NET-075", "2026-07-15", "Core router line card failure",
     "core_router", "linecard_failure, multiple interface_down on core router, traffic rerouted",
     "Hardware failure on line card slot 2", "device_hardware_failure",
     "Line card replaced under maintenance window, traffic shifted to CR-02", 2, 240),
    ("INC-NET-080", "2026-07-29", "Routing issue after BGP session flap",
     "core_router", "bgp_neighbor_down, route_withdrawn, latency increase on alternate path",
     "Upstream provider BGP session instability", "routing_issue",
     "BGP dampening applied, provider ticket raised", 0, 60),
    ("INC-NET-084", "2026-08-11", "Access switch failure took down three base stations",
     "switch", "node_unreachable on access switch then backhaul_lost on 3 base stations",
     "Switch power supply unit failure", "device_hardware_failure",
     "PSU replaced; dual PSU recommended", 3, 150),
    ("INC-NET-088", "2026-08-25", "Traffic shift caused congestion after link failure",
     "aggregation_router", "interface_down on primary uplink, high_utilization on backup path, latency increase",
     "Primary link failure shifted traffic to lower-capacity backup", "physical_link_failure",
     "Primary link repaired; backup capacity review raised", 2, 130),
    ("INC-NET-091", "2026-09-08", "Enterprise link down due to customer premises issue",
     "enterprise_gw", "interface_down on enterprise gateway, upstream aggregation router healthy",
     "Customer premises equipment powered off", "external_connectivity_failure",
     "Customer contacted, CPE powered on", 0, 45),
    ("INC-NET-095", "2026-09-20", "High CPU on aggregation router degraded forwarding",
     "aggregation_router", "high_cpu, increased latency and jitter on all downstream sites, no interface down",
     "Control-plane storm from misconfigured protocol timer", "software_failure",
     "Protocol timers corrected, CoPP policy reviewed", 3, 70),
]


def baseline_for(device_type: str):
    """Typical 'normal' values per device type (mean, std)."""
    if device_type in ("core_router", "internet_gateway"):
        return dict(lat=(8, 1.5), loss=(0.05, 0.03), jit=(2, 0.6), util=(45, 8), cpu=(30, 5), mem=(50, 4), err=(0.5, 0.5))
    if device_type == "aggregation_router":
        return dict(lat=(15, 3), loss=(0.2, 0.08), jit=(5, 1.5), util=(50, 10), cpu=(35, 6), mem=(55, 5), err=(1, 1))
    return dict(lat=(25, 4), loss=(0.3, 0.1), jit=(8, 2), util=(55, 12), cpu=(40, 8), mem=(60, 5), err=(2, 1.5))


def normal_point(dev_type: str, hour_frac: float):
    """One normal telemetry sample. Utilization follows a day/night (diurnal) curve."""
    b = baseline_for(dev_type)
    diurnal = 1 + 0.25 * np.sin((hour_frac - 9) / 24 * 2 * np.pi)   # peak in the evening
    util = float(np.clip(rng.normal(b["util"][0] * diurnal, b["util"][1]), 5, 85))
    return dict(
        latency_ms=float(max(1, rng.normal(*b["lat"]) * (1 + (util - 50) / 400))),
        packet_loss_pct=float(max(0, rng.normal(*b["loss"]))),
        jitter_ms=float(max(0.2, rng.normal(*b["jit"]))),
        utilization_pct=util,
        throughput_mbps=0.0,  # filled later from capacity
        cpu_pct=float(np.clip(rng.normal(*b["cpu"]), 5, 90)),
        memory_pct=float(np.clip(rng.normal(*b["mem"]), 10, 90)),
        interface_errors=float(max(0, rng.normal(*b["err"]))),
        link_up=1.0,
    )


def make_telemetry(end: datetime, hours: int = 24, step_min: int = 5) -> pd.DataFrame:
    rows = []
    cap = {}
    for s, t, *_rest in LINKS:
        cap[t] = max(cap.get(t, 0), _rest[3])
    cap.setdefault("GW-INT-01", 100000)
    n = hours * 60 // step_min
    start = end - timedelta(minutes=step_min * n)
    for d in DEVICES:
        dev, dtype = d[0], d[2]
        for i in range(n):
            ts = start + timedelta(minutes=step_min * i)
            p = normal_point(dtype, ts.hour + ts.minute / 60)
            p["throughput_mbps"] = round(cap.get(dev, 1000) * p["utilization_pct"] / 100, 2)
            rows.append(dict(timestamp=ts, device=dev, label=0, anomaly_kind="normal", **p))
    df = pd.DataFrame(rows)

    # ---- inject labelled anomalies (ground truth for evaluation) ----
    def inject(device, start_idx, length, kind):
        idx = df[(df.device == device)].index[start_idx:start_idx + length]
        for k, j in enumerate(idx):
            if kind == "congestion":          # util high + latency/loss/jitter high
                df.loc[j, ["utilization_pct", "latency_ms", "packet_loss_pct", "jitter_ms"]] = [
                    rng.uniform(92, 99), rng.uniform(120, 220), rng.uniform(4, 10), rng.uniform(30, 55)]
            elif kind == "degradation":       # slowly rising errors + loss (gradual)
                f = (k + 1) / length
                df.loc[j, "interface_errors"] = 2 + 80 * f
                df.loc[j, "packet_loss_pct"] = 0.3 + 4 * f
                df.loc[j, "latency_ms"] = df.loc[j, "latency_ms"] * (1 + f)
            elif kind == "cpu_spike":
                df.loc[j, ["cpu_pct", "latency_ms", "jitter_ms"]] = [rng.uniform(92, 99), rng.uniform(60, 120), rng.uniform(20, 40)]
            elif kind == "link_down":
                df.loc[j, ["link_up", "utilization_pct", "throughput_mbps", "packet_loss_pct"]] = [0, 0, 0, 100]
            elif kind == "telemetry_glitch":  # impossible single value, others normal
                df.loc[j, "latency_ms"] = 9999.0
            df.loc[j, "label"] = 1
            df.loc[j, "anomaly_kind"] = kind

    inject("CR-01", 200, 10, "congestion")
    inject("AR-02", 120, 24, "degradation")
    inject("AR-03", 60, 6, "cpu_spike")
    inject("BS-203", 150, 8, "congestion")
    inject("BS-102", 90, 5, "link_down")
    inject("AR-01", 240, 1, "telemetry_glitch")
    inject("BS-301", 30, 12, "degradation")
    inject("ENT-GW-201", 180, 4, "cpu_spike")
    df["throughput_mbps"] = df["throughput_mbps"].round(2)
    return df


def main():
    devices = [dict(id=d[0], name=d[1], device_type=d[2], layer=d[3], region=d[4], vendor=d[5], model=d[6],
                    services=d[7], ip_address=f"10.{d[3]}.{i // 250}.{i % 250 + 1}",
                    interfaces=sorted({l[2] for l in LINKS if l[0] == d[0]} | {l[3] for l in LINKS if l[1] == d[0]}))
               for i, d in enumerate(DEVICES)]
    links = [dict(id=f"L-{s}-{t}".replace("-0", "0"), source=s, target=t, source_interface=si, target_interface=ti,
                  link_type=lt, capacity_mbps=c, is_backup=b) for s, t, si, ti, lt, c, b in LINKS]
    (OUT / "topology.json").write_text(json.dumps({"devices": devices, "links": links}, indent=2))
    (OUT / "services.json").write_text(json.dumps(
        [dict(id=s[0], name=s[1], service_type=s[2], region=s[3], depends_on=s[4], customers=s[5]) for s in SERVICES], indent=2))
    (OUT / "historical_incidents.json").write_text(json.dumps(
        [dict(id=h[0], date=h[1], title=h[2], device_type=h[3], alarm_pattern=h[4], root_cause=h[5],
              root_cause_category=h[6], resolution=h[7], downstream_impact=h[8], mttr_minutes=h[9]) for h in HISTORICAL], indent=2))
    df = make_telemetry(datetime(2026, 10, 3, 10, 0, 0))
    df.to_csv(OUT / "telemetry_history.csv", index=False)
    print(f"devices={len(devices)} links={len(links)} services={len(SERVICES)} "
          f"telemetry_rows={len(df)} anomalies={int(df.label.sum())}")


if __name__ == "__main__":
    main()
