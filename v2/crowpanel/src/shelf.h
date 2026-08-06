#pragma once

#include <Arduino.h>
#include <lvgl.h>

// ---------------------------------------------------------------------------
// The record shelf on the panel.
//
// Why this is its own file and not part of artwork.cpp: that one is about a
// single sleeve, the record playing now. This is about hundreds of sleeves of
// which three are on screen at a time, and that is a different problem.
//
// The division is the same as everywhere in this device: the Pi knows things,
// the panel shows them. The names arrive in one go as flat text — 25 kB for a
// whole collection, and splitting lines on a tab costs an ESP32 almost nothing
// where parsing 40 kB of JSON takes seconds. The pictures come one at a time,
// sized by the Pi, and only for the albums you can actually see.
//
// Fetching never happens while you are turning. A knob that spends a hundred
// milliseconds per step waiting on the network feels broken; so the text moves
// with you immediately and the sleeves follow once you hold still.
// ---------------------------------------------------------------------------

// Thumbnail size. All three the same, so one step needs one new picture rather
// than three. Which one is current you see from the border around it and the
// title below, not from its size.
#define SHELF_PX 120

void shelfBegin();

// Fetch the list. Once is enough; false when it failed.
bool shelfLoad(const char *host, uint16_t port);
bool shelfLoaded();
int  shelfCount();

// Where we are, and moving. Wraps around at both ends.
int  shelfIndex();
void shelfMove(int steps);
void shelfSet(int index);

// The artist's first letter ('#' when it is not A-Z).
char shelfLetterAt(int index);

// Jump to the start of the previous or next letter. With hundreds of albums,
// turning one at a time is no way to travel; this is the web interface's jump
// index, driven from the knob.
void shelfJump(int direction);

// The text of the album at this position in the list.
const char *shelfArtist(int index);
const char *shelfTitle(int index);

// The release number, so the sleeve can be fetched full-screen.
uint16_t shelfReleaseId(int index);

// The picture for one of the three slots (0 = left, 1 = middle, 2 = right), or
// nullptr while it has not arrived yet.
const lv_img_dsc_t *shelfArtworkAt(int slot);

// Call every loop: fetches what is missing, but only while you hold still.
// True when something changed and the screen needs redrawing.
bool shelfLoop(const char *host, uint16_t port);
