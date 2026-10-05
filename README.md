# Agentic AI Telecom Network Fault Diagnosis & Service Restoration System
<!-- README.md - project documentation required by the assignment. -->

A **Network Operations Center (NOC) decision-support platform**. Eight specialized AI agents, orchestrated with
LangGraph, ingest alarms and telemetry, correlate alarms, localize faults on the network topology, detect anomalies,
analyze service impact, generate evidence-based root-cause hypotheses, retrieve approved procedures (RAG) and
recommend restoration actions. **A NOC engineer approves every action. The system never modifies network devices.**

- Live frontend: `<your Vercel URL>` - Live backend: `<your Render URL>` (API docs at `/docs`)
- Architecture diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Demo script: [docs/DEMO.md](docs/DEMO.md) - Test results: [docs/TEST_CASES.md](docs/TEST_CASES.md)

## 1. Problem statement and telecom use case
One fault (for example an aggregation-router uplink failure) produces many alarms on many devices: interface down
on the router, backhaul lost and service unavailable on every base station behind it. Engineers must find which alarm
is the cause, which services and customers are hit, where the fault is, why it happened and how to restore service
safely. This system automates the analysis and keeps the human in control of every decision.

Example from the brief (scenario `ar01_uplink_failure`): 7 alarms (AR-01 interface down, BS-101/BS-102 backhaul lost
and service unavailable, ENT-GW-101 link down, one duplicate) become **1 incident**, primary AR-01, confidence high,
3 services unavailable, similar past incident INC-NET-032 retrieved, physical uplink failure suspected.

## 2. System architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams. Flow:

`Devices/telemetry/alarms -> Intake (normalize) -> Correlation -> Performance/anomaly -> Topology fault localization
-> Service impact -> RCA (history + RAG) -> Restoration planning -> Critic review -> Human approval -> Action tracking
-> Post-restoration validation -> Close / escalate`

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI + Pydantic | async, typed, auto OpenAPI docs |
| Orchestration | LangGraph `StateGraph` | explicit shared state, conditional edges (critic loop), inspectable |
| LLM | OpenRouter (`nvidia/nemotron-3-ultra-550b-a55b:free`, configurable) | free; any OpenAI-compatible model works |
| Topology | NetworkX (graph rebuilt from PostgreSQL) | ancestors, reachability, failure simulation in memory |
| ML | scikit-learn Isolation Forest + robust z-scores | unsupervised, explainable, CPU-only |
| RAG | TF-IDF vectors + cosine similarity over sectioned SOPs | zero cost, deterministic, runs on free tier |
| Database | PostgreSQL (SQLite fallback for quick local runs) | single store for inventory, alarms, telemetry, incidents, traces |
| Frontend | React 18 + TypeScript + Tailwind + Recharts + React Flow | interactive topology and charts |
| Reports | ReportLab | PDF incident report |
| Deploy | Render (backend + Postgres) / Vercel (frontend) | free tiers |

## 3. Multi-agent architecture

| # | Agent (file) | Responsibility | Tools it calls |
|---|---|---|---|
| 1 | Telemetry & Alarm Intake (`intake_agent.py`) | formats, timestamp validation, duplicates, missing info, device state | `update_device_state` |
| 2 | Alarm Correlation (`correlation_agent.py`) | primary / consequential / duplicate / independent, storm summary, timeline | `correlate_alarms` |
| 3 | Topology & Fault Localization (`topology_agent.py`) | ranked device and link hypotheses with evidence and alternatives | `topology.localize` |
| 4 | Performance & Anomaly Detection (`performance_agent.py`) | anomaly scores, before vs after, 5-question investigation | `get_telemetry`, `anomaly_model.score` |
| 5 | Service Impact (`impact_agent.py`) | unavailable vs degraded services, redundancy, known customers | `impact.analyze` |
| 6 | Root Cause Analysis (`rca_agent.py`) | hypotheses with supporting/contradicting evidence, verification | `get_device_logs`, `get_change_and_maintenance_history`, `similar_incidents`, `search_procedures(RAG)`, LLM |
| 7 | Restoration & Action Planning (`restoration_agent.py`) | SOP-backed plan, action classes, validation after restoration | `search_procedures(RAG)`, LLM |
| 8 | Reviewer / Critic (`critic_agent.py`) | checks consistency, evidence, invented numbers, approval flags; requests rework | LLM |

