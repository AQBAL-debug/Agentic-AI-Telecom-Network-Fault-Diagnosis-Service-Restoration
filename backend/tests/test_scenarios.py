"""
tests/test_scenarios.py
-----------------------
WHAT IT DOES:
    Automated versions of the 8 required test cases (TC-01 ... TC-08) + extra checks.
    Each test resets the DB, injects a simulated scenario through the real API with
    ?sync=true (agents run inline), and asserts the expected behaviour.
    LLM is disabled here so results are deterministic (rule-based fallback path).
    Run:   cd backend && pytest -v
"""
import os
os.environ["LLM_ENABLED"] = "false"
os.environ.setdefault("DATABASE_URL", "")          # tests use SQLite unless you export a test Postgres URL
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture()
def c():
    with TestClient(app) as client:
        client.post("/api/reset")
        yield client


def sim(c, name):
    r = c.post(f"/api/simulate/{name}?sync=true")
    assert r.status_code == 200, r.text
    return r.json()


def test_tc01_single_interface_down_creates_incident(c):
    r = sim(c, "single_interface_down")
    assert len(r["incidents_created"]) == 1
    inc = c.get(f"/api/incidents/{r['incidents_created'][0]}").json()
    assert inc["status"] == "awaiting_approval"
    assert inc["correlation"]["primary"]["device"] == "ENT-GW-201"
    assert inc["correlation"]["primary"]["type"] == "interface_down"


def test_tc02_downstream_alarms_correlated(c):
    r = sim(c, "ar01_uplink_failure")
    assert len(r["incidents_created"]) == 1                     # 7 alarms -> ONE incident
    inc = c.get(f"/api/incidents/{r['incidents_created'][0]}").json()
    assert inc["correlation"]["primary"]["device"] == "AR-01"
    conseq = {a["device"] for a in inc["correlation"]["consequential"]}
    assert {"BS-101", "BS-102"} <= conseq
    assert inc["correlation"]["duplicate_count"] >= 1          # duplicate suppressed but kept
    assert any(a["role"] == "duplicate" for a in inc["alarms"])


def test_tc03_alarm_storm_grouped(c):
    r = sim(c, "alarm_storm")
    assert r["events_sent"] > 150
    assert len(r["incidents_created"]) == 2                     # storm cluster + independent BS-201 power alarm
    incs = [c.get(f"/api/incidents/{i}").json() for i in r["incidents_created"]]
    storm = max(incs, key=lambda i: len(i["alarms"]))
    assert storm["correlation"]["storm"] is True
    assert storm["fault_localization"]["primary"]["location"] == "AR-03"
    other = min(incs, key=lambda i: len(i["alarms"]))
    assert other["correlation"]["primary"]["device"] == "BS-201"
    clusters = c.get("/api/alarms/clusters").json()
    assert clusters[0]["total"] > 150


def test_tc04_performance_anomaly_detected(c):
    r = sim(c, "congestion")
    assert r["incidents_created"], "anomaly model should raise an alarm automatically"
    inc = c.get(f"/api/incidents/{r['incidents_created'][0]}").json()
    pats = {a["pattern"] for a in inc["performance"]["anomalies"]}
    assert "congestion" in pats
    checks = {x["check"]: x["result"] for x in inc["performance"]["investigation"]}
    assert checks["Link congestion"] == "supported"
    # must NOT blindly claim utilization as confirmed cause
    assert all(h["status"] == "suspected" for h in inc["rca"]["hypotheses"])


def test_tc05_common_upstream_fault_domain(c):
    r = sim(c, "ar01_uplink_failure")
    inc = c.get(f"/api/incidents/{r['incidents_created'][0]}").json()
    top = inc["fault_localization"]["primary"]
    assert top["location"] == "AR-01"
    assert top["confidence"] == "high"
    assert inc["fault_localization"]["alternatives"]
    imp = inc["service_impact"]
    assert set(imp["affected_base_stations"]) == {"BS-101", "BS-102"}
    assert "E-101" in {s["service_id"] for s in imp["affected_services"]}
    assert "E-101" in imp["services_with_unknown_customers"]     # customers never invented


def test_tc06_similar_historical_incident(c):
    r = sim(c, "ar01_uplink_failure")
    inc = c.get(f"/api/incidents/{r['incidents_created'][0]}").json()
    assert "INC-NET-032" in [h["id"] for h in inc["historical"]]


def test_tc07_restoration_verified(c):
    r = sim(c, "ar01_uplink_failure")
    iid = r["incidents_created"][0]
    inc = c.get(f"/api/incidents/{iid}").json()
    disruptive = [a for a in inc["actions"] if a["category"] == "potentially_disruptive"]
    assert disruptive and all(a["requires_approval"] for a in disruptive)
    # disruptive action cannot run without approval
    assert c.post(f"/api/actions/{disruptive[0]['id']}/status", json={"status": "completed"}).status_code == 400
    c.post(f"/api/actions/{disruptive[0]['id']}/decision", json={"decision": "approve", "engineer": "lead"})
    assert c.post(f"/api/actions/{disruptive[0]['id']}/status", json={"status": "completed", "result": "link restored"}).status_code == 200
    v = c.post(f"/api/simulate/restore/{iid}").json()
    assert v["passed"] is True and v["alarm_clearance"]["pass"]
    c.post(f"/api/incidents/{iid}/root-cause", json={"root_cause": "Fiber cut on CR-01 - AR-01 span"})
    assert c.post(f"/api/incidents/{iid}/close", json={"author": "lead", "text": "fixed"}).status_code == 200
    pdf = c.get(f"/api/incidents/{iid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_tc08_dynamic_reassessment(c):
    r = sim(c, "ar01_uplink_failure")
    iid = r["incidents_created"][0]
    r2 = sim(c, "new_alarm_during_incident")
    assert r2["incidents_reassessed"] == [iid] and not r2["incidents_created"]
    inc = c.get(f"/api/incidents/{iid}").json()
    assert inc["revision"] == 2
    note = inc["notifications"][-1]
    assert note["material"] is True
    assert inc["fault_localization"]["primary"]["type"] == "link"      # now both link ends are down


def test_rag_and_kb(c):
    hits = c.get("/api/kb/search", params={"q": "interface down troubleshooting procedure"}).json()
    assert hits and hits[0]["doc_id"] == "SOP-001"
    ans = c.post("/api/kb/ask", json={"question": "What troubleshooting procedure applies to backhaul lost?"}).json()
    assert ans["sources"]


def test_normalizer_formats(c):
    r = c.post("/api/alarms/ingest?sync=true", json={"events": [
        {"format": "snmp", "agent": "BS-304", "trap_oid": "1.3.6.1.6.3.1.1.5.3", "varbinds": {"ifName": "eth0"}},
        {"format": "json", "device": "NOPE-1", "alarm": "Interface Down"}]}).json()
    assert r["stored"] == 2
    assert any("not in inventory" in " ".join(x["issues"]) for x in r["validation_issues"])
