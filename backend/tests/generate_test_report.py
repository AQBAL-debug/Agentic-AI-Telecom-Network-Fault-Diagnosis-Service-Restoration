"""
tests/generate_test_report.py
-----------------------------
WHAT IT DOES:
    Runs the 8 required test scenarios against the real API (in-process) and writes
    docs/TEST_CASES.md with, for every test case: input, initial network state,
    expected output, ACTUAL output, agents involved, model/tool output, supporting
    evidence, final network state and PASS/FAIL.
    Run:  cd backend && python tests/generate_test_report.py
"""
import os, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_ENABLED", "false")
from fastapi.testclient import TestClient
from app.main import app

OUT = Path(__file__).resolve().parent.parent.parent / "docs" / "TEST_CASES.md"
AGENTS = "Intake, Correlation, Performance, Topology/Fault Localization, Impact, RCA, Restoration, Critic"


def state(c):
    d = c.get("/api/dashboard").json()
    return f"health {d['network_health_pct']}%, devices {d['device_status']}, active alarms {d['active_alarms']}, active incidents {d['correlated_incidents']}"


def sim(c, name):
    return c.post(f"/api/simulate/{name}?sync=true").json()


def inc(c, iid):
    return c.get(f"/api/incidents/{iid}").json()


def main():
    rows = []
    with TestClient(app) as c:
        def case(tc, title, scenario, expected, check):
            c.post("/api/reset")
            pre = None
            if tc == "TC-08":
                sim(c, "ar01_uplink_failure")
            if tc == "TC-07":
                pre = sim(c, "ar01_uplink_failure")
            initial = state(c)
            r = pre if tc == "TC-07" else sim(c, scenario)
            actual, tool, evidence, ok = check(c, r)
            rows.append(dict(tc=tc, title=title, input=scenario, initial=initial, expected=expected, actual=actual,
                             tool=tool, evidence=evidence, final=state(c), ok=ok))

        def tc01(c, r):
            i = inc(c, r["incidents_created"][0])
            p = i["correlation"]["primary"]
            return (f"Incident {i['id']} created; primary {p['device']} {p['type']}; status {i['status']}",
                    "normalizer: SNMP linkDown trap -> interface_down", i["correlation"]["reasoning"],
                    len(r["incidents_created"]) == 1 and p["device"] == "ENT-GW-201")
        case("TC-01", "Single device interface-down alarm", "single_interface_down", "One network incident created", tc01)

        def tc02(c, r):
            i = inc(c, r["incidents_created"][0])
            cons = sorted({a["device"] for a in i["correlation"]["consequential"]})
            return (f"{r['events_sent']} alarms -> 1 incident {i['id']}; primary {i['correlation']['primary']['device']}; consequential {cons}; duplicates {i['correlation']['duplicate_count']}",
                    "correlate_alarms (time window 120 s + topology)", i["correlation"]["reasoning"],
                    len(r["incidents_created"]) == 1 and i["correlation"]["primary"]["device"] == "AR-01")
        case("TC-02", "Downstream failures after upstream alarm", "ar01_uplink_failure", "Related alarms correlated into one incident", tc02)

        def tc03(c, r):
            ii = [inc(c, x) for x in r["incidents_created"]]
            big = max(ii, key=lambda x: len(x["alarms"]))
            small = min(ii, key=lambda x: len(x["alarms"]))
            return (f"{r['events_sent']} alarms -> {len(ii)} incidents: storm {big['id']} ({len(big['alarms'])} alarms, fault {big['fault_localization']['primary']['location']}) + independent {small['id']} ({small['correlation']['primary']['device']} {small['correlation']['primary']['type']})",
                    f"storm summary: {json.dumps(big['correlation']['storm_summary'].get('by_type', {}))}", big["correlation"]["reasoning"],
                    len(ii) == 2 and big["correlation"]["storm"])
        case("TC-03", "Large alarm storm", "alarm_storm", "Events grouped into meaningful incidents", tc03)

        def tc04(c, r):
            i = inc(c, r["incidents_created"][0])
            an = i["performance"]["anomalies"]
            return (f"Anomaly model raised incident {i['id']}: {i['performance']['summary']}",
                    f"anomaly_model.score -> {[(a['device'], a['pattern'], a['max_score'], a['detected_by']) for a in an][:3]}",
                    [f"{x['check']}: {x['result']}" for x in i["performance"]["investigation"]],
                    any(a["pattern"] == "congestion" for a in an))
        case("TC-04", "Latency and packet loss increase", "congestion", "Performance anomaly detected", tc04)

        def tc05(c, r):
            i = inc(c, r["incidents_created"][0])
            t = i["fault_localization"]["primary"]
            return (f"{i['fault_localization']['headline']}; alternatives {[h['location'] for h in i['fault_localization']['alternatives']]}; impact: {i['service_impact']['summary']}",
                    f"topology.localize score {t['score']}", t["evidence"], t["location"] == "AR-01")
        case("TC-05", "Common upstream dependency", "ar01_uplink_failure", "Likely fault domain identified", tc05)

        def tc06(c, r):
            i = inc(c, r["incidents_created"][0])
            h = i["historical"]
            return (f"Retrieved {[x['id'] + ' (' + str(x['similarity']) + ')' for x in h]}", "similar_incidents (TF-IDF + structural bonus)",
                    [x["title"] + " -> " + x["root_cause"] for x in h], "INC-NET-032" in [x["id"] for x in h])
        case("TC-06", "Similar historical incident exists", "ar01_uplink_failure", "Relevant incident retrieved (INC-NET-032)", tc06)

        def tc07(c, r):
            iid = r["incidents_created"][0]
            acts = inc(c, iid)["actions"]
            d = next(a for a in acts if a["category"] == "potentially_disruptive")
            blocked = c.post(f"/api/actions/{d['id']}/status", json={"status": "completed"}).status_code
            c.post(f"/api/actions/{d['id']}/decision", json={"decision": "approve", "engineer": "noc.lead"})
            c.post(f"/api/actions/{d['id']}/status", json={"status": "completed", "result": "interface restored"})
            v = c.post(f"/api/simulate/restore/{iid}").json()
            m = v["metrics"][0]
            return (f"Unapproved disruptive action blocked (HTTP {blocked}); after approval + restoration: {v['summary']}",
                    f"verify_restoration: {m['device']} packet loss baseline {m['packet_loss_pct']['baseline']} -> after {m['packet_loss_pct']['after']}",
                    [f"alarms remaining {v['alarm_clearance']['active_alarms_remaining']}", f"services not available {v['service_status']['services_not_available']}"],
                    v["passed"] and blocked == 400)
        case("TC-07", "Restoration action completed", "ar01_uplink_failure + restore", "Post-restoration metrics verified", tc07)

        def tc08(c, r):
            iid = r["incidents_reassessed"][0]
            i = inc(c, iid)
            n = i["notifications"][-1]
            return (f"Alarm joined {iid} (no new incident); revision {i['revision']}; material changes: {n['material_changes']}",
                    f"new top location {i['fault_localization']['primary']['location']} ({i['fault_localization']['primary']['type']})",
                    i["fault_localization"]["primary"]["evidence"][:3], n["material"] and not r["incidents_created"])
        case("TC-08", "New alarm during active incident", "new_alarm_during_incident", "Dynamic reassessment triggered", tc08)

    lines = ["# Test Cases - results", "", "Generated by `backend/tests/generate_test_report.py` (LLM disabled for deterministic output; "
             "the same flow runs with the LLM enabled). Automated assertions: `cd backend && pytest -v`.", "",
             "| Test | Scenario | Result |", "|---|---|---|"]
    lines += [f"| {r['tc']} | {r['title']} | {'PASS' if r['ok'] else 'FAIL'} |" for r in rows]
    for r in rows:
        lines += ["", f"## {r['tc']} - {r['title']}", "",
                  f"- **Input:** simulator scenario `{r['input']}`", f"- **Initial network state:** {r['initial']}",
                  f"- **Expected output:** {r['expected']}", f"- **Actual output:** {r['actual']}",
                  f"- **Agents involved:** {AGENTS}", f"- **Model/tool output:** {r['tool']}",
                  "- **Supporting evidence:**"] + [f"  - {e}" for e in r["evidence"]] + \
                 [f"- **Final network state:** {r['final']}", f"- **Status:** {'PASS' if r['ok'] else 'FAIL'}"]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()