**Agent prompts:** all system prompts are in `backend/app/agents/prompts.py` and shown on the Agent Execution page.
Each prompt forbids inventing data and forbids calling a root cause confirmed.

**Agent-to-agent communication and shared workflow state:** `NOCState` (TypedDict) in `agents/graph.py`. Every agent
reads previous keys and writes its own; `BaseAgent.send()` appends explicit messages (`from`, `to`, `content`) to
`state["messages"]`. The critic routes back to the restoration agent (`needs_rework`, max one loop) or ends the graph.
Every input, tool call, LLM call, message, output, review and human decision is stored in `agent_logs`.

**Deterministic tools + LLM design:** agents compute facts with tools; the LLM re-weighs hypotheses (bounded to
+/-0.2 of the rule score, capped at 0.9), writes summaries/briefings and may suggest at most 2 extra actions which the
critic re-classifies. Evidence lists never come from the LLM. If the LLM is unavailable or rate-limited, each agent
uses its rule-based output, so the system always works.

## 4. Data model
Tables (`backend/app/models.py`): `devices` (inventory), `links` (topology edges, `is_backup` marks redundancy),
`services` (`depends_on` device list, `customers` nullable = unknown), `alarms` (normalized fields + original `raw`
payload, `role`, `incident_id`, never deleted), `telemetry` (time series), `incidents` (one JSON column per agent
result + timeline, comments, notifications, revision), `actions` (approval and tracking fields), `agent_logs`,
`historical_incidents`, `changes` (configuration / maintenance history).

**Network inventory model:** id, name, type, layer, region, IP, vendor, model, status, interfaces, services; connected
devices derive from `links`. **Topology representation:** directed graph upstream -> downstream (core to access);
roots are devices with no upstream; dual-homed devices (BS-303, AR-02) have backup links.

## 5. Alarm ingestion pipeline
`POST /api/alarms/ingest` accepts a list of raw events in three formats (`engines/normalizer.py`):
SNMP traps (IF-MIB linkDown/linkUp/coldStart OIDs), syslog lines (regex for `%LINK-3-UPDOWN`, BGP, CPU, restart,
power) and vendor JSON (synonym table maps "Backhaul Connectivity Lost" -> `backhaul_lost` etc.). Validation reports
missing device, unknown device, missing/future timestamps and unknown alarm types without dropping the event.
`interface_up` events clear matching alarms. Analysis runs in a FastAPI background task (event-driven).

## 6. Alarm correlation methodology
`engines/correlation.py`: (1) duplicates = same device + type + interface within 5x window; (2) union-find over
time-sorted alarms joins two alarms when they are within 120 s **and** topologically related (same device,
upstream/downstream, or share a nearby non-core parent); (3) primary = alarm on the device that is upstream of the most
other alarmed devices, tie-broken by type priority (power > restart > interface down > ... > service unavailable) and
time; (4) single unrelated alarm = independent incident; (5) new groups related to an incident active in the last 30
min join it and trigger reassessment. Engineers can confirm or reject the correlation.

**Alarm-storm handling:** groups of 50+ alarms are flagged as storms and summarized by device and type; the Alarm
Console's cluster view shows one card per incident instead of a flat list; originals stay in `alarms`. Complexity is
kept low with time-sorted early break and cached topology relations (206 alarms analyzed in well under a second).

## 7. Telemetry pipeline and anomaly-detection model
`POST /api/telemetry/ingest` stores metrics, scores them, and raises `performance_anomaly` alarms automatically, so the
model is part of the operational workflow (scenario `congestion` has no device alarms at all).

- **Dataset:** `data/generate_data.py` - 18 devices x 24 h x 5 min = 5,184 rows, device-type baselines with a day/night
  utilization curve, plus 70 labelled anomalies of 5 kinds: congestion, gradual degradation, CPU spike, link down,
  telemetry glitch (impossible value).
- **Features:** robust z-score of latency, loss, jitter, utilization, CPU, memory, interface errors, throughput against
  each device's own median/MAD, plus link-down flag.
