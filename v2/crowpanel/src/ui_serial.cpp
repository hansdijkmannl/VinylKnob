// ---------------------------------------------------------------------------
// Screen implementation for the serial port.
//
// This lets the whole control layer be built and walked through with no panel
// attached: the monitor shows exactly what would be drawn. Swap between this
// and ui_lvgl.cpp in build_src_filter.
//
// Touches are simulated by typing a letter in the monitor:
//   i = tap the input name    a = tap the sleeve
//   c = bevestigen               x = wegklikken
// ---------------------------------------------------------------------------

#include "ui.h"

static Touch pending = Touch::None;
static Screen lastScreen = Screen::Setup;

void uiBegin() {
  Serial.println(F("\n[screen] serial output active"));
  Serial.println(F("[screen] i=input  a=sleeve  c=confirm  x=dismiss"));
}

static const char *screenName(Screen s) {
  switch (s) {
    case Screen::Volume:  return "VOLUME";
    case Screen::Inputs:  return "INPUT";
    case Screen::Browse:  return "SHELF";
    case Screen::Pairing: return "LINK";
    case Screen::Setup:   return "SETUP";
    case Screen::NoAvr:   return "NO RECEIVER";
  }
  return "?";
}

void uiRender(const UiState &s) {
  if (s.screen != lastScreen) {
    Serial.printf("\n=== %s ===\n", screenName(s.screen));
    lastScreen = s.screen;
  }

  switch (s.screen) {
    case Screen::Volume: {
      char vol[16];
      if (s.haveVolume) snprintf(vol, sizeof(vol), "%.1f dB", s.volumeDb);
      else              strcpy(vol, "--");
      Serial.printf("[%s] %-9s %-14s%s%s\n",
                    s.turning ? "turning" : "   idle", vol, s.inputLabel,
                    s.muted ? "  MUTE" : "", s.powered ? "" : "  STANDBY");
      if (s.nowTitle[0])
        Serial.printf("         %s - %s%s\n", s.nowArtist, s.nowTitle,
                      s.haveArtwork ? "  [sleeve]" : "");
      break;
    }
    case Screen::Inputs:
    case Screen::Browse:
      Serial.printf("  %d/%d  %s\n", s.pickIndex + 1, s.pickCount, s.pickLabel);
      break;
    case Screen::Pairing:
      Serial.printf("  QR -> http://%s   (%s.local)\n", s.ip, "vinylknob");
      break;
    case Screen::Setup:
      Serial.println(F("  connect to the access point and set up Wi-Fi"));
      break;
    case Screen::NoAvr:
      Serial.println(F("  Wi-Fi ok, receiver unreachable"));
      break;
  }
}

void uiTick() {
  while (Serial.available()) {
    switch (Serial.read()) {
      case 'i': pending = Touch::InputLabel; break;
      case 'a': pending = Touch::Artwork;    break;
      case 'c': pending = Touch::Confirm;    break;
      case 'x': pending = Touch::Dismiss;    break;
      default: break;
    }
  }
}

Touch uiTakeTouch() {
  const Touch t = pending;
  pending = Touch::None;
  return t;
}

void uiSetRotation(bool) {}   // the serial view does not rotate
void uiSetAngle(int16_t) {}   // nor by a few degrees
