// Self-healing feeder (FLISR) control panel on a simulated ESP32 in Wokwi.
//
// The study (Python + OpenDSS, scripts/panel_bridge.py) runs on the PC and drives this panel over
// MQTT; the panel sends its button presses back. The frame format is described in shf/panel.py.
// Simulation only: this is not field equipment and it is not connected to a real feeder.
//
// Lamps, in chain order (shf/panel.py LAMPS): Sw1 Sw2 Sw3 Sw4 Sw5 L13 L45 L61 L68 L77 Sw7 Sw9
// Lamp colours: green = closed with power, grey = closed without power, red = open,
// blinking amber = zone the model located, or a tie waiting for CLOSE TIES,
// purple = that switch's sensor sends nothing, blinking red = switch stuck (did not open).
// Failure injection: the SENSOR OFFLINE and SWITCH STUCK slide switches ride along with FAULT.

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <LiquidCrystal_I2C.h>

// On a real board: your own Wi-Fi, and BROKER pointing at the local broker (scada/docker-compose.yml).
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASS ""
#define BROKER "broker.hivemq.com"
#define BROKER_PORT 1883
#define PANEL_ID "shf123-demo"
#define N_LAMPS 12

const int PIN_LAMPS = 13, PIN_LOCK = 4, PIN_KNOB = 34;
const int PIN_SENSOR = 32, PIN_STUCK = 33;            // slide switches, ON = pulled to GND
const int PIN_BTN[3] = {25, 26, 27};                  // FAULT, CLOSE TIES, RESET
const char* BTN_CMD[3] = {"fault", "ties", "reset"};
const char* TOPIC_STATE = "shf/" PANEL_ID "/state";
const char* TOPIC_CMD = "shf/" PANEL_ID "/cmd";

Adafruit_NeoPixel lamps(N_LAMPS, PIN_LAMPS, NEO_GRB + NEO_KHZ800);
LiquidCrystal_I2C lcd(0x27, 20, 4);
WiFiClient net;
PubSubClient mqtt(net);

char lampCode[N_LAMPS + 1] = "GGGGGGGGGGRR";
bool lockout = false, idle = false, waiting = false;
double rs[16];
int nRs = 0, knobIdx = -1;
bool btnLast[3] = {true, true, true};
unsigned long btnTime[3] = {0, 0, 0}, lastDraw = 0;

void lcdLine(int row, const char* text) {
  char buf[21];
  snprintf(buf, sizeof buf, "%-20.20s", text);
  lcd.setCursor(0, row);
  lcd.print(buf);
}

uint32_t colour(char c, bool on) {
  switch (c) {
    case 'G': return lamps.Color(0, 170, 0);
    case 'R': return lamps.Color(200, 0, 0);
    case 'K': return lamps.Color(35, 35, 35);
    case 'A': return on ? lamps.Color(240, 140, 0) : 0;
    case 'P': return lamps.Color(130, 0, 170);
    case 'S': return on ? lamps.Color(255, 0, 0) : lamps.Color(40, 0, 0);
    default:  return 0;
  }
}

void drawLamps() {
  bool on = (millis() / 350) % 2 == 0;
  for (int i = 0; i < N_LAMPS; i++) lamps.setPixelColor(i, colour(lampCode[i], on));
  lamps.show();
  digitalWrite(PIN_LOCK, lockout ? HIGH : LOW);
}

bool sensorOff() { return digitalRead(PIN_SENSOR) == LOW; }
bool stuckOn() { return digitalRead(PIN_STUCK) == LOW; }

