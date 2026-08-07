#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// What a screen has to be able to do — deliberately separate from *how* it is
// drawn.
//
// The controls (knob.cpp) and the logic (main.cpp) talk only to these
// functions. There are two implementations:
//
//   ui_serial.cpp   writes to the serial port, so the whole control layer can
//                   be built and tested with no display at all.
//   ui_lvgl.cpp     draws it for real.
//
// That separation is not tidiness: the display was the one part that could not
// be written before the hardware was on the desk, and the serial version is
// still the fastest way to debug a gesture.
// ---------------------------------------------------------------------------

// The settings pages, in the order the knob walks through them. First the
// address, because that is the one you came for.
enum SettingsPage : uint8_t {
  SETTINGS_WEB = 0, SETTINGS_WIFI, SETTINGS_PI, SETTINGS_AVR, SETTINGS_BRIGHT,
  SETTINGS_CLOSE,
  SETTINGS_PAGES
};

enum class Screen : uint8_t {
  Volume,      // sleeve as the background, arc around the rim
  Inputs,      // the list of inputs
  Browse,      // browsing the record shelf
  Pairing,     // QR code and address, when something is waiting to be linked
  Settings,    // where to reach it, what it is connected to, and the brightness
  Off,         // switched off; any touch or turn wakes it
  Setup,       // own access point, no Wi-Fi yet
  NoAvr,       // Wi-Fi yes, receiver unreachable
};

// Which screen is showing, as a short name ("volume", "off", ...). It lives in
// main.cpp — that is what tracks the screen state — but is declared here
// because web.cpp needs it for the copy of this panel in the web interface.
// Without it, that copy could only reproduce the volume screen.
const char *uiScreenName();

struct UiState {
  Screen   screen        = Screen::Setup;

  // volume
  float    volumeDb      = -80.0f;
  bool     haveVolume    = false;
  bool     muted         = false;
  bool     powered       = false;
  bool     turning       = false;   // shows the dB reading while turning

  // what is playing
  char     inputLabel[24] = "?";
  char     nowArtist[48]  = "";
  char     nowTitle[48]   = "";
  bool     haveArtwork    = false;
  bool     artworkIsLogo  = false;  // an app logo, not real artwork
  char     sourceApp[24]  = "";     // "YouTube" when there is no artwork
  bool     listening      = false;   // the Pi is recording right now

  // the choice screens
  int      pickIndex      = 0;
  int      pickCount      = 0;
  char     pickLabel[24]  = "";
  char     pickPrev[24]   = "";
  char     pickNext[24]   = "";

  // how many records are waiting to be linked (0 = nothing to do)
  int      pairing        = 0;
  bool     piHot          = false;  // Pi too hot; otherwise show nothing

  // The letter you just jumped to, large on screen. 0 = do not show.
  // It lives here and not in shelf.cpp because it is about showing, not about
  // where you are: how long it stays is a display decision.
  char     shelfLetter    = 0;
  // Would a choice in the shelf be a link right now? Then the screen says so,
  // because otherwise you point at something without knowing you are recording
  // it permanently.
  bool     shelfLinkable  = false;
  // Browsing is narrowed to the records this track could be on, rather than the
  // whole shelf. The heading says so and the letter ring goes away — jumping by
  // letter through four records is the same as turning.
  bool     shelfNarrowed  = false;
  // A track that is on more than one of your records, waiting for you to say
  // which. The now-playing screen has to show that it is asking, or the answer
  // never comes: a sleeve that looks settled is one nobody goes and corrects.
  uint8_t  choiceCount    = 0;
  bool     justLinked     = false;   // just linked; confirm briefly

  // network
  char     ip[16]         = "";
  int      rssi           = 0;

  // -- settings, turned through with the knob -------------------------------
  // Everything a phone would tell you, on the one screen this device has. It
  // exists because the address is the thing you need at exactly the moment you
  // cannot look it up: right after Wi-Fi is set up, standing at the shelf with
  // no idea what the router gave it.
  uint8_t  settingsPage   = 0;
  bool     settingsAdjust = false;   // press held the page: turning now changes it
  uint8_t  brightness     = 100;
  bool     brainUp        = false;
  char     brainHost[40]  = "";
  char     wifiSsid[33]   = "";

};

void uiBegin();
void uiRender(const UiState &state);   // only call when something changed
void uiTick();                          // every loop; animations and touches

// Rotate the screen 180 degrees without a restart. Useful when the enclosure
// is the other way round and you want to try it.
void uiSetRotation(bool upsideDown);

// Fine correction, in tenths of a degree, for a panel sitting a few degrees
// off in its mount. LVGL turns a display by whole quarters and cannot turn a
// label at all, so this happens to the finished frame on its way to the glass
// — which costs a second pass over the whole buffer. 0 skips it entirely.
void uiSetAngle(int16_t tenths);


// Touches the screen reports back to the logic.
enum class Touch : uint8_t { None, InputLabel, Artwork, Confirm, Dismiss, Listen,
                             Pairing };
Touch uiTakeTouch();
