/**
 * LVGL settings for the CrowPanel.
 *
 * Deliberately short: LVGL's lv_conf_internal.h gives every option not named
 * here a sensible default. So what follows is exactly what differs for this
 * board, and nothing more.
 *
 * Found via -DLV_CONF_INCLUDE_SIMPLE; PlatformIO puts include/ on the path.
 */
#ifndef LV_CONF_H
#define LV_CONF_H

#include <stdint.h>

// 16-bit colour, in the same order draw16bitRGBBitmap expects. Set
// LV_COLOR_16_SWAP to 1 and the flush in ui_lvgl.cpp has to change with it.
#define LV_COLOR_DEPTH   16
#define LV_COLOR_16_SWAP 0

// LVGL's own working memory (objects and styles, not the draw buffers — those
// live in PSRAM). 48 kB is ample for this many screens.
#define LV_MEM_CUSTOM 0
#define LV_MEM_SIZE   (48U * 1024U)

// Let LVGL read its own clock from millis(); saves a separate timer.
#define LV_TICK_CUSTOM                1
#define LV_TICK_CUSTOM_INCLUDE        "Arduino.h"
#define LV_TICK_CUSTOM_SYS_TIME_EXPR  (millis())

// Only the font sizes we actually draw.
#define LV_FONT_MONTSERRAT_14 1
#define LV_FONT_MONTSERRAT_20 1
#define LV_FONT_MONTSERRAT_28 1
#define LV_FONT_MONTSERRAT_48 1
#define LV_FONT_DEFAULT       &lv_font_montserrat_20

// The QR code on the linking screen. Part of LVGL itself, off by default.
#define LV_USE_QRCODE        1

#define LV_USE_LOG           0
#define LV_USE_PERF_MONITOR  0
#define LV_USE_MEM_MONITOR   0

#endif  // LV_CONF_H
