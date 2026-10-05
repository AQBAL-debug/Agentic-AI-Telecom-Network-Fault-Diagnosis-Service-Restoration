# SOP-002 Base Station Backhaul Loss
<!-- Approved procedure for base station transport loss. -->

## Scope
Applies to backhaul_lost, s1_link_down and service_unavailable alarms raised by base stations (eNodeB / gNodeB).

## Initial Diagnostics
1. Check whether other base stations behind the same aggregation router or switch also lost backhaul.
2. If several sites lost backhaul at the same time, treat the shared upstream device as the primary fault candidate and do not open separate tickets per site.
3. Verify the status of the base station's upstream port on the aggregation router.
4. Check site power and environmental alarms.

## Restoration
1. (Diagnostic) Ping and traceroute from the aggregation router to the base station management address.
2. (Non-disruptive) If the site is dual-homed, confirm traffic switched to the backup microwave/fiber path.
3. (Potentially disruptive - approval required) Remote reset of the base station transport card.
4. (Escalation) Dispatch field team for site visit when power or physical damage is suspected.

## Verification
Backhaul alarm cleared, cell service available, KPI (latency, packet loss) at baseline for 15 minutes.
