#pragma once

#include <Arduino.h>
#include <Arduino_GFX_Library.h>

// ---------------------------------------------------------------------------
// Het paneel aan de praat krijgen: voeding, resets, ST7701 en de aanraakchip.
//
// Dit is het deel dat lang ontbrak omdat het niet te beraden viel. Het komt nu
// letterlijk uit Elecrow's eigen schets; zie board.cpp voor wat er precies in
// welke volgorde moet.
//
// Alles hierboven in de stapel (ui_lvgl.cpp) praat alleen met deze drie
// functies, zodat de tekencode niets van het bord hoeft te weten.
// ---------------------------------------------------------------------------

extern Arduino_ST7701_RGBPanel *gfx;

// Wire moet gestart zijn en pcfBegin() gedaan.
void boardBegin();

// 0 = uit, 255 = vol.
void boardBacklight(uint8_t level);

// True zolang er een vinger op ligt; x en y in schermpixels.
bool boardTouch(int16_t &x, int16_t &y);
