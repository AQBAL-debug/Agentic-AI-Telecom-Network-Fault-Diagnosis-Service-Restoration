"""
engines/anomaly.py
------------------
WHAT IT DOES:
    The anomaly-detection MODEL used by the Network Performance & Anomaly Detection Agent.

    APPROACH (hybrid, chosen on purpose):
      Step 1  Per-device ROBUST BASELINE   -> median + MAD of every metric for that device
              (devices have very different "normal": core latency 8 ms, base station 25 ms).
      Step 2  FEATURES = robust z-scores of the 8 metrics relative to that baseline
              (+ link_up flag). Normalising per device lets ONE model serve all devices.
      Step 3  ISOLATION FOREST (scikit-learn, unsupervised) on those z-features
              -> catches "unusual metric COMBINATIONS" (e.g. moderate util + high jitter + errors).
      Step 4  STATISTICAL THRESHOLD (|z| > 6 or link down) -> catches extreme single-metric jumps.
      Final   anomaly = IF flags it OR threshold flags it; score in [0,1].
              Explanation = which metrics deviated and by how many sigma.

    WHY: no labelled real data exists -> unsupervised; Isolation Forest is fast, works on
    small tabular data, needs no GPU; z-score layer keeps the result EXPLAINABLE for a NOC
    engineer. LSTM/autoencoder would need far more data and be harder to explain.

    It also classifies the anomaly PATTERN (congestion, link_down, cpu_overload,
    gradual_degradation, possible_telemetry_issue) to feed root-cause analysis.

    Training data: data/telemetry_history.csv (synthetic, labels used ONLY for evaluation).
    Run training:  python -m app.engines.anomaly     -> saves models/anomaly_model.joblib + metrics
"""
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, f1_score, confusion_matrix
from ..config import DATA_DIR, MODEL_DIR

METRICS = ["latency_ms", "packet_loss_pct", "jitter_ms", "utilization_pct",
           "cpu_pct", "memory_pct", "interface_errors", "throughput_mbps"]
Z_THRESHOLD = 6.0
MODEL_PATH = MODEL_DIR / "anomaly_model.joblib"
METRICS_PATH = MODEL_DIR / "anomaly_metrics.json"


def compute_baselines(df: pd.DataFrame) -> dict:
    """median and MAD per device per metric (robust to the anomalies inside the data)."""
    base = {}
    for dev, g in df.groupby("device"):
        base[dev] = {}
        for m in METRICS:
            med = float(g[m].median())
            mad = float((g[m] - med).abs().median()) * 1.4826
            base[dev][m] = {"median": med, "mad": max(mad, 0.05 * abs(med) + 0.05)}
    return base


def zfeatures(df: pd.DataFrame, baselines: dict) -> np.ndarray:
    rows = []
    for _, r in df.iterrows():
        b = baselines.get(r["device"]) or next(iter(baselines.values()))
        z = [(r[m] - b[m]["median"]) / b[m]["mad"] for m in METRICS]
        rows.append(z + [0.0 if r.get("link_up", 1) >= 0.5 else 10.0])
    return np.clip(np.array(rows, dtype=float), -50, 50)


