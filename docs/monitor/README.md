# Feeder Monitor (demo)

A role-based outage console built on this project's results. Pick a role and work a simulated
fault from Sw1 lockout to normal configuration, or run the one-click two-tier HIF → FLISR demo:

| Role | Sees | Can do |
|---|---|---|
| Dispatcher | Lockout alarm, ML zone with confidence, switching sequence | Confirm zone, execute switching, dispatch crew, re-energize |
| Field Crew | Assigned zone, isolation points, buses | Six-step safety checklist (clearance, tags, test, grounds, patrol, repair) |
| Engineer | All 10 devices' event records, ML vs fault indicators, power-flow checks | Approve the zone when ML confidence is below 0.90 |
| Manager | Load out, incident status, kW-minutes vs manual | Read-only |

A fifth card, **Technical Reader**, is not a role in the demo: it opens the paper-style
[technical study](../study/) (method, validation, error analysis, limits).

## 10s Two-Tier Demo, Live Wokwi MQTT & Reversed Tie Flow

- **One-click `10s Two-Tier Demo (HIF Arc → ESP32 → FLISR)`:** plays the full two-tier lifecycle in 10 seconds directly in the browser (works completely offline, no broker or backend needed):
  1. **0–2.5 s (Tier 1 Edge HIF):** displays the 15.36 kHz arcing waveform and verified C99 `504 B` `int8` Tiny MLP output (`417` parameters, `PERSIST = 3`, GCC `13.3.0` verified parity `max |p_c - p_py| = 4.77×10⁻⁷`, host latency `0.540 µs/inf` from [`hif_sensor/results/c_firmware_verify.json`](../../hif_sensor/results/c_firmware_verify.json)) paired with a high-impedance (`R >= 100 Ω`) incident from `data.json`.
  2. **2.5–4.5 s (Lockout & Location):** feeder-head recloser `Sw1` locks out and Tier-2 FLISR locates the faulted zone.
  3. **4.5–6.5 s (Isolation):** sectionalizing switches open to isolate the faulted zone.
  4. **6.5–10 s (Restoration & Reversed Flow):** `Sw1` re-closes to feed upstream zones and the planned tie (`Sw7` or `Sw9`) closes to back-feed healthy downstream zones with animated reversed power flow.
- **Live Wokwi MQTT listener (`wss://broker.hivemq.com:8884/mqtt`):** toggle **Live Wokwi MQTT** to listen directly to the simulated ESP32 panel ([`board/README.md`](../../board/README.md)) and `scripts/panel_bridge.py` using a self-contained pure-JS MQTT 3.1.1-over-WSS client (no external CDN dependency). It subscribes to `shf/shf123-demo/hif` (Tier-1 C99 HIF alerts) and `shf/shf123-demo/state` (Tier-2 FLISR frames including `flow` and `hif` metadata).
- **Directional & reversed back-feed flow animation:** the SVG feeder map computes BFS power flow from Substation `150` along energized lines during normal feed; when a tie switch (`Sw7` or `Sw9`) closes to restore a downstream island (`restored_by_tie`), it computes reversed BFS flow from the tie and highlights animated pulses/arrows with a **Reversed back-feed via tie** legend (respecting `prefers-reduced-motion`).

> **Simulation only:** Wokwi is a browser ESP32 simulator connecting through a public demo MQTT broker (`broker.hivemq.com`) for interactive demonstration. Nothing here controls energized field hardware or connects to a live utility SCADA system.

## Data & Running Locally

The 40 incidents are faults from the OpenDSS sweep (4 per zone). Their ML predictions come from
a model trained **without** the incident buses, so they are unseen-bus predictions (35 of 40
correct; fault indicators 19 of 40). Sign-in has no password and nothing here controls real
equipment.

Static site: `index.html` + `data.json`. Rebuild the data with

```
.venv\Scripts\python scripts\export_control_room.py
```

Live with the report page on GitHub Pages:
https://chau1912550.github.io/self-healing-feeder/monitor/

Run locally: `python -m http.server 5173 --directory docs/monitor`, then open http://localhost:5173.
