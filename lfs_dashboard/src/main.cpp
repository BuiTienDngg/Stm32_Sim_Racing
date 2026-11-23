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
  screen.fillScreen(TFT_BLACK);
  screen.setTextDatum(TL_DATUM);
  screen.setTextColor(TFT_CYAN, TFT_BLACK);
  screen.drawString("LIVE FOR SPEED", 12, 8, 2);
  screen.setTextColor(connected ? TFT_GREEN : TFT_ORANGE, TFT_BLACK);
  screen.drawString(connected ? "LIVE" : "WAITING FOR LFS", 230, 8, 2);

  screen.setTextColor(TFT_WHITE, TFT_BLACK);
  screen.drawString("SPEED", 14, 39, 2);
  screen.setTextColor(TFT_CYAN, TFT_BLACK);
  screen.drawString(String(speedKmh), 12, 60, 7);
  screen.setTextColor(TFT_WHITE, TFT_BLACK);
  screen.drawString("km/h", 205, 100, 2);
  screen.drawFastHLine(12, 127, 296, TFT_DARKGREY);
  screen.drawString("RPM", 15, 141, 2);
  screen.setTextColor(TFT_YELLOW, TFT_BLACK);
  screen.drawString(String(rpm), 14, 163, 4);
  screen.setTextColor(TFT_WHITE, TFT_BLACK);
  screen.drawString("GEAR", 232, 142, 2);
  screen.setTextColor(TFT_GREEN, TFT_BLACK);
  screen.drawString(gear, 238, 165, 4);

  const int values[] = {throttle, brake, clutch};
  const char *names[] = {"GAS", "BRK", "CLT"};
  const uint16_t colors[] = {TFT_GREEN, TFT_RED, TFT_BLUE};
  for (int i = 0; i < 3; ++i) {
    int x = 14 + i * 102;
    screen.setTextColor(TFT_WHITE, TFT_BLACK);
    screen.drawString(names[i], x, 205, 2);
    screen.drawRect(x, 225, 88, 10, TFT_DARKGREY);
    screen.fillRect(x + 1, 226, values[i] * 86 / 100, 8, colors[i]);
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
