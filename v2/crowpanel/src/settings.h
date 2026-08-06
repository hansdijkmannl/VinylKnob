#pragma once

#include <Arduino.h>
#include "config.h"

struct InputDef {
  char code[16];   // protocol name without "SI", e.g. "PHONO"
  char label[20];  // what appears on the screen
};

struct Settings {
  char     wifiSsid[33];
  char     wifiPass[65];
  char     avrHost[48];          // IP address or hostname of the receiver
  uint16_t avrPort;

  // The brain on the Pi, where recognition comes from. Empty = off, and the
  // panel falls back to showing volume and input only.
  char     brainHost[48];

  uint8_t  halfDbPerClick;       // 1 = 0.5 dB per click
  uint8_t  accelFactor;          // multiplier when turning fast
  uint16_t accelWindowMs;        // what "fast" means
  uint8_t  encDivider;           // quadrature transitions per step (1, 2 or 4)
  int8_t   volMaxDb;             // ceiling in dB (-80 .. +18)

  uint8_t  brightness;           // backlight 10..255
  uint16_t dimAfterS;            // dim after this many idle seconds; 0 = never
  bool     rotated;              // screen rotated 180 degrees

  // Screen off as soon as the main zone goes off, and on again when it
  // returns. Switch the amplifier off with the remote — or let your Apple TV do
  // it over HDMI — and otherwise a lit screen is left standing on a system that
  // is off.
  bool     offWithAmp;

  uint16_t longPressMs;          // hold = power on/off
  uint16_t doublePressMs;        // double-press window; 0 = disabled
  int8_t   favouriteInput;       // index for the double press; -1 = off


  uint8_t  inputCount;           // 0 .. MAX_INPUTS
  InputDef inputs[MAX_INPUTS];   // the list you step through by holding and turning
};

extern Settings settings;

void settingsLoad();
void settingsSave();

// Clear the Wi-Fi credentials, so the board boots into setup mode again.
void settingsClearWifi();

// Index of this protocol code in the input list, or -1.
int settingsFindInput(const char *code);

// Serialise to JSON for the web interface. The Wi-Fi password never leaves;
// instead the JSON says whether one is stored.
void settingsToJson(String &out);

// Apply a partial JSON document. Only fields that are present change, and
// everything is clamped to a valid range. False on malformed JSON.
bool settingsFromJson(const String &body, String &err, bool &wifiChanged);
