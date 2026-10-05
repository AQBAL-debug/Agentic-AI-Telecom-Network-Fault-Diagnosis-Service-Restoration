# SOP-005 Configuration-Related Incidents and Rollback
<!-- Approved procedure for faults following a configuration change. -->

## Scope
Applies when an incident starts within 30 minutes after a configuration commit on an affected device.

## Initial Diagnostics
1. Retrieve the change record and the configuration diff.
2. Compare the running configuration with the last known good configuration.
3. Confirm the timing between the commit and the first alarm.

## Restoration
1. (Diagnostic) Review the configuration diff with the change owner.
2. (Potentially disruptive - approval required by NOC lead and change owner) Roll back to the last known good configuration.
3. (Escalation) Escalate to network engineering if rollback is not possible.

## Verification
Services restored, no new alarms for 30 minutes, change record updated with outcome.
