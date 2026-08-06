#pragma once

#include <Arduino.h>

// Volume is tracked in half-steps everywhere: 0..196.
//   dB = halfSteps / 2.0 - 80.0
struct AvrState {
  bool     connected    = false;
  bool     powered      = false;   // main zone on
  bool     muted        = false;
  bool     haveVolume   = false;
  int      volHalfSteps = 0;
  int      volMaxHalf   = 196;     // overwritten by MVMAX
  char     input[24]    = "?";     // protocol code as the AVR reports it
  char     inputLabel[24] = "?";   // your label, if the code is in the list
  uint32_t revision     = 0;       // increments on every change
};

extern AvrState avrState;

void avrLoop();

// Send a raw command ("SIPHONO", "MV?"). False when there is no connection.
bool avrSend(const char *cmd);

// Set the volume. Throttled inside avrLoop, so this is safe to call on every
// turn of the knob without drowning the receiver.
void avrSetVolumeHalf(int halfSteps);

// Where the volume stops: the lower of MVMAX and your own ceiling.
int avrVolumeCeilingHalf();

// The volume we are on our way to (or the current one when nothing is
// queued).
int avrPendingVolumeHalf();

// Drop the connection so avrLoop reconnects. Use after the receiver's address
// has changed.
void avrReconnect();

// Increments on every command sent; the status LED blinks on this.
uint32_t avrTxCount();