class AnomalyModel:
    def __init__(self):
        self.iforest = None
        self.baselines = {}

    # ---------------- training ----------------
    def train(self, df: pd.DataFrame, contamination: float = 0.015):
        self.baselines = compute_baselines(df)
        X = zfeatures(df, self.baselines)
        self.iforest = IsolationForest(n_estimators=200, contamination=contamination, random_state=42)
        self.iforest.fit(X)
        return self

    def save(self):
        joblib.dump({"iforest": self.iforest, "baselines": self.baselines}, MODEL_PATH)

    @classmethod
    def load(cls):
        m = cls()
        if MODEL_PATH.exists():
            obj = joblib.load(MODEL_PATH)
            m.iforest, m.baselines = obj["iforest"], obj["baselines"]
        return m

    # ---------------- inference ----------------
    def score(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adds columns: if_flag, z_flag, anomaly, anomaly_score, top_metrics, pattern."""
        df = df.copy().reset_index(drop=True)
        if df.empty:
            return df
        X = zfeatures(df, self.baselines)
        if_raw = -self.iforest.decision_function(X)                 # higher = more anomalous
        if_flag = self.iforest.predict(X) == -1
        zmax = np.abs(X[:, :len(METRICS)]).max(axis=1)
        z_flag = (zmax > Z_THRESHOLD) | (X[:, -1] > 0)
        df["if_flag"], df["z_flag"] = if_flag, z_flag
        df["anomaly"] = if_flag | z_flag
        df["anomaly_score"] = np.clip(0.5 + if_raw * 2, 0, 1).round(3)
        df.loc[df["anomaly"], "anomaly_score"] = np.maximum(df.loc[df["anomaly"], "anomaly_score"], 0.6)
        tops, pats = [], []
        for i in range(len(df)):
            z = dict(zip(METRICS, X[i, :len(METRICS)]))
            top = sorted(((m, round(float(v), 1)) for m, v in z.items() if abs(v) > 3), key=lambda t: -abs(t[1]))[:4]
            tops.append(top)
            pats.append(classify_pattern(z, X[i, -1] > 0, df.loc[i, "utilization_pct"]) if df.loc[i, "anomaly"] else "normal")
        df["top_metrics"], df["pattern"] = tops, pats
        return df


def classify_pattern(z: dict, link_down: bool, utilization: float = 0.0) -> str:
    """Rule-based pattern label used as EVIDENCE (not as a final root cause).
    Utilization >= 90 % is treated as high in absolute terms (a link near capacity)."""
    high = {m for m, v in z.items() if v > 3}
    if utilization >= 90:
        high.add("utilization_pct")
    if link_down:
        return "link_down"
    if len(high) == 1 and max(z.values()) > 20:
        return "possible_telemetry_issue"        # one impossible metric, everything else normal
    if "utilization_pct" in high and ({"latency_ms", "packet_loss_pct", "jitter_ms"} & high):
        return "congestion"
    if "cpu_pct" in high:
        return "cpu_overload"
    if "interface_errors" in high:
        return "interface_degradation"
    if {"latency_ms", "packet_loss_pct", "jitter_ms"} & high:
        return "performance_degradation"
    return "unusual_metric_combination"


def evaluate(model: AnomalyModel, df: pd.DataFrame) -> dict:
    """Compares IF-only, z-score-only and the hybrid against the synthetic ground-truth labels."""
    s = model.score(df)
    y = df["label"].values
    out = {}
    for name, pred in [("isolation_forest", s["if_flag"]), ("zscore_threshold", s["z_flag"]), ("hybrid", s["anomaly"])]:
        out[name] = {"precision": round(precision_score(y, pred, zero_division=0), 3),
                     "recall": round(recall_score(y, pred, zero_division=0), 3),
                     "f1": round(f1_score(y, pred, zero_division=0), 3),
                     "confusion_matrix": confusion_matrix(y, pred).tolist()}
    per_kind = {}
    for kind, g in s.assign(kind=df["anomaly_kind"].values).groupby("kind"):
        if kind != "normal":
            per_kind[kind] = round(float(g["anomaly"].mean()), 3)
    out["recall_per_anomaly_type"] = per_kind
    out["dataset"] = {"rows": int(len(df)), "devices": int(df.device.nunique()), "labelled_anomalies": int(y.sum())}
    return out


def train_and_evaluate() -> dict:
    df = pd.read_csv(DATA_DIR / "telemetry_history.csv", parse_dates=["timestamp"])
    model = AnomalyModel().train(df)
    model.save()
    metrics = evaluate(model, df)
    metrics["method"] = "Per-device robust z-score features + Isolation Forest (200 trees, contamination=0.015) OR |z|>6 threshold"
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    print(json.dumps(train_and_evaluate(), indent=2))
