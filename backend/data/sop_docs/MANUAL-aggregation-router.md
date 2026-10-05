# Aggregation Router Operations Manual (ASR 920 / 7750 / NE40E)
<!-- Device manual extract used as a knowledge-base document. -->

## Role in the Network
Aggregation routers connect access devices (base stations, enterprise gateways, access switches) to the core. A failure of the aggregation router or its uplink isolates every downstream site that has no redundant path.

## Common Alarms
- interface_down: physical or logical port failure.
- high_cpu: control-plane overload, often caused by protocol storms or misconfiguration.
- crc_errors: physical layer degradation, dirty optics or failing SFP.
- bgp_neighbor_down / ospf_neighbor_down: routing adjacency loss.

## Useful Diagnostic Commands (read-only)
1. show interface <name> - operational state and counters.
2. show logging - recent syslog events.
3. show processes cpu sorted - CPU consumers.
4. show inventory / show environment - hardware and power.

## Redundancy
Some aggregation routers have a backup uplink to a second core router. When the backup is active, downstream services remain available but may be degraded during switchover.
