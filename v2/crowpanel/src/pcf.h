#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// PCF8574 I/O expander at 0x21.
//
// More hangs off it on this board than you would expect: the rotary knob's push
// button, but also power and reset for the LCD and the touch chip. Hence one
// shared helper instead of three places doing the same thing.
//
// The PCF8574 is quasi-bidirectional: a pin only reads correctly if you have
// written a 1 to it first. So we keep a shadow byte in which every input
// stays high.
// ---------------------------------------------------------------------------

void    pcfBegin();                          // Wire must already be started
void    pcfWritePin(uint8_t pin, bool high);
bool    pcfReadPin(uint8_t pin);
uint8_t pcfReadAll();
