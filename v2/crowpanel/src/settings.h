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

  // Which numbers the volume is allowed to land on. Some people cannot leave a
  // -40.5 alone, and a few want it even or odd. See VolumeLattice.
  uint8_t  volumeLattice;
  uint8_t  accelFactor;          // multiplier when turning fast
  uint16_t accelWindowMs;        // what "fast" means
  uint8_t  encDivider;           // quadrature transitions per step (1, 2 or 4)
  int8_t   volMaxDb;             // ceiling in dB (-80 .. +18)

  uint8_t  brightness;           // backlight 10..255
  uint16_t dimAfterS;            // dim after this many idle seconds; 0 = never
  bool     rotated;              // screen rotated 180 degrees
  // Fine correction for a panel that ended up a few degrees off in its
  // mount, in tenths of a degree. 0 is the fast path: no rotation at all.
  int16_t  screenAngle;

  // Screen off as soon as the main zone goes off, and on again when it
  // returns. Switch the amplifier off with the remote — or let your Apple TV do
  // it over HDMI — and otherwise a lit screen is left standing on a system that
  // is off.
  bool     offWithAmp;

  uint16_t longPressMs;          // hold = power on/off
  uint16_t doublePressMs;        // double-press window; 0 = disabled
  int8_t   favouriteInput;       // index for the double press; -1 = off

  // Which of the inputs above is the Apple TV, as an index; -1 = none. Three
  // things need to know: choosing it wakes the Apple TV, switching everything
  // off puts it back to sleep, and tapping the screen while it is selected
  // opens the app launcher instead of the record shelf.
  int8_t   appleTvInput;


  uint8_t  inputCount;           // 0 .. MAX_INPUTS
  InputDef inputs[MAX_INPUTS];   // the list you step through by holding and turning
};

// What the volume may settle on. The receiver counts in half decibels and will
// take any of them; this is entirely about what you can stand to look at.
enum VolumeLattice : uint8_t {
  VOL_ANY = 0,    // every half step the receiver offers: -40.5, -41.0, -41.5
  VOL_WHOLE,      // whole decibels only: -40, -41, -42
  VOL_EVEN,       // -40, -42, -44
  VOL_ODD,        // -41, -43, -45
  VOL_LATTICES
};

// Snap a volume in half steps to the nearest allowed one in the given
// direction. Exposed for the panel and for its test.
int16_t volumeSnap(int16_t halfSteps, int direction, uint8_t lattice);

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
