# SOP-007 NOC Escalation and Approval Policy
<!-- Governs who can approve which restoration actions. -->

## Action Classification
- Diagnostic: read-only checks. No approval required.
- Non-disruptive: traffic engineering, QoS changes on redundant paths. NOC Tier-2 approval recommended.
- Potentially disruptive: interface resets, device restarts, configuration changes or rollbacks. Explicit NOC lead approval required before execution.
- Escalation required: field dispatch, vendor TAC, network engineering.

## Escalation Timers
1. Critical incident with customer impact: escalate to Tier-2 within 15 minutes if not diagnosed.
2. Enterprise link outage: notify account team within 30 minutes.
3. Physical fiber failure: dispatch field team immediately after confirmation.

## Closure
An incident may be closed only after post-restoration validation confirms alarms cleared and KPIs returned to baseline. The confirmed root cause must be recorded.
