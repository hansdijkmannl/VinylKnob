#pragma once

#include <Arduino.h>
#include <lvgl.h>

// ---------------------------------------------------------------------------
// The Apple TV's apps on the panel.
//
// The same shape as the record shelf and for the same reason — three tiles,
// turn to move, press to choose — but a much smaller problem: two dozen apps
// instead of five hundred records, so the whole list is fetched as JSON and
// every logo fits in memory at once. No letter ring, no eviction, no cache
// policy worth the name.
//
// What it is *for* is the part worth stating. Everything else this can do to an
// Apple TV, the remote on the sofa does better; the one thing it does better is
// skip the navigating. One turn and one press and you are in the app, instead
// of walking a grid with a direction pad.
//
// Not every app has a logo. Apple's own are not in the App Store, so those show
// their name instead — which is honest, and better than a hole where a picture
// is never going to arrive. The Pi says up front which is which.
// ---------------------------------------------------------------------------

#define APPS_MAX  40
#define APPS_PX  120        // same tile as the shelf, so the layout is shared

void appsBegin();

// Fetch the list from the Pi. False if it failed; try again later.
bool appsLoad(const char *host, uint16_t port);
bool appsLoaded();
int  appsCount();
int  appsIndex();
void appsMove(int steps);

const char *appsName(int index);
const char *appsId(int index);

// The logo for one of the three positions on screen, or null when this app has
// none and when it has not arrived yet. Slot 0 is left, 1 the middle, 2 right.
const lv_img_dsc_t *appsIconAt(int slot);
bool appsHasIcon(int index);

// Fetch what is missing, one logo per call, and only while you hold still.
// True when something new arrived and the screen should be redrawn.
bool appsLoop(const char *host, uint16_t port);