// On an idle frame, LCD line 2 shows the knob's fault resistance and line 3 the failures armed.
int failShown = -1;
void drawKnob() {
  if (!idle || nRs == 0) return;
  int idx = min(nRs - 1, (int)((long)analogRead(PIN_KNOB) * nRs / 4096));
  int fail = (sensorOff() ? 1 : 0) + (stuckOn() ? 2 : 0);
  if (idx == knobIdx && fail == failShown) return;
  knobIdx = idx;
  failShown = fail;
  char buf[24];
  snprintf(buf, sizeof buf, "Knob: R = %g ohm", rs[idx]);
  lcdLine(1, buf);
  const char* armed[4] = {"FAULT: new fault", "FAULT +no sensor", "FAULT +stuck switch", "FAULT +sensor +stuck"};
  lcdLine(2, armed[fail]);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  const char* code = doc["lamps"] | "";
  if (strlen(code) == N_LAMPS) memcpy(lampCode, code, N_LAMPS);
  lockout = (doc["lock"] | 0) == 1;
  waiting = (doc["wait"] | 0) == 1;
  idle = (doc["idle"] | 0) == 1;
  JsonArray r = doc["rs"];
  if (!r.isNull()) {
    nRs = 0;
    for (JsonVariant v : r) if (nRs < 16) rs[nRs++] = v.as<double>();
  }
  JsonArray lines = doc["lcd"];
  for (int i = 0; i < 4; i++) lcdLine(i, lines[i] | "");
  knobIdx = -1;
  failShown = -1;
  drawKnob();
  drawLamps();
}

void send(int b) {
  JsonDocument doc;
  doc["cmd"] = BTN_CMD[b];
  if (b == 0) {                        // FAULT: only when the study is ready for a new one
    if (!idle || knobIdx < 0) return;
    doc["r"] = rs[knobIdx];
    doc["sensor"] = sensorOff() ? 1 : 0;
    doc["stuck"] = stuckOn() ? 1 : 0;
  }
  if (b == 1 && !waiting) return;      // CLOSE TIES: only when a tie is waiting
  char buf[96];
  serializeJson(doc, buf);
  mqtt.publish(TOPIC_CMD, buf);
  Serial.printf("sent %s\n", buf);
}

void connect() {
  if (WiFi.status() != WL_CONNECTED) {
    lcdLine(0, "Connecting Wi-Fi...");
    WiFi.begin(WIFI_SSID, WIFI_PASS, 6);   // channel 6 = Wokwi's access point; drop it on a real board
    while (WiFi.status() != WL_CONNECTED) delay(200);
  }
  lcdLine(0, "Connecting MQTT...");
  char id[32];
  snprintf(id, sizeof id, "shf-panel-%08lx", (unsigned long)esp_random());
  while (!mqtt.connect(id)) delay(1000);
  mqtt.subscribe(TOPIC_STATE);
  mqtt.publish(TOPIC_CMD, "{\"cmd\":\"hello\"}");
  lcdLine(0, "Waiting for study:");
  lcdLine(1, "run panel_bridge.py");
}

void setup() {
  Serial.begin(115200);
  for (int b = 0; b < 3; b++) pinMode(PIN_BTN[b], INPUT_PULLUP);
  pinMode(PIN_SENSOR, INPUT_PULLUP);
  pinMode(PIN_STUCK, INPUT_PULLUP);
  pinMode(PIN_LOCK, OUTPUT);
  lamps.begin();
  lamps.setBrightness(120);
  lcd.init();
  lcd.backlight();
  lcdLine(0, "SELF-HEALING FEEDER");
  lcdLine(3, "simulation only");
  mqtt.setServer(BROKER, BROKER_PORT);
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(60);   // the simulator can run at a third of real time; 15 s pings then arrive too late
  mqtt.setCallback(onMessage);
  drawLamps();
}

void loop() {
  if (!mqtt.connected()) connect();
  mqtt.loop();
  for (int b = 0; b < 3; b++) {          // buttons pull the pin low; 40 ms debounce
    bool now = digitalRead(PIN_BTN[b]);
    if (now != btnLast[b] && millis() - btnTime[b] > 40) {
      btnTime[b] = millis();
      btnLast[b] = now;
      if (!now) send(b);
    }
  }
  if (millis() - lastDraw > 100) {
    lastDraw = millis();
    drawKnob();
    drawLamps();
  }
}
