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

enum class Screen : uint8_t {
  Volume,      // sleeve as the background, arc around the rim
  Inputs,      // ingangenlijst
  Browse,      // platenkast doorbladeren
  Pairing,     // QR code and address, when something is waiting to be linked
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

  // keuzeschermen
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
  bool     justLinked     = false;   // just linked; confirm briefly

  // netwerk
  char     ip[16]         = "";
  int      rssi           = 0;
};

void uiBegin();
void uiRender(const UiState &state);   // only call when something changed
void uiTick();                          // every loop; animations and touches

// Rotate the screen 180 degrees without a restart. Useful when the enclosure
// is the other way round and you want to try it.
void uiSetRotation(bool upsideDown);

// Touches the screen reports back to the logic.
enum class Touch : uint8_t { None, InputLabel, Artwork, Confirm, Dismiss, Listen,
                             Pairing };
Touch uiTakeTouch();
