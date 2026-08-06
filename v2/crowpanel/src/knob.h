#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// The rotary knob: quadrature decoding plus the push button's gestures.
//
// Taken from version 1 and changed in two places: the encoder sits on GPIO
// 42/4 here, and the push button hangs off the PCF8574 rather than the ESP32.
//
// The control model: turning is always volume, including in a list — where it
// is the position. What you want to do without looking lives on the knob, the
// rest on the screen.
// ---------------------------------------------------------------------------

enum class KnobEvent : uint8_t {
  None,
  ShortPress,    // mute on/off
  DoublePress,   // jump to the favourite input
  LongPress,     // amplifier on/off
  WifiReset,     // acht seconden vasthouden
};

struct KnobInput {
  int       steps = 0;                 // steps since the previous call
  bool      turnedWhileHeld = false;   // were those steps taken while held?
  bool      held = false;
  KnobEvent event = KnobEvent::None;
};

void      knobBegin();
KnobInput knobPoll();                  // één keer per lus aanroepen