- **Algorithm:** Isolation Forest (200 trees, contamination 0.015) on z-features OR |z| > 6 / link down. A rule layer
  labels the pattern (congestion, link_down, cpu_overload, interface_degradation, possible_telemetry_issue ...) as evidence.
- **Training:** unsupervised; labels are used only for evaluation. `python -m app.engines.anomaly`.
- **Results** (`models/anomaly_metrics.json`): Isolation Forest P 0.82 / R 0.91 / F1 0.87; z-score P 1.00 / R 0.97 /
  F1 0.99; hybrid P 0.83 / R 0.99 / F1 0.90; recall 1.0 for congestion, CPU, link down, glitch and 0.97 for gradual
  degradation. Honest note: the synthetic anomalies are pronounced, so the z-score layer is very strong here; Isolation
  Forest adds coverage for multi-metric combinations. Hybrid is used to favour recall in a NOC.
- **Why not LSTM/autoencoder:** needs much more data, harder to explain to engineers, heavier to deploy.
- **Investigation:** the performance agent answers congestion? traffic shift? element degraded? routing change?
  telemetry problem? and never concludes utilization is the root cause on its own.

## 8. Fault-localization methodology
`engines/topology.py::localize` scores every candidate device (alarmed devices and their non-root ancestors) and every
non-backup uplink: `0.5*coverage + 0.25*precision + bonuses`. Coverage = share of alarmed devices a single failure
there explains (using `isolated_if_failed`, which respects redundancy); precision penalizes candidates that would also
isolate or force onto backup healthy devices; bonuses for own alarm, earliest alarm and alarms on the exact link
interfaces. Output: suspected device/link, supporting alarms, topology evidence (incl. healthy peers), telemetry
evidence, contradicting evidence, confidence (high needs score >= 0.8 and margin >= 0.08) and alternatives.

## 9. Service-impact methodology
`engines/impact.py`: failed elements -> isolated devices (no path to core) and degraded devices (lost a path, on
backup). A service is unavailable if a dependency is down/isolated, degraded if a dependency runs on redundancy.
Customer totals sum only known counts; unknown ones are listed as unknown.

## 10. Network RAG and historical incident retrieval
`engines/rag.py`: 8 documents in `data/sop_docs/` (SOPs, escalation policy, device manual) split by `##` section;
TF-IDF (1-2 grams) + cosine. `POST /api/kb/ask` retrieves top sections and the LLM answers only from them with
`[SOP-xxx / section]` citations (falls back to returning the best section). Historical incidents use TF-IDF over
title + alarm pattern + device type + category plus a structural bonus (same device type, similar downstream count);
the result is labelled "evidence only".

## 11. Root Cause Analysis methodology
`agents/rca_agent.py` gathers logs, change/maintenance history (recent change within 2 h strongly supports
configuration; older changes count against it), similar incidents and SOPs, then builds hypotheses for physical link,
interface hardware, configuration, maintenance, upstream, power/restart, congestion, software/CPU, routing and
telemetry issues, each with supporting and contradicting evidence and required verification. All stay **suspected**;
`POST /incidents/{id}/root-cause` records the engineer-**confirmed** cause.

## 12. Restoration planning, human approval and validation
Playbooks per cause, enriched with retrieved SOP references, ordered diagnostic -> non-disruptive -> potentially
disruptive -> escalation; redundancy checks added when backup paths exist. A keyword safety net forces reset /
restart / rollback / replace / shut actions into `potentially_disruptive` with `requires_approval`. Engineers can
approve, reject, modify (re-classified), comment and escalate. The API refuses to start an unapproved disruptive
action. Statuses: proposed -> approved -> in_progress -> completed -> verified.
**Post-restoration validation** compares baseline, during-incident and after-restoration latency, loss, jitter,
utilization, link state, alarm clearance and service status; pass -> resolved (actions verified), fail -> escalated.
An incident can only be closed after validation passes.

**Dynamic reassessment:** a new related alarm joins the active incident, all agents re-run, the revision increments,
and material changes (fault location, impact, top cause) are shown as a notification. Approved actions are kept.

