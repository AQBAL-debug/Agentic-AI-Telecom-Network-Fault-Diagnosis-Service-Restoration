# SOP-006 Telemetry and Sensor Data Validation
<!-- Procedure to rule out false alarms caused by monitoring/probe issues. -->

## Scope
Applies when a performance metric shows an impossible or isolated value (for example latency 9999 ms or 100% loss) while other metrics and services remain normal.

## Diagnostics
1. Cross-check the metric against a second source (interface counters, another probe).
2. Check whether any service or customer impact is reported.
3. Check the collector/probe health and recent probe configuration changes.

## Resolution
1. (Non-disruptive) Mark the data point as suspect and suppress the alert.
2. (Non-disruptive) Reconfigure or restart the probe (monitoring system only, no network impact).

## Verification
Metric returns to plausible range from the probe; no network change needed.
