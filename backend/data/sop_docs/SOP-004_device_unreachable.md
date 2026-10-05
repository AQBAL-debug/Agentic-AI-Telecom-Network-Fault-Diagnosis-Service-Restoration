# SOP-004 Network Element Unreachable / Device Failure
<!-- Approved procedure for node_unreachable, device_restart, power_failure, hardware failures. -->

## Scope
Applies to node_unreachable, device_restart, power_failure, linecard_failure and psu_failure alarms.

## Initial Diagnostics
1. Check whether the device is reachable through the out-of-band management network.
2. Check for power alarms at the site and on the device power supplies.
3. Review syslog for crash dumps, watchdog resets or hardware errors before the event.
4. Check uptime after recovery to confirm whether a restart occurred.

## Restoration
1. (Diagnostic) Collect logs and crash information once reachable.
2. (Potentially disruptive - approval required) Remote power cycle through intelligent PDU.
3. (Potentially disruptive - approval required) Switch over to redundant routing engine.
4. (Escalation) Open vendor TAC case for hardware or software crash; dispatch field engineer for hardware replacement.

## Verification
Device reachable, all interfaces in expected state, downstream services restored.
