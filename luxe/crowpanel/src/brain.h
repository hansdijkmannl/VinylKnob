#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// What is playing, fetched from the Pi.
//
// Why over HTTP and not over the USB cable that is already there: that cable
// does carry serial (it shows up as /dev/ttyACM0 on the Pi), but using it would
// mean inventing a protocol with framing, a serial client on the Pi, and giving
// up the monitor this panel is debugged with. The panel is on Wi-Fi already —
// it has to be, for telnet to the receiver — and the Pi already serves HTTP.
// One GET is enough.
//
// The Pi is the side that knows what is playing; the panel only asks. So there
// is no recognition logic here, only fetching.
// ---------------------------------------------------------------------------

struct BrainState {
  bool bereikbaar = false;
  bool playing    = false;      // a record is on
  bool listening   = false;      // the Pi is recording or looking up
  bool onShelf     = false;      // found in your own Discogs collection
  // A lookup came up empty and is still open: point at an album in the shelf
  // now and the two get linked, teaching the device this side.
  bool canLink = false;
  bool haveArtwork   = false;      // there is a sleeve waiting on /hoes
  bool artworkIsLogo = false;      // ...but it is the app logo, not real artwork
  char artist[48] = "";
  char title[64]   = "";
  char album[64]   = "";
  char app[24]     = "";      // "YouTube", when the Apple TV is the source
  bool hot       = false;      // Pi on its top fan step, or throttling
  uint8_t linkable = 0;         // records waiting to be linked
  uint32_t revision = 0;        // increments as soon as anything changes
};

extern BrainState brainState;

// Set by main.cpp: does listening make sense right now? Sent with every poll,
// so the Pi is not trying to recognise the Apple TV.
extern bool brainWantsToListen;

void brainBegin();
void brainLoop();               // call every loop; it paces itself

// Link this album to the record playing now that was not recognised. The Pi
// records it and turns the clip into fingerprints, so the same side is
// recognised without a service next time. False when it failed.
bool brainLink(uint16_t releaseId);

// Ask the Pi to listen now. Used when the input switches to your favourite:
// that is the moment you put the needle down.
void brainAskLookup();
