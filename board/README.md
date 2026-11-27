# Control panel board (ESP32, simulated in Wokwi)

**Tool:** [Wokwi](https://wokwi.com) (browser ESP32 simulator), Arduino/C99 code.

**Try it in the browser, nothing to install: [https://wokwi.com/projects/481240462876979201](https://wokwi.com/projects/481240462876979201)**. Press the green Start button. With no study connected, the board waits 15 s and then enters demo mode: press **HIF ARC** (yellow button) to run the embedded C99 Tier-1 HIF DSP + 504 B `int8` MLP directly on the simulated ESP32 and replay a two-tier HIF → FLISR incident, or press **FAULT**, then **CLOSE TIES** when a tie lamp blinks, and **RESET**. Slide **SENSOR OFFLINE** or **SWITCH STUCK** to the right first to replay those cases. Run `scripts/panel_bridge.py` on your PC to drive it live from OpenDSS + ML instead (and optionally connect the browser [Monitor](../docs/monitor/README.md) over MQTT-WSS).

> **Simulation only:** Wokwi is a browser ESP32 microcontroller simulator connecting over a public demo MQTT broker (`broker.hivemq.com`). This panel is **not** energized physical hardware in the field and is **not** connected to a real utility feeder or SCADA system.

![The panel in Wokwi: switch Sw3 was stuck, so zone L13 was isolated too; tie Sw7 waits for CLOSE TIES](panel_tie_ready.png)

**What goes here:** a two-tier mimic control panel simulated on one ESP32. Tier 1 runs the verified pure-C99 HIF DSP + quantized Tiny MLP (`hif_dsp.c` + `hif_infer.c` + `hif_model.h`) directly on the ESP32; Tier 2 (`scripts/panel_bridge.py`) runs OpenDSS + ML FLISR on the PC and drives the board over MQTT. The panel has one RGB lamp per switch laid out like the feeder's zone tree, a lockout lamp, a yellow Tier-1 HIF alarm lamp, a 20x4 LCD, four buttons, a resistance knob and two failure-injection slide switches.

| Part | What it does |
|---|---|
| 12 RGB lamps | Sw1 to Sw5, L13 to L77 and the ties Sw7, Sw9. The colours mean: green = closed with power, grey = closed without power, red = open, blinking amber = the zone the model located, or a tie waiting for the operator, purple = that switch's sensor sends nothing, blinking red = the switch is stuck. |
| LOCKOUT lamp (red) | On while the feeder-head recloser Sw1 is locked out. |
| HIF ALARM lamp (yellow) | On when the on-chip C99 Tier-1 HIF detector latches (`PERSIST = 3` consecutive windows above `0.982635`) or when a Tier-1 HIF state frame arrives (`hif.alarm == 1`). |
| LCD (20×4 I2C) | Shows Tier-1 C99 inference (`p_hif`, `P=3/3`, elapsed `µs`, `504B`) followed by each Tier-2 switching step (located zone, confidence, kW restored). |
| FAULT button (red) | Asks the study for a line-to-ground fault in a random zone (every zone equally likely), at a random bus inside it. When the knob is set to `R >= 100 Ω`, pressing FAULT runs the on-chip Tier-1 C99 HIF pipeline first. |
| CLOSE TIES button (green) | The operator approves closing the planned ties. |
| RESET button (blue) | Resets the Tier-1 persistence state (`hif_reset()`) and puts the feeder back to normal. |
| HIF ARC button (yellow) | Runs the on-chip C99 Tier-1 DSP + 504 B `int8` MLP directly on a deterministic 10-cycle Emanuel arcing waveform (`400 Ω` default, or knob `R >= 100 Ω`), lights **HIF ALARM**, publishes JSON to `shf/shf123-demo/hif`, and triggers Tier-2 FLISR. |
| Knob | Picks that fault's resistance, one of the study's values (`config.SLG_RESISTANCES`: `0.01` to `400 Ω`). |
| SENSOR OFFLINE switch (slide right) | The next fault arrives with no readings from one switch, picked at random as in the study's missing-sensor test. The model uses the other nine; it was trained for this (sensor dropout), and the LCD shows the study's share of faults located correctly with that sensor missing (`results/metrics.json`). |
| SWITCH STUCK switch (slide right) | The first switch told to open fails to open. The zone on its other side is isolated together with the faulted zone, and the next switches out open instead (`restoration.plan_restoration(..., stuck=...)`); the ties are then checked by power flow as usual. |

## GPIO pinout (`wokwi/diagram.json` & `wokwi/sketch.ino`)

| ESP32 GPIO | Direction / Bus | Component | Notes |
|---|---|---|---|
| `GPIO 13` | Output (NeoPixel) | 12 × RGB NeoPixel chain (`Sw1..Sw5`, `L13..L77`, `Sw7`, `Sw9`) | `5 V` in Wokwi; needs 3.3 V→5 V level shifter on real hardware |
| `GPIO 4` | Output | Red `LOCKOUT` LED (`220 Ω` series resistor) | HIGH while `Sw1` is locked out |
| **`GPIO 5`** | **Output** | **Yellow `HIF ALARM` LED (`220 Ω` series resistor)** | **NEW — HIGH when on-chip Tier-1 C99 `hif_update() == 1` (or `hif.alarm == 1`)** |
| **`GPIO 14`** | **Input (`INPUT_PULLUP`)** | **Yellow `HIF ARC` pushbutton** | **NEW — Active LOW; runs on-chip C99 DSP + 504 B `int8` MLP & publishes `/hif`** |
| `GPIO 21` / `GPIO 22` | I2C (`SDA` / `SCL`) | 20×4 I2C LCD (`0x27`) | Displays Tier-1 `p_hif` / `infer_us` and Tier-2 FLISR steps |
| `GPIO 25` / `GPIO 26` / `GPIO 27` | Input (`INPUT_PULLUP`) | `FAULT`, `CLOSE TIES`, `RESET` pushbuttons | Active LOW, 40 ms debounce |
| `GPIO 34` | Analog input (`ADC1`) | Fault-resistance potentiometer (`3.3 V`–`GND`) | Maps to `config.SLG_RESISTANCES` (`0.01`–`400 Ω`) |
| `GPIO 32` / `GPIO 33` | Input (`INPUT_PULLUP`) | `SENSOR OFFLINE`, `SWITCH STUCK` slide switches | Active LOW when slid right |

Files in `board/wokwi/`:

| File | Made by |
|---|---|
| `wokwi/sketch.ino` | Firmware. Hand-written; runs the C99 Tier-1 worker task and MQTT Tier-2 panel client. |
| `wokwi/hif_dsp.h`, `wokwi/hif_dsp.c` | Byte-identical copies of `hif_sensor/firmware/hif_dsp.{h,c}` (12-bit ADC → amps, 256/1024-pt Radix-2 FFT, 16 features). |
| `wokwi/hif_infer.h`, `wokwi/hif_infer.c` | Byte-identical copies of `hif_sensor/firmware/hif_infer.{h,c}` (`int8` MLP inference + `PERSIST = 3` relay state machine). |
| `wokwi/hif_model.h` | Byte-identical copy of `hif_sensor/firmware/hif_model.h` (frozen Phase-0 `417`-param / `504 B` `int8` weights + `float32` biases, threshold `0.982635`). |
| `wokwi/hif_arc_samples.h` | Deterministic C99 12-bit ADC waveform generator (fixed seed `0x5A17C991u`, `33/2000 V/A`, `1.65 V` bias) generating 10 cycles (`2,560` samples) on the fly for `PERSIST = 3` sliding windows without large Flash tables. |
| `wokwi/diagram.json` | Wiring and lamp layout. Generated from the study's topology: `python scripts/wokwi_diagram.py` |
| `wokwi/libraries.txt` | The 4 Arduino libraries Wokwi installs (`PubSubClient`, `ArduinoJson`, `Adafruit NeoPixel`, `LiquidCrystal I2C`). |
| demo block in `sketch.ino` | Recorded incidents (`DEMO_NORMAL`, `DEMO_SENSOR`, `DEMO_STUCK`, `DEMO_HIF`) for offline demo mode. Generated: `python scripts/wokwi_demo.py` |

## Running the C99 Tier-1 HIF chain directly on Wokwi ESP32

Instead of mocking a pre-computed probability, `board/wokwi/` compiles and runs the exact pure-C99 source files (`hif_dsp.c`, `hif_infer.c`, `hif_model.h`) copied byte-for-byte from [`../hif_sensor/firmware/`](../hif_sensor/firmware/) — the same files verified with Linux GCC `13.3.0` (`-O2 -Wall -Wextra -Werror`) in [`../hif_sensor/results/c_firmware_verify.json`](../hif_sensor/results/c_firmware_verify.json) (`417` parameters, `504 B` `int8` weights + `float32` biases, `max |p_c - p_py| = 4.77×10⁻⁷` on 6 official vectors and `8.34×10⁻⁷` on 100 extended vectors, `100%` decision agreement, `0.540–0.611 µs` host MLP latency):

1. **Dedicated `24 KB` FreeRTOS worker task (`hif_c99`, Core 1):** ESP32's default Arduino `loopTask` stack is only `8 KB`, while the 1024-pt Radix-2 FFT in `hif_extract_features()` uses ~`10 KB` of stack. `sketch.ino` therefore allocates `HIF_TASK_STACK = 24576` bytes for `hifWorkerTask()` and keeps the 10-cycle ADC/amps buffers (`2,560 × int16` + `2,560 × float32`) in static DRAM.
2. **End-to-end execution per trigger:** `hif_gen_cycles()` → `hif_adc_to_amps()` → 3 sliding 8-cycle windows of `hif_extract_features()` → `hif_predict()` / `hif_update()` (`HIF_PERSIST = 3`, `HIF_THRESHOLD = 0.982635`), timed on the simulated ESP32 with `micros()`.
3. **Boot self-test:** on startup, `setup()` automatically runs one normal-load pass (`is_arc = 0`) and prints `[HIF-C99] mode=normal ... alarm=0` to the Wokwi Serial Monitor to verify zero false alarm before waiting for user input.
4. **Offline demo parity:** if `panel_bridge.py` is not running after 15 s, Wokwi enters demo mode (`DEMO_HIF`) but **still executes the real C99 DSP + MLP pipeline on the ESP32** when you press **HIF ARC** (or **FAULT** at `R >= 100 Ω`), then replays the recorded OpenDSS + ML FLISR steps (`bus 35`, `400 Ω`, zone `Sw3`, tie `Sw7` restoring `+515 kW`).

## Run it (10-second Wokwi ↔ Monitor two-tier demo)

### Option A — Live Wokwi ESP32 ↔ PC Study ↔ Monitor (full MQTT loop)

1. On the PC, start the Tier-2 study bridge (needs `models/model.pkl`, so run `python run.py` once first):

   ```bash
   python scripts/panel_bridge.py
   ```

   *(To inspect one Tier-1 HIF → Tier-2 FLISR sequence in the terminal without MQTT: `python scripts/panel_bridge.py --dry-run --bus 60 --phase 1 --r 400 --hif`, or standard fault `--dry-run --bus 60 --r 25`.)*

2. Open the Wokwi ESP32 project ([shared link](https://wokwi.com/projects/481240462876979201), or create a new ESP32 project at <https://wokwi.com/projects/new/esp32> and add `sketch.ino`, `diagram.json`, `libraries.txt`, `hif_dsp.{h,c}`, `hif_infer.{h,c}`, `hif_model.h`, and `hif_arc_samples.h`), then press the green **Start** button.
3. Open the [Monitor](../docs/monitor/README.md) page (`https://chau1912550.github.io/self-healing-feeder/monitor/` or locally via `python -m http.server 5173 --directory docs/monitor`) and toggle **Live Wokwi MQTT** on (connects via `wss://broker.hivemq.com:8884/mqtt`).
4. On Wokwi, press **HIF ARC** (yellow button) — or turn the knob to `100 / 200 / 400 Ω` and press **FAULT**:
   - **~0–2 s (Tier 1 on ESP32):** ESP32 runs `hif_dsp.c` + `hif_infer.c` (`504 B` `int8`), lights yellow **HIF ALARM** (`GPIO 5`), shows `p_hif`, `P=3/3` and `µs` on the LCD, and publishes the 6-key alert to `shf/shf123-demo/hif`.
   - **~2–7 s (Tier 2 FLISR):** `panel_bridge.py` runs OpenDSS + ML fault location, publishes state frames with `hif` and `flow` metadata to `shf/shf123-demo/state`; Wokwi walks through Sw1 lockout, ML zone, isolation, Sw1 re-close, and blinking tie lamp while Monitor updates live.
   - **~7–10 s (Restoration):** press **CLOSE TIES** on Wokwi; the planned tie closes, Wokwi shows `+kW restored`, and Monitor animates the reversed back-feed power flow through the closed tie.
5. Press **RESET** to return to normal. Slide **SENSOR OFFLINE** or **SWITCH STUCK** right before **FAULT** to inject a failure; LCD line 3 shows what is armed.

### Option B — Browser-only 10-second demo (no PC bridge needed)

- **In Wokwi only:** open the shared Wokwi link, press Start, wait 15 s for demo mode, then press **HIF ARC** → **CLOSE TIES** → **RESET**.
- **In Monitor only:** open the [Monitor](../docs/monitor/README.md) page and click the one-click **10s Two-Tier Demo** button (replays the full 10-second HIF Arc → ESP32 → FLISR → reversed tie back-feed cycle locally with zero broker required).

## Building it for real

[`BOM.md`](BOM.md) lists the parts for a breadboard version (about $71 at 2026-11-20 store prices) and the wiring that differs from Wokwi: a real ESP32 needs level shifting for the 5 V NeoPixels and the 5 V LCD backpack, which Wokwi does not model (add one yellow LED + `220 Ω` resistor on `GPIO 5` and one pushbutton on `GPIO 14` from the kit to include the Tier-1 HIF indicator/trigger).

## How it connects

The free Wokwi simulator reaches only the internet, not this computer. The board, `panel_bridge.py`, and the optional browser Monitor therefore meet on a public test broker (`config.PANEL_BROKER = broker.hivemq.com`: TCP `1883` for ESP32/Python, WSS `8884` for the browser Monitor):

| Topic | Direction | Payload & Validation |
|---|---|---|
| `shf/shf123-demo/state` | Study (`panel_bridge.py`) → Wokwi & Monitor | Panel lamps, `lock`, `wait`, `idle`, 4-line `lcd`, `rs`, directional `flow` (`upstream`, `restored_by_tie`, `ties`), and optional `hif` metadata. |
| `shf/shf123-demo/cmd` | Wokwi → Study | Button commands (`fault`, `ties`, `reset`, `hello`) validated strictly by `shf/panel.py:parse_command()`. |
| `shf/shf123-demo/hif` | Wokwi Tier-1 C99 → Study & Monitor | Strict 6-key JSON (`<= 256 B`) validated by `shf/panel.py:parse_hif_alert()`: `{"p_hif": 0..1, "alarm": 0\|1, "persist": 0..10, "infer_us": >=0, "mode": "arc"\|"normal", "r": <SLG_RESISTANCES\|null>}`. |

- All messages are simulated panel states and simulated HIF alerts — nothing private.
- Because anyone can read or write a public broker topic, `panel_bridge.py` accepts only the four known commands (`parse_command`) and strictly type/range-checked HIF alerts (`parse_hif_alert`).

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

Everything here is a simulation. Wokwi is a browser ESP32 microcontroller simulator connecting through a public demo MQTT broker (`broker.hivemq.com`), **not** energized physical hardware in the field, and it is not connected to a real utility feeder or SCADA system. The on-chip C99 HIF waveforms (`hif_arc_samples.h`) are deterministic synthetic 12-bit Emanuel arcing signals rather than live substation CT measurements.

The panel shows what the study computes:

- the Tier-1 on-chip C99 DSP + `504 B` `int8` MLP HIF check;
- the OpenDSS fault;
- the zone the trained model picks;
- the restoration plan.

When the model picks the wrong zone, the panel says so and stops. The study does not model what a real scheme would do next.

The stuck switch is a simple back-up rule: the zone behind the stuck switch is isolated as well. It is not modelled in time, so there are no breaker-failure timers and no second trip. With no switch stuck, the plan is exactly the study's plan.
