# Control panel board (ESP32, simulated in Wokwi)

**Tool:** [Wokwi](https://wokwi.com) (browser ESP32 simulator), Arduino code.

**Try it in the browser, nothing to install: [https://wokwi.com/projects/481240462876979201](https://wokwi.com/projects/481240462876979201)**. Press the green Start button. With no study connected, the board waits 15 s and then replays incidents recorded from the study (demo mode): press FAULT, then CLOSE TIES when a tie lamp blinks, and RESET. Slide SENSOR OFFLINE or SWITCH STUCK to the right first to replay those cases. Run `scripts/panel_bridge.py` on your PC to drive it live from the study instead.

![The panel in Wokwi: switch Sw3 was stuck, so zone L13 was isolated too; tie Sw7 waits for CLOSE TIES](panel_tie_ready.png)

**What goes here:** a small control panel the study drives over MQTT. It is a mimic board: one RGB lamp per switch, laid out like the feeder's zone tree, plus a lockout lamp, a 20x4 LCD, three buttons, a knob and two failure-injection switches.

| Part | What it does |
|---|---|
| 12 RGB lamps | Sw1 to Sw5, L13 to L77 and the ties Sw7, Sw9. The colours mean: green = closed with power, grey = closed without power, red = open, blinking amber = the zone the model located, or a tie waiting for the operator, purple = that switch's sensor sends nothing, blinking red = the switch is stuck. |
| LOCKOUT lamp | On while the feeder-head recloser Sw1 is locked out. |
| LCD | The current switching step, with the study's numbers (located zone, confidence, kW restored). |
| FAULT button | Asks the study for a line-to-ground fault in a random zone (every zone equally likely), at a random bus inside it. |
| Knob | Picks that fault's resistance, one of the study's values (`config.SLG_RESISTANCES`). |
| CLOSE TIES button | The operator approves closing the planned ties. |
| RESET button | Puts the feeder back to normal. |
| SENSOR OFFLINE switch (slide right) | The next fault arrives with no readings from one switch, picked at random as in the study's missing-sensor test. The model uses the other nine; it was trained for this (sensor dropout), and the LCD shows the study's share of faults located correctly with that sensor missing (`results/metrics.json`). |
| SWITCH STUCK switch (slide right) | The first switch told to open fails to open. The zone on its other side is isolated together with the faulted zone, and the next switches out open instead (`restoration.plan_restoration(..., stuck=...)`); the ties are then checked by power flow as usual. |

Files:

| File | Made by |
|---|---|
| `wokwi/sketch.ino` | Firmware. Hand-written; the same code is meant to run on a real ESP32. |
| `wokwi/diagram.json` | Wiring and lamp layout. Generated from the study's topology: `python scripts/wokwi_diagram.py` |
| `wokwi/libraries.txt` | The Arduino libraries Wokwi installs. |
| demo block in `sketch.ino` | Recorded incidents for demo mode. Generated: `python scripts/wokwi_demo.py` |

## Run it

1. On the PC, start the study's side. It needs `models/model.pkl`, so run `python run.py` once first.

   ```bash
   python scripts/panel_bridge.py
   ```

2. Open a new ESP32 project at <https://wokwi.com/projects/new/esp32>. Paste `sketch.ino` and `diagram.json` into the tabs of the same name, and add the four libraries from `libraries.txt` in the Library Manager. Then press the green Start button.
3. Turn the knob to choose a fault resistance, then press FAULT. The lamps and the LCD walk through the switching steps:
   - Sw1 locks out;
   - the model names a zone;
   - isolation;
   - Sw1 re-closes;
   - the ties wait for CLOSE TIES.
4. Press RESET to start again. Slide SENSOR OFFLINE or SWITCH STUCK to the right before FAULT to inject a failure; LCD line 3 shows what is armed.

`python scripts/panel_bridge.py --dry-run --bus 60 --r 25` prints one incident's frames without MQTT.

## Building it for real

[`BOM.md`](BOM.md) lists the parts for a breadboard version (about $71 at 2026-11-20 store prices) and the wiring that differs from Wokwi: a real ESP32 needs level shifting for the 5 V NeoPixels and the 5 V LCD backpack, which Wokwi does not model.

## How it connects

The free Wokwi simulator reaches only the internet, not this computer. The board and `panel_bridge.py` therefore meet on a public test broker (`config.PANEL_BROKER`), with topics `shf/<PANEL_ID>/state` and `shf/<PANEL_ID>/cmd`.

- The messages are simulated panel states, nothing private.
- Anyone can read or write a public topic, so the bridge accepts only the four commands it knows (`shf/panel.py`, `parse_command`).

A real ESP32 would put its own Wi-Fi in `sketch.ino` and point `BROKER` at the local broker from `scada/docker-compose.yml`.

## Tier-1 Edge HIF Sensor ESP32-S3 Resource Budget

The companion Tier-1 edge detector ([`../hif_sensor/firmware/`](../hif_sensor/firmware/)) provides a pure C99 end-to-end pipeline (`hif_dsp.c` + `hif_infer.c` + `hif_model.h`) designed to run on an ESP32-S3-class MCU (`240 MHz` dual-core Xtensa LX7 with hardware FPU, `512 KB` internal SRAM):

| Component | Source File | Memory Footprint | Notes / Measured Verification |
|---|---|---|---|
| Quantized Tiny MLP weights (`16→16→8→1`, `417` params) | `hif_sensor/firmware/hif_model.h` (`hif_model_phase15.h`) | **504 B** Flash/RODATA | `int8` weights + `float32` per-layer scale & bias; **< 0.1%** of ESP32-S3 SRAM |
| 8-cycle ADC ring buffer (`2,048 × int16`) + amps (`float32`) | `hif_sensor/firmware/hif_dsp.c` | **12 KB** RAM | `256` samples/cycle (`15.36 kHz` @ 60 Hz US, `12.8 kHz` @ 50 Hz VN) |
| Radix-2 FFT scratch (`1024`-pt real + imag `float32`) | `hif_sensor/firmware/hif_dsp.c` | **8 KB** stack/static | Pure C99 iterative Cooley-Tukey; zero external DSP library required |
| Compiled GCC `13.3.0` bit-parity check (`-O2 -Wall -Wextra -Werror`) | `hif_sensor/firmware/test_infer.c` | `17 KB` Linux ELF | `max \|p_c − p_py\|` = `4.77×10⁻⁷` (Phase 0) / `1.04×10⁻⁶` (Phase 1.5), **100%** decision match, **`0.54–0.61 µs`** host MLP latency (`results/c_firmware_verify.json`) |

At 1 inference per power cycle (`16.67 ms` @ 60 Hz or `20.0 ms` @ 50 Hz), the 417-parameter MLP + 256/1024-pt FFT fits comfortably inside `< 1 ms` of ESP32-S3 CPU budget, leaving full headroom for ADC DMA and MQTT telemetry. (Not yet flashed or bench-measured on energized physical hardware.)

## Limits

Everything here is a simulation. The board is a Wokwi simulation, not field equipment, and it is not connected to a real feeder.

The panel shows what the study computes:

- the OpenDSS fault;
- the zone the trained model picks;
- the restoration plan.

When the model picks the wrong zone, the panel says so and stops. The study does not model what a real scheme would do next.

The stuck switch is a simple back-up rule: the zone behind the stuck switch is isolated as well. It is not modelled in time, so there are no breaker-failure timers and no second trip. With no switch stuck, the plan is exactly the study's plan.
