# Feeder Monitor (demo)

A role-based outage console built on this project's results. Pick a role and work a simulated
fault from Sw1 lockout to normal configuration:

| Role | Sees | Can do |
|---|---|---|
| Dispatcher | Lockout alarm, ML zone with confidence, switching sequence | Confirm zone, execute switching, dispatch crew, re-energize |
| Field Crew | Assigned zone, isolation points, buses | Six-step safety checklist (clearance, tags, test, grounds, patrol, repair) |
| Engineer | All 10 devices' event records, ML vs fault indicators, power-flow checks | Approve the zone when ML confidence is below 0.90 |
| Manager | Load out, incident status, kW-minutes vs manual | Read-only |

A fifth card, **Technical Reader**, is not a role in the demo: it opens the paper-style
[technical study](../study/) (method, validation, error analysis, limits).

The 40 incidents are faults from the OpenDSS sweep (4 per zone). Their ML predictions come from
a model trained **without** the incident buses, so they are unseen-bus predictions (38 of 40
correct; fault indicators 19 of 40). Sign-in has no password and nothing here controls real
equipment.

Static site: `index.html` + `data.json`. Rebuild the data with

```
.venv\Scripts\python scripts\export_control_room.py
```

Live with the report page on GitHub Pages:
https://chau1912550.github.io/self-healing-feeder/monitor/

Run locally: `python -m http.server 5173 --directory docs/monitor`, then open http://localhost:5173.
