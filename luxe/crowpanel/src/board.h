#pragma once

#include <Arduino.h>
#include <Arduino_GFX_Library.h>

// ---------------------------------------------------------------------------
// Bringing the panel up: power, resets, the ST7701 and the touch chip.
//
// This is the part that was missing for a long time because it cannot be
// guessed. It comes verbatim from Elecrow's own sketch; see board.cpp for what
// welke volgorde moet.
//
// Everything above this in the stack (ui_lvgl.cpp) talks only to these three
// functions, so the drawing code needs to know nothing about the board.
// ---------------------------------------------------------------------------

extern Arduino_ST7701_RGBPanel *gfx;

// Wire must be started and pcfBegin() already called.
void boardBegin();

// 0 = off, 255 = full.
void boardBacklight(uint8_t level);

// True while a finger is down; x and y in screen pixels.
bool boardTouch(int16_t &x, int16_t &y);
