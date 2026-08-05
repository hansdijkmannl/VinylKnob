#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// De draaiknop: quadratuur plus de gebaren van de drukknop.
//
// Overgenomen uit versie 1 en aangepast op twee punten: de encoder zit hier op
// GPIO 42/4, en de drukknop hangt niet aan de ESP32 maar aan de PCF8574.
//
// Het bedieningsmodel is dat van luxe/mockup/: draaien is altijd volume, ook
// in een keuzescherm — daar is het de lijstpositie. Wat je zonder kijken wil
// doen zit op de knop, de rest op het scherm.
// ---------------------------------------------------------------------------

enum class KnobEvent : uint8_t {
  None,
  ShortPress,    // mute aan/uit
  DoublePress,   // naar de favoriete ingang
  LongPress,     // versterker aan/uit
  WifiReset,     // acht seconden vasthouden
};

struct KnobInput {
  int       steps = 0;                 // stappen sinds de vorige aanroep
  bool      turnedWhileHeld = false;   // waren die stappen met de knop ingedrukt?
  bool      held = false;
  KnobEvent event = KnobEvent::None;
};

void      knobBegin();
KnobInput knobPoll();                  // één keer per lus aanroepen
