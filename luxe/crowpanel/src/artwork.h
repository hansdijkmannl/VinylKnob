#pragma once

#include <Arduino.h>
#include <lvgl.h>

// ---------------------------------------------------------------------------
// De albumhoes ophalen en decoderen.
//
// The Pi delivers it ready-sized: scaling on an ESP32 costs memory and time
// that are better spent elsewhere, and the Pi does it in tens of milliseconds.
// So all that is left here is decoding.
//
// The result is an LVGL image in PSRAM that stays until a different record
// comes along, which is why it is fetched exactly once per record.
// ---------------------------------------------------------------------------

// Full-bleed: the sleeve is the background of the volume screen, not a little
// disc in the middle. 480x480x2 = 460 kB in PSRAM, alongside LVGL's two draw
// buffers — under one and a half megabytes of the eight, together.
#define ARTWORK_PX 480

void artworkBegin();

// Fetch and decode the sleeve from this address. True if there is one to show.
bool artworkLoad(const char *host, uint16_t poort);

// The same, but for an album you pointed at in the shelf. Same buffer and the
// same accent calculation; only the source differs.
bool artworkLoadAlbum(const char *host, uint16_t poort, uint16_t releaseId);

// Throw it away; the empty record label shows again.
void artworkClear();

// The image for LVGL, or nullptr when there is no sleeve.
const lv_img_dsc_t *artworkImage();

// The most prominent colour in the sleeve, as 0xRRGGBB; the default when there
// is none. Meant for the volume arc, so it matches the record.
uint32_t artworkAccent();