## 13. API documentation
Full interactive docs at `<backend>/docs`. Main endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET/POST/PUT/DELETE | `/api/devices` | inventory |
| GET/POST/DELETE | `/api/links`, GET `/api/services` | links, services |
| GET | `/api/topology`, `/api/topology/node/{id}` | topology graph, node details |
| POST | `/api/alarms/ingest` | ingest raw events (`?sync=true` runs agents inline) |
| GET | `/api/alarms`, `/api/alarms/clusters`, `/api/alarms/{id}/raw` | console, storm view, audit |
| POST/GET | `/api/telemetry/ingest`, `/api/telemetry/{device}` | metrics in, scored series out |
| GET | `/api/anomalies`, `/api/model/metrics` | active anomalies, model evaluation |
| GET | `/api/incidents`, `/api/incidents/{id}`, `/api/incidents/{id}/agent-logs` | incidents, trace |
| POST | `/api/incidents/{id}/reanalyze \| correlation \| comment \| escalate \| validate \| root-cause \| close` | engineer actions |
| GET | `/api/incidents/{id}/report.pdf` | PDF report |
| GET/POST | `/api/actions`, `/api/actions/{id}/decision`, `/api/actions/{id}/status` | approvals, tracking |
| GET/POST | `/api/kb/search`, `/api/kb/ask`, `/api/kb/documents`, `/api/historical[/similar]` | knowledge |
| GET/POST | `/api/simulate/scenarios`, `/api/simulate/{scenario}`, `/api/simulate/restore/{id}`, `/api/reset` | simulator |
| GET | `/api/dashboard`, `/api/agents` | dashboard, agent prompts |

## 14. Environment variables
Backend (`backend/.env`, see `.env.example`): `DATABASE_URL`, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `LLM_ENABLED`,
`CORS_ORIGINS`. Frontend (`frontend/.env.local`): `VITE_API_URL`.

## 15. Setup and local execution
Prerequisites: Python 3.11+ (3.12 tested), Node 18+ (22 tested), PostgreSQL 14+.

```bash
# database (psql as the postgres user)
CREATE DATABASE noc_ai;

# backend
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # edit DATABASE_URL password + OPENROUTER_API_KEY
python data/generate_data.py                           # synthetic dataset (already included)
python -m app.engines.anomaly                          # train + evaluate the model
uvicorn app.main:app --reload --port 8000              # tables + seed data created on first start

# frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local                             # VITE_API_URL=http://localhost:8000
npm run dev                                            # http://localhost:5173
```

## 16. Testing methodology
`cd backend && pytest -v` runs 10 automated tests (TC-01 ... TC-08, RAG, normalizer) through the real API with the
LLM disabled for deterministic results; verified on SQLite and PostgreSQL 16. `python tests/generate_test_report.py`
regenerates [docs/TEST_CASES.md](docs/TEST_CASES.md) with input, initial state, expected and actual output, agents,
tool output, evidence, final state and pass/fail for each case.

## 17. Deployment
- **Backend (Render):** push to GitHub -> Render -> New -> Blueprint -> select repo (`render.yaml` creates the web
  service and a free PostgreSQL). Set `OPENROUTER_API_KEY` in the dashboard.
- **Frontend (Vercel):** New project -> root directory `frontend` -> framework Vite -> env `VITE_API_URL=<Render URL>`.
- Optionally restrict `CORS_ORIGINS` to the Vercel URL.

## 18. Repository layout
```
backend/  app/ (main, config, db, models, schemas, llm, report, seed)
          app/agents/ (8 agents, prompts, LangGraph graph)   app/engines/ (normalizer, correlation, topology, anomaly, impact, rag)
          app/services/ (incident workflow, toolbox, simulator)   app/routers/ (REST API)
          data/ (generator, topology.json, services.json, historical_incidents.json, telemetry_history.csv, sop_docs/)
          tests/ (pytest suite, test report generator)
frontend/ src/ (api, hooks, components, 16 pages)
docs/     ARCHITECTURE.md, DEMO.md, TEST_CASES.md
```

## 19. Limitations and next steps
Synthetic data only; TF-IDF retrieval could be upgraded to embeddings + pgvector behind the same interface; the
simulator stands in for real SNMP/syslog collectors; free LLM endpoints log prompts (only synthetic data is sent).
