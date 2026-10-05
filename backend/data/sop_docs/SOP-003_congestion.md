# SOP-003 Link Congestion and Performance Degradation
<!-- Approved procedure for high utilization, latency, jitter and packet loss. -->

## Scope
Applies to high_utilization, high_latency, packet_loss and jitter threshold anomalies.

## Initial Diagnostics
1. Do not assume high utilization is the root cause. Correlate with interface errors, routing changes and link failures elsewhere.
2. Check whether traffic shifted from another failed link (look for interface_down alarms on parallel paths).
3. Check routing tables for recent route changes or BGP/OSPF neighbor events.
4. Check device CPU and memory for degradation of the network element itself.
5. Validate the telemetry source: compare probe data with interface counters to exclude a sensor problem.

## Restoration
1. (Non-disruptive) Apply traffic engineering to move load onto underutilized paths.
2. (Non-disruptive) Apply QoS prioritisation for critical services.
3. (Potentially disruptive - approval required) Change routing metrics.
4. (Escalation) Raise capacity-planning ticket if congestion is recurring.

## Verification
Utilization below 80%, latency and packet loss back within baseline thresholds.
