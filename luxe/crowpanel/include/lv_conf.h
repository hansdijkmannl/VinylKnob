/**
 * LVGL-instellingen voor het CrowPanel.
 *
 * Bewust kort: lv_conf_internal.h van LVGL geeft elke optie die hier niet staat
 * een verstandige standaardwaarde. Wat hieronder staat is dus precies wat voor
 * dit bord afwijkt, en niets meer.
 *
 * Gevonden via -DLV_CONF_INCLUDE_SIMPLE; PlatformIO zet include/ op het pad.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

// 16 bits kleur, in dezelfde volgorde als draw16bitRGBBitmap verwacht. Zet je
// LV_COLOR_16_SWAP op 1, dan moet de flush in ui_lvgl.cpp mee veranderen.
#define LV_COLOR_DEPTH   16
#define LV_COLOR_16_SWAP 0

// Werkgeheugen van LVGL zelf (objecten en stijlen, niet de tekenbuffers — die
// staan in PSRAM). 48 kB is ruim voor dit aantal schermen.
#define LV_MEM_CUSTOM 0
#define LV_MEM_SIZE   (48U * 1024U)

// LVGL zijn eigen klok laten aflezen van millis(), scheelt een losse timer.
#define LV_TICK_CUSTOM                1
#define LV_TICK_CUSTOM_INCLUDE        "Arduino.h"
#define LV_TICK_CUSTOM_SYS_TIME_EXPR  (millis())

// Alleen de lettergroottes die we echt tekenen.
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT       &lv_font_montserrat_20

// De QR-code op het koppelscherm. Zit in LVGL zelf, staat standaard uit.
#define LV_USE_QRCODE        1

#define LV_USE_LOG           0
#define LV_USE_PERF_MONITOR  0
#define LV_USE_MEM_MONITOR   0

#endif  // LV_CONF_H
