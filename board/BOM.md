# Hardware list for a real panel

This is the parts list for building the Wokwi panel ([`README.md`](README.md)) on a real breadboard. Nothing here is bought yet; the owner decides and orders.

The firmware in `wokwi/sketch.ino` runs on the real board with three changes:

- your Wi-Fi name and password;
- drop the Wokwi channel argument in `WiFi.begin`;
- the I2C address of your LCD, if it is not 0x27.

Everything runs from the 5 V USB supply. **No mains voltage anywhere.** The panel shows the simulated feeder; it does not connect to one.

Prices are USD, from the store pages on 2026-11-20, one unit, before shipping and tax. They change, so check the store before ordering.

## Needed

| # | Part | Wokwi part it replaces | Qty | Price | Where |
|---|---|---|---|---|---|
| 1 | Espressif **ESP32-DevKitC-32E** (ESP32-WROOM-32E, 4 MB flash) | `board-esp32-devkit-c-v4` | 1 | $10.00 | [DigiKey 1965-ESP32-DEVKITC-32E-ND](https://www.digikey.com/en/products/detail/espressif-systems/ESP32-DEVKITC-32E/12091810) (Mouser lists $10.21) |
| 2 | Breadboard-friendly RGB NeoPixels (WS2812-type), sheet of 25 | 12 × `wokwi-neopixel` | 1 sheet (12 used, 13 spare) | $24.95 | [Adafruit 1558](https://www.adafruit.com/product/1558) |
| 3 | **74AHCT125** quad level shifter, 3 V to 5 V, for the NeoPixel data line | — (not needed in Wokwi) | 1 | $1.50 | [Adafruit 1787](https://www.adafruit.com/product/1787) |
| 4 | **20x4 character LCD with I2C backpack (PCF8574 type)**, address 0x27 or 0x3F, works with the `LiquidCrystal_I2C` library the firmware uses | `wokwi-lcd2004` (I2C) | 1 | $14.99 | [SunFounder LCD2004 I2C](https://www.sunfounder.com/products/i2c-lcd2004-module) |
| 5 | **4-channel I2C-safe level converter (BSS138)**, for SDA/SCL between the 3.3 V ESP32 and the 5 V LCD backpack | — (not needed in Wokwi) | 1 | $3.95 | [Adafruit 757](https://www.adafruit.com/product/757) |
| 6 | Starter parts kit: 830-point breadboard, jumper wires, push buttons, potentiometer, LEDs, resistors, capacitors | `wokwi-pushbutton` ×3, `wokwi-potentiometer`, `wokwi-led` + `wokwi-resistor` | 1 | about $16 | ELEGOO Upgraded Electronics Fun Kit EL-CK-003 ([Keystone $15.99](https://www.keystoneenterprises.com/maker-electronics/elegoo-upgraded-electronics-fun-kit-for-arduino.html)) |
| | **Total** | | | **about $71** | plus shipping and tax |

Also needed:

- a micro-USB **data** cable (the DevKitC V4 has a micro-USB port);
- a **1000 µF electrolytic capacitor** for the NeoPixel supply (if the kit does not have one; see below);
- the two failure-injection switches. SPDT slide switches work, or two jumper wires from the kit: plug the wire into GND for "on", pull it out for "off".

Adafruit's own LCD backpack (product 292) is **not** a drop-in substitute for item 4. It uses a different chip (MCP23008, address 0x20) and needs a different library.

## Wiring that differs from Wokwi

Wokwi is forgiving about voltage levels; a real board is not.

1. **NeoPixel data (GPIO13).** The NeoPixels run at 5 V and expect a 5 V data signal; the ESP32 gives 3.3 V.
   - Route GPIO13 through one gate of the 74AHCT125, powered at 5 V, with its enable pin tied to GND.
   - Put a 300–500 Ω resistor in series with the first pixel's DIN.
   - Put the 1000 µF capacitor across 5 V and GND near the first pixel. This follows Adafruit's NeoPixel best-practice guide.
2. **LCD I2C (GPIO21 SDA, GPIO22 SCL).** The LCD backpack runs at 5 V and pulls SDA/SCL up to 5 V, but ESP32 pins are 3.3 V. Put the BSS138 converter between them: low side to 3.3 V and the ESP32, high side to 5 V and the LCD.
3. **LCD address.** Run an I2C scanner sketch once. If it shows 0x3F, change `LiquidCrystal_I2C lcd(0x27, 20, 4)` to 0x3F.
4. **Knob (GPIO34).** Connect the potentiometer between **3.3 V** and GND, never 5 V. GPIO34 is input-only and on ADC1, which still works while Wi-Fi is on.
5. **Buttons and failure switches (GPIO25, 26, 27, 32, 33).** Wire each between the pin and GND, as in Wokwi; the firmware uses the internal pull-ups.
6. **Lockout LED (GPIO4).** Wire GPIO4 → 220 Ω → LED → GND, as in Wokwi.
7. **Power.** The firmware sets the NeoPixel brightness to 120/255 and never shows white, so 12 pixels stay well inside what a USB port gives. Do not raise the brightness to full white on USB power.
8. **Network.** Put your Wi-Fi in `WIFI_SSID` / `WIFI_PASS`. Keep `broker.hivemq.com`, or run the local broker in `../scada/docker-compose.yml` and point `BROKER` at that computer's address.

## Optional, later (not priced, not needed for the panel)

| Part | Why |
|---|---|
| 5 V relay module | Clicks when Sw1 trips, for a demo video. Switch only low voltage with it. |
| INA219 current sensor breakout | Measures a small DC current, if a later step adds a real measurement. Use it on low-voltage DC only, never on mains. |
| Raspberry Pi | Not needed. The ESP32 does the panel, and the study runs on the PC. |
