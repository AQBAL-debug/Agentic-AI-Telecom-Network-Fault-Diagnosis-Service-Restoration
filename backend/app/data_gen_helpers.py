"""
data_gen_helpers.py
-------------------
WHAT IT DOES:
    Small helper re-used by the live simulator: produces ONE realistic "normal"
    telemetry sample for a device type (same baselines as data/generate_data.py),
    so live scenario data looks like the training data.
"""
import numpy as np

_rng = np.random.default_rng()


def _base(t):
    if t in ("core_router", "internet_gateway"):
        return dict(lat=(8, 1.5), loss=(0.05, 0.03), jit=(2, 0.6), util=(45, 8), cpu=(30, 5), mem=(50, 4), err=(0.5, 0.5), cap=100000)
    if t == "aggregation_router":
        return dict(lat=(15, 3), loss=(0.2, 0.08), jit=(5, 1.5), util=(50, 10), cpu=(35, 6), mem=(55, 5), err=(1, 1), cap=10000)
    return dict(lat=(25, 4), loss=(0.3, 0.1), jit=(8, 2), util=(55, 12), cpu=(40, 8), mem=(60, 5), err=(2, 1.5), cap=1000)


def normal_point(device_type: str, hour_frac: float) -> dict:
    b = _base(device_type)
    diurnal = 1 + 0.25 * np.sin((hour_frac - 9) / 24 * 2 * np.pi)
    util = float(np.clip(_rng.normal(b["util"][0] * diurnal, b["util"][1] * 0.6), 5, 80))
    return dict(latency_ms=float(max(1, _rng.normal(*b["lat"]))), packet_loss_pct=float(max(0, _rng.normal(*b["loss"]))),
                jitter_ms=float(max(0.2, _rng.normal(*b["jit"]))), utilization_pct=util,
                throughput_mbps=round(b["cap"] * util / 100, 2), cpu_pct=float(np.clip(_rng.normal(*b["cpu"]), 5, 80)),
                memory_pct=float(np.clip(_rng.normal(*b["mem"]), 10, 85)), interface_errors=float(max(0, _rng.normal(*b["err"]))),
                link_up=1.0)
