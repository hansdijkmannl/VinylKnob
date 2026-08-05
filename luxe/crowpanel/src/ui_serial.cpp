// ---------------------------------------------------------------------------
// Scherm-implementatie voor de seriële poort.
//
// Hiermee is de hele bediening te bouwen en te doorlopen zonder dat er een
// paneel aangesloten is: je ziet in de monitor precies wat er getekend zou
// worden. Zodra ui_lvgl.cpp er is, haal je dit bestand uit build_src_filter.
//
// Aanrakingen zijn hier na te bootsen door een letter in de monitor te typen:
//   i = tik op de ingangsnaam    a = tik op de hoes
//   c = bevestigen               x = wegklikken
// ---------------------------------------------------------------------------

#include "ui.h"

static Touch pending = Touch::None;
static Screen lastScreen = Screen::Setup;

void uiBegin() {
  Serial.println(F("\n[scherm] seriële weergave actief"));
  Serial.println(F("[scherm] i=ingang  a=hoes  c=bevestig  x=weg"));
}

static const char *screenName(Screen s) {
  switch (s) {
    case Screen::Volume:  return "VOLUME";
    case Screen::Inputs:  return "INGANG";
    case Screen::Browse:  return "PLATENKAST";
    case Screen::Pairing: return "KOPPELEN";
    case Screen::Setup:   return "SETUP";
    case Screen::NoAvr:   return "GEEN RECEIVER";
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
                    s.turning ? "draait" : "  rust", vol, s.inputLabel,
                    s.muted ? "  MUTE" : "", s.powered ? "" : "  STANDBY");
      if (s.nowTitle[0])
        Serial.printf("         %s - %s%s\n", s.nowArtist, s.nowTitle,
                      s.haveArtwork ? "  [hoes]" : "");
      break;
    }
    case Screen::Inputs:
    case Screen::Browse:
      Serial.printf("  %d/%d  %s\n", s.pickIndex + 1, s.pickCount, s.pickLabel);
      break;
    case Screen::Pairing:
      Serial.printf("  QR -> http://%s   (%s.local)\n", s.ip, "marantzknob");
      break;
    case Screen::Setup:
      Serial.println(F("  verbind met het accesspoint en stel wifi in"));
      break;
    case Screen::NoAvr:
      Serial.println(F("  wifi ok, receiver niet bereikbaar"));
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

void uiSetRotation(bool) {}   // de seriële weergave draait nergens om
