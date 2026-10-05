# SOP-001 Interface Down Troubleshooting
<!-- Approved network-operations procedure. Indexed by the RAG engine (app/engines/rag.py). -->

## Scope
Applies to alarms of type interface_down, link_down or port_down on routers and switches (core, aggregation, access).

## Initial Diagnostics (Diagnostic - no approval needed)
1. Verify current interface operational and administrative state from the monitoring system.
2. Review interface error counters (CRC, input errors, output drops) for the last 60 minutes.
3. Check optical receive/transmit power levels (DOM) if the port is optical.
4. Confirm whether the remote end of the link also reports the interface down.
5. Check recent configuration changes on the device in the change-management log.

## Fault Isolation
- If both ends report down and optical power is absent, suspect a physical fiber failure.
- If only one end reports down and errors rose before the failure, suspect SFP or interface hardware.
- If the interface went down immediately after a configuration commit, suspect configuration.

## Restoration
1. (Non-disruptive) Shift traffic to redundant path if available.
2. (Potentially disruptive - requires NOC approval) Administrative shut/no-shut of the interface.
3. (Potentially disruptive - requires approval) Replace SFP module under an approved MOP.
4. (Escalation) Dispatch field engineering if physical fiber damage is suspected.

## Verification
Confirm interface state up, error counters stable, downstream alarms cleared and latency/packet loss back to baseline.
