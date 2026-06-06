"""SentinelAI live-flow sensor.

A *log-tailing* sensor — it reads flow records that Zeek/Suricata already wrote
(or replays a flow log for demos) and posts them to the SentinelAI backend. It
never binds a NIC, never captures raw packets, and never stores payloads. It is
disabled by default and only runs against explicitly authorized lab subnets.

For authorized lab networks only. See docs/LIVE_SENSOR.md.
"""

__version__ = "0.1.0"
