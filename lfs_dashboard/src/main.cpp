#include <Arduino.h>
#include <TFT_eSPI.h>

TFT_eSPI screen;
char line[96];
size_t used = 0;
unsigned long lastPacket = 0;
int speedKmh = 0, rpm = 0, throttle = 0, brake = 0, clutch = 0;
char gear[8] = "N";
bool connected = false;

void draw() {
  static bool first = true, oldConnected = false;
  static int oldSpeed = -1, oldRpm = -1, oldLit = -1;
  static int oldValues[3] = {-1, -1, -1};
  static char oldGear[8] = "";
  constexpr uint16_t panel = 0x10A2;
  if (first) {
    screen.fillScreen(TFT_BLACK);
    screen.setTextDatum(TL_DATUM);
    screen.setTextColor(TFT_WHITE, TFT_BLACK);
    screen.drawString("RACE DASH", 12, 8, 2);
    screen.drawFastHLine(12, 43, 296, panel);
    screen.drawFastHLine(12, 166, 296, panel);
    screen.drawString("SPEED", 14, 58, 2);
    screen.drawString("GEAR", 160, 58, 2);
    screen.drawString("RPM", 14, 174, 2);
    screen.drawString("km/h", 99, 137, 2);
    const char *names[] = {"THR", "BRK", "CLT"};
    for (int i = 0; i < 3; ++i) {
      int x = 14 + i * 102;
      screen.drawString(names[i], x, 207, 2);
      screen.drawRect(x + 37, 211, 52, 9, panel);
    }
    first = false;
  }
  if (connected != oldConnected || oldSpeed < 0) {
    screen.fillRect(245, 6, 63, 22, TFT_BLACK);
    screen.setTextColor(connected ? TFT_GREEN : TFT_ORANGE, TFT_BLACK);
    screen.drawRightString(connected ? "LIVE" : "WAIT", 308, 8, 2);
    oldConnected = connected;
  }
  // Update only segments whose state changed; the RPM range is 0..8000.
  int lit = constrain(rpm, 0, 8000) * 20 / 8000;
  if (lit != oldLit) {
    for (int i = 0; i < 20; ++i) {
      if (oldLit >= 0 && (i < lit) == (i < oldLit)) continue;
      uint16_t color = i < 12 ? TFT_CYAN : (i < 16 ? TFT_YELLOW : TFT_RED);
      screen.fillRect(12 + i * 15, 32, 12, 7, i < lit ? color : panel);
    }
    oldLit = lit;
  }
  if (speedKmh != oldSpeed) {
    screen.fillRect(12, 85, 143, 52, TFT_BLACK);
    screen.setTextColor(TFT_CYAN, TFT_BLACK);
    screen.drawString(String(speedKmh), 12, 85, 7);
    oldSpeed = speedKmh;
  }
  if (strcmp(gear, oldGear)) {
    screen.fillRect(160, 79, 148, 82, TFT_BLACK);
    screen.setTextColor(TFT_GREEN, TFT_BLACK);
    screen.drawCentreString(gear, 234, 81, 8);
    strcpy(oldGear, gear);
  }
  if (rpm != oldRpm) {
    screen.fillRect(60, 173, 110, 29, TFT_BLACK);
    screen.setTextColor(TFT_YELLOW, TFT_BLACK);
    screen.drawString(String(rpm), 60, 174, 4);
    oldRpm = rpm;
  }
  const int values[] = {throttle, brake, clutch};
  const uint16_t colors[] = {TFT_GREEN, TFT_RED, TFT_CYAN};
  for (int i = 0; i < 3; ++i) {
    if (values[i] == oldValues[i]) continue;
    int x = 14 + i * 102;
    screen.fillRect(x + 38, 212, 50, 7, panel);
    screen.fillRect(x + 38, 212, values[i] * 50 / 100, 7, colors[i]);
    oldValues[i] = values[i];
  }
}

void parseLine() {
  if (!strcmp(line, "STOP")) {
    connected = false;
    speedKmh = rpm = throttle = brake = clutch = 0;
    strcpy(gear, "N");
    draw();
    return;
  }
  int s, r, t, b, c;
  char g[8] = {};
  if (sscanf(line, "LFS,%d,%d,%7[^,],%d,%d,%d", &s, &r, g, &t, &b, &c) != 6) return;
  if (s < 0 || s > 600 || r < 0 || r > 30000 || t < 0 || t > 100 ||
      b < 0 || b > 100 || c < 0 || c > 100) return;
  speedKmh = s; rpm = r; throttle = t; brake = b; clutch = c;
  strcpy(gear, g);
  connected = true;
  lastPacket = millis();
  draw();
}

void setup() {
  Serial.begin(115200);
  pinMode(21, OUTPUT);
  digitalWrite(21, HIGH);
  screen.init();
  screen.setRotation(1);
  draw();
}

void loop() {
  while (Serial.available()) {
    char ch = (char)Serial.read();
    if (ch == '\n') {
      line[used] = 0;
      parseLine();
      used = 0;
    } else if (ch != '\r') {
      if (used + 1 < sizeof(line)) line[used++] = ch;
      else used = 0;
    }
  }
  if (connected && millis() - lastPacket > 2000) {
    connected = false;
    speedKmh = rpm = throttle = brake = clutch = 0;
    strcpy(gear, "N");
    draw();
  }
}
