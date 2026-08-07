// ---------------------------------------------------------------------------
// Screen implementation with LVGL, for the round 480x480 panel.
//
// Turning is always volume, so the volume sits as an arc around the rim on
// *every* screen there is. What you want to do without looking lives on the
// knob; what you have to look at anyway lives on the screen.
//
// Structure: one screen with five layers that take turns being visible. That is
// simpler than lv_scr_load() and skips the transition animation, which adds
// nothing on a round panel.
//
// The objects are created once in uiBegin(); uiRender() only sets texts and
// values. That way the loop never has to allocate.
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <lvgl.h>

#include "board.h"
#include "config.h"
#include "artwork.h"
#include "shelf.h"
#include "settings.h"
#include "ui.h"

// -- colours ----------------------------------------------------------------
#define COL_BACKGROUND 0x101014
#define COL_ACCENT      0xe8a33d
#define COL_TEXT       0xf2f2f4
#define COL_DIM     0x8b8b96
#define COL_TRACK       0x3a3a42
#define COL_WARN   0xc2451f

// The arc spans 270 degrees, with the gap at the bottom.
#define ARC_START 135
#define ARC_END  405

static Touch pending = Touch::None;

// -- the layers -------------------------------------------------------------
static lv_obj_t *lyNow, *lyInputs, *lyBrowse, *lyQr, *lyMsg, *lySet;
static lv_obj_t *arc, *lblVol, *lblTitle, *lblArtist, *lblInput, *lblMute, *discNoArtwork;
static lv_obj_t *lblSource, *lblHot;
static lv_obj_t *imgArtwork, *scrim, *plateCentre, *plateBottom, *lblNoArtwork, *linkDot, *listenButton;
static lv_obj_t *linkTouch;
static lv_obj_t *lblPickHead, *lblPickAbove, *lblPickCurrent, *lblPickBelow;

// The record shelf. As many letters as the alphabet plus one slot for anything
// outside it; the ring can never need more places than that.
#define SHELF_RING_MAX 27
static lv_obj_t *shelfSlot[3], *shelfThumb[3];
static lv_obj_t *lblShelfHead, *lblShelfTitle, *lblShelfArtist, *lblShelfCount;
static lv_obj_t *shelfBackPlate, *lblShelfBack;
static lv_obj_t *shelfRing[SHELF_RING_MAX];
static lv_obj_t *lblShelfLetter, *letterVeil;

// The large typeface from font_shelf_letter.c.
LV_FONT_DECLARE(font_shelf_letter);
static lv_obj_t *lblQrIp, *lblQrHost, *lblQrHead, *qr;
static lv_obj_t *lblMsgHead, *lblMsgText;
static lv_obj_t *lblSetHead, *lblSetBody, *lblSetHint, *lblSetBig, *setArc;

// LVGL draws into PSRAM: two full screens of 480x480x2 = 460 kB each, the way
// Elecrow does it. Smaller buffers in internal memory are faster, but this is
// the arrangement known to work on this panel.
static lv_disp_draw_buf_t drawBuf;
static lv_color_t *buf1 = nullptr;
static lv_color_t *buf2 = nullptr;

// ---------------------------------------------------------------------------
// Wiring LVGL to the board
// ---------------------------------------------------------------------------
// -- fine rotation ----------------------------------------------------------
//
// LVGL turns a display by whole quarters and nothing in between, and it cannot
// turn a label at all. So a panel that ended up a few degrees off in its mount
// cannot be corrected anywhere in the widget tree: the sleeve and the arc would
// come round and every piece of text would stay where it was.
//
// The one place where everything is already together is the finished frame, on
// its way to the glass. Rotating there costs a second pass over the whole
// buffer, which is why it is measured rather than assumed — see flushStats().
//
// Small angles are kinder than they look. Stepping along a destination row
// moves the source by (cos, -sin) per pixel, and at four degrees sin is 0.07:
// the source row changes only every fourteenth pixel, so the reads stay almost
// sequential and PSRAM is not asked to jump about.
static int32_t rotSin = 0, rotCos = 1 << 16;      // Q16, of minus the angle
static int16_t rotTenths = 0;
static uint16_t rowBuf[SCREEN_W];                  // one row, in internal RAM

// Where the glass actually is, per row. The panel is round and the buffer is
// square, so a fifth of every frame is corner that sits behind the bezel. There
// is no point rotating pixels nobody can see, and skipping them is a fifth off
// the whole pass.
static int16_t spanFrom[SCREEN_H], spanTo[SCREEN_H];

static void buildSpans() {
  const int32_t r = SCREEN_W / 2, cy = SCREEN_H / 2;
  for (int32_t dy = 0; dy < SCREEN_H; dy++) {
    const int32_t d = dy - cy;
    int32_t half = 0;
    // Integer square root of r*r - d*d, no floating point in a startup loop.
    for (int32_t v = r * r - d * d; half * half <= v; half++) {}
    half--;
    spanFrom[dy] = (int16_t)(r - half);
    spanTo[dy]   = (int16_t)(r + half);
    if (spanFrom[dy] < 0) spanFrom[dy] = 0;
    if (spanTo[dy] > SCREEN_W - 1) spanTo[dy] = SCREEN_W - 1;
  }
}

// Blend two RGB565 pixels, f in 0..31.
//
// The usual trick: red and blue sit far enough apart in the word to be
// interpolated in one go without spilling into each other, so this is two
// multiplies instead of six, and no unpacking to bytes and back.
static inline __attribute__((always_inline))
uint16_t blend565(uint16_t a, uint16_t b, int32_t f) {
  const int32_t arb = a & 0xF81F, agr = a & 0x07E0;
  const int32_t brb = b & 0xF81F, bgr = b & 0x07E0;
  const int32_t rb = (arb + (((brb - arb) * f) >> 5)) & 0xF81F;
  const int32_t g  = (agr + (((bgr - agr) * f) >> 5)) & 0x07E0;
  return (uint16_t)(rb | g);
}

static void __attribute__((optimize("O3"))) IRAM_ATTR
flushRotated(lv_color_t *px) {
  // Counter-rotate every destination pixel to find where it came from. The
  // centre is the centre of the glass, because that is what the mount turned
  // around.
  //
  // Bilinear, and in IRAM at -O3, which is what makes it affordable.
  //
  // Interpolating between the two rows only was the first try, on the argument
  // that the staircase runs that way and the other direction slips by less than
  // a pixel across a row. That holds at three degrees. At six it does not: the
  // source advances 0.9945 pixels per step, so a row slips two and a half
  // pixels and two or three columns are doubled — scattered differently on
  // every row, which is exactly the ragged look on vertical strokes.
  //
  // So all four neighbours after all. Plain, that measured 241 ms a frame and
  // was too slow to keep; the blends were the cost, not the reads. Compiling
  // this one function for speed and putting it in internal RAM, where it is not
  // fighting the flash cache for the same bus PSRAM is on, is what brought it
  // back within reach — see the numbers in ../README.md.
  const int32_t cx = SCREEN_W / 2, cy = SCREEN_H / 2;
  const uint16_t *src = (const uint16_t *)px;

  for (int32_t dy = 0; dy < SCREEN_H; dy++) {
    const int32_t x0 = spanFrom[dy], x1 = spanTo[dy];
    if (x1 < x0) continue;
    // Start of the visible part of the row, in Q16 source coordinates.
    int32_t sx = (cx << 16) + (x0 - cx) * rotCos + (dy - cy) * rotSin;
    int32_t sy = (cy << 16) - (x0 - cx) * rotSin + (dy - cy) * rotCos;

    for (int32_t dx = x0; dx <= x1; dx++) {
      const int32_t ix = sx >> 16, iy = sy >> 16;
      // One short of the bottom, because the sample reaches into the next row.
      // Outside is black; on a round screen that sits in the corners behind the
      // bezel, where nobody ever sees it.
      if (ix < 0 || ix >= SCREEN_W - 1 || iy < 0 || iy >= SCREEN_H - 1) {
        rowBuf[dx - x0] = 0;
      } else {
        const uint16_t *r0 = src + iy * SCREEN_W + ix;
        const int32_t fx = (sx >> 11) & 0x1F;
        rowBuf[dx - x0] = blend565(blend565(r0[0], r0[1], fx),
                                   blend565(r0[SCREEN_W], r0[SCREEN_W + 1], fx),
                                   (sy >> 11) & 0x1F);
      }
      sx += rotCos;
      sy -= rotSin;
    }
#if (LV_COLOR_16_SWAP != 0)
    gfx->draw16bitBeRGBBitmap(x0, dy, rowBuf, x1 - x0 + 1, 1);
#else
    gfx->draw16bitRGBBitmap(x0, dy, rowBuf, x1 - x0 + 1, 1);
#endif
  }
}

static void flushCb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *px) {
  if (rotTenths != 0) {
    // full_refresh is on whenever the angle is, so this area is the whole
    // screen. Rotating a partial one would land it in the wrong place.
    flushRotated(px);
  } else {
    const uint32_t w = area->x2 - area->x1 + 1;
    const uint32_t h = area->y2 - area->y1 + 1;
#if (LV_COLOR_16_SWAP != 0)
    gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t *)px, w, h);
#else
    gfx->draw16bitRGBBitmap(area->x1, area->y1, (uint16_t *)px, w, h);
#endif
  }
  lv_disp_flush_ready(drv);
}

static void touchCb(lv_indev_drv_t *, lv_indev_data_t *data) {
  int16_t x, y;
  if (boardTouch(x, y)) {
    // Do not mirror here on a rotated screen: LVGL already does that in
    // lv_indev.c once disp_drv.rotated is 180. Doing it here too cancelled the
    // two out and every tap landed on the mirror image — exactly the bug that
    // stopped the listen button responding.
    //
    // The fine angle is a different matter: LVGL knows nothing about it, so the
    // finger has to be turned back by hand. Same rotation as the picture, the
    // other way round, or every tap lands where the button used to be.
    if (rotTenths != 0) {
      const int32_t cx = SCREEN_W / 2, cy = SCREEN_H / 2;
      const int32_t rx = x - cx, ry = y - cy;
      x = (int16_t)(cx + ((rx * rotCos + ry * rotSin) >> 16));
      y = (int16_t)(cy + ((-rx * rotSin + ry * rotCos) >> 16));
    }
    data->point.x = x;
    data->point.y = y;
    data->state   = LV_INDEV_STATE_PRESSED;
  } else {
    data->state = LV_INDEV_STATE_RELEASED;
  }
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------
static lv_obj_t *makeLayer() {
  lv_obj_t *o = lv_obj_create(lv_scr_act());
  lv_obj_remove_style_all(o);
  lv_obj_set_size(o, SCREEN_W, SCREEN_H);
  lv_obj_center(o);
  lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
  return o;
}

static lv_obj_t *makeLabel(lv_obj_t *parent, const lv_font_t *font, uint32_t colour,
                           lv_align_t align, lv_coord_t dx, lv_coord_t dy) {
  lv_obj_t *l = lv_label_create(parent);
  lv_obj_set_style_text_font(l, font, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(colour), 0);
  lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
  lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
  lv_obj_set_width(l, SCREEN_W - 150);
  lv_obj_align(l, align, dx, dy);
  lv_label_set_text(l, "");
  return l;
}

static void tapCb(lv_event_t *e) {
  pending = (Touch)(uintptr_t)lv_event_get_user_data(e);
}

static void makeTappable(lv_obj_t *o, Touch what) {
  lv_obj_add_flag(o, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(o, tapCb, LV_EVENT_CLICKED, (void *)(uintptr_t)what);
}

// ---------------------------------------------------------------------------
void uiBegin() {
  boardBegin();
  lv_init();

  const size_t bytes = sizeof(lv_color_t) * SCREEN_W * SCREEN_H;
  buf1 = (lv_color_t *)heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
  buf2 = (lv_color_t *)heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
  if (!buf1) {
    // No point continuing without PSRAM: there is nothing to draw into.
    Serial.println(F("[screen] no PSRAM for the draw buffers"));
    return;
  }
  lv_disp_draw_buf_init(&drawBuf, buf1, buf2, SCREEN_W * SCREEN_H);

  static lv_disp_drv_t dispDrv;
  lv_disp_drv_init(&dispDrv);
  dispDrv.hor_res  = SCREEN_W;
  dispDrv.ver_res  = SCREEN_H;
  dispDrv.flush_cb = flushCb;
  dispDrv.draw_buf = &drawBuf;
  // LVGL handles the rotation. The alternative was flipping the ST7701's scan
  // direction in register 0x36, but that table comes unchanged from Arduino_GFX
  // and is best left alone. At 180 degrees the operation is nothing more than
  // writing the pixels out in reverse anyway.
  dispDrv.sw_rotate = 1;
  dispDrv.rotated   = settings.rotated ? LV_DISP_ROT_180 : LV_DISP_ROT_NONE;
  // A fine angle turns the finished frame, so the flush has to be handed the
  // whole of it. Rotating one of LVGL's partial areas would put it on the glass
  // somewhere it does not belong. Costs nothing when the angle is zero, which
  // is why it is conditional and why changing it from zero needs a restart.
  dispDrv.full_refresh = settings.screenAngle != 0;
  buildSpans();
  uiSetAngle(settings.screenAngle);
  lv_disp_drv_register(&dispDrv);

  static lv_indev_drv_t indevDrv;
  lv_indev_drv_init(&indevDrv);
  indevDrv.type    = LV_INDEV_TYPE_POINTER;
  indevDrv.read_cb = touchCb;
  lv_indev_drv_register(&indevDrv);

  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);
  lv_obj_clear_flag(lv_scr_act(), LV_OBJ_FLAG_SCROLLABLE);

  // -- layer 1: what is playing ----------------------------------------------
  lyNow = makeLayer();

  // The sleeve fills the whole screen and sits at the bottom of the stack: the
  // record is the background, not a stamp in the middle. Creation order decides
  // stacking in LVGL, so this has to come before the arc and the texts.
  imgArtwork = lv_img_create(lyNow);
  lv_obj_center(imgArtwork);
  lv_obj_add_flag(imgArtwork, LV_OBJ_FLAG_HIDDEN);
  makeTappable(imgArtwork, Touch::Artwork);

  // A scrim over it, or the dB reading disappears into a light sleeve. Fixed
  // rather than clever: on a small round screen, predictable legibility is worth
  // more than a scrim that behaves differently for every record.
  scrim = lv_obj_create(lyNow);
  lv_obj_remove_style_all(scrim);
  lv_obj_set_size(scrim, SCREEN_W, SCREEN_H);
  lv_obj_center(scrim);
  lv_obj_set_style_bg_color(scrim, lv_color_hex(COL_BACKGROUND), 0);
  // Light: legibility no longer comes from a dark haze over everything but from
  // soft plates behind the text itself. That way the sleeve stays a sleeve.
  lv_obj_set_style_bg_opa(scrim, LV_OPA_20, 0);
  lv_obj_add_flag(scrim, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(scrim, LV_OBJ_FLAG_CLICKABLE);

  // A soft plate behind the dB reading and the title. Only where text sits, so
  // the rest of the sleeve is untouched.
  plateCentre = lv_obj_create(lyNow);
  lv_obj_remove_style_all(plateCentre);
  lv_obj_set_size(plateCentre, 320, 132);
  lv_obj_align(plateCentre, LV_ALIGN_CENTER, 0, 16);
  lv_obj_set_style_radius(plateCentre, 66, 0);
  lv_obj_set_style_bg_color(plateCentre, lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(plateCentre, LV_OPA_50, 0);
  lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(plateCentre, LV_OBJ_FLAG_CLICKABLE);

  // With no sleeve, a dark disc with a music symbol, so there is always
  // something in the middle instead of a hole.
  discNoArtwork = lv_obj_create(lyNow);
  lv_obj_remove_style_all(discNoArtwork);
  lv_obj_set_size(discNoArtwork, 232, 232);
  lv_obj_center(discNoArtwork);
  lv_obj_set_style_radius(discNoArtwork, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(discNoArtwork, lv_color_hex(0x1c1c22), 0);
  lv_obj_set_style_bg_opa(discNoArtwork, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(discNoArtwork, lv_color_hex(COL_TRACK), 0);
  lv_obj_set_style_border_width(discNoArtwork, 1, 0);
  makeTappable(discNoArtwork, Touch::Artwork);

  lblNoArtwork = lv_label_create(discNoArtwork);
  lv_obj_center(lblNoArtwork);
  lv_obj_set_style_text_font(lblNoArtwork, &lv_font_montserrat_48, 0);
  lv_obj_set_style_text_color(lblNoArtwork, lv_color_hex(COL_TRACK), 0);
  lv_label_set_text(lblNoArtwork, LV_SYMBOL_AUDIO);

  arc = lv_arc_create(lyNow);
  lv_obj_set_size(arc, 456, 456);
  lv_obj_center(arc);
  lv_arc_set_bg_angles(arc, ARC_START, ARC_END);
  lv_arc_set_range(arc, 0, 1000);
  lv_arc_set_value(arc, 0);
  lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
  lv_obj_clear_flag(arc, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_arc_width(arc, 10, LV_PART_MAIN);
  lv_obj_set_style_arc_width(arc, 10, LV_PART_INDICATOR);
  lv_obj_set_style_arc_color(arc, lv_color_hex(COL_TRACK), LV_PART_MAIN);
  lv_obj_set_style_arc_color(arc, lv_color_hex(COL_ACCENT), LV_PART_INDICATOR);

  lblVol     = makeLabel(lyNow, &lv_font_montserrat_48, COL_TEXT,    LV_ALIGN_CENTER,  0, -14);
  lblTitle   = makeLabel(lyNow, &lv_font_montserrat_20, COL_TEXT,    LV_ALIGN_CENTER,  0,  30);
  lblArtist = makeLabel(lyNow, &lv_font_montserrat_14, COL_DIM,  LV_ALIGN_CENTER,  0,  56);
  lblInput  = makeLabel(lyNow, &lv_font_montserrat_28, COL_ACCENT,   LV_ALIGN_CENTER,  0, 146);
  // Where the title came from, when there is no sleeve. With YouTube it stays
  // text — that app supplies no image — and then "YouTube" above the video title
  // is more informative than an empty space.
  lblSource    = makeLabel(lyNow, &lv_font_montserrat_14, COL_ACCENT,    LV_ALIGN_CENTER,  0, -60);
  lblMute    = makeLabel(lyNow, &lv_font_montserrat_20, COL_WARN, LV_ALIGN_CENTER, 0, -100);
  lv_label_set_text(lblMute, "MUTE");
  lv_obj_add_flag(lblMute, LV_OBJ_FLAG_HIDDEN);

  // The input name's touch area has to be larger than the letters themselves:
  // on a touchscreen you want around 44 points, not the height of one line.
  // The listen button goes at the bottom: at the top it lay over the sleeve.
  // Here it sits under the input name, where there is text anyway, and can be
  // tapped to force a lookup. A generous target, because on a round screen the
  // top edge is cramped.
  // A dark plate underneath: on a light sleeve the icon was otherwise nearly
  // invisible, and tinting it with the sleeve only makes that worse.
  plateBottom = lv_obj_create(lyNow);
  lv_obj_remove_style_all(plateBottom);
  lv_obj_set_size(plateBottom, 132, 56);
  lv_obj_align(plateBottom, LV_ALIGN_CENTER, 0, 192);
  lv_obj_set_style_radius(plateBottom, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(plateBottom, lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(plateBottom, LV_OPA_60, 0);
  lv_obj_clear_flag(plateBottom, LV_OBJ_FLAG_CLICKABLE);

  listenButton = lv_label_create(lyNow);
  lv_obj_set_style_text_font(listenButton, &lv_font_montserrat_28, 0);
  lv_obj_set_style_text_color(listenButton, lv_color_hex(COL_TRACK), 0);
  lv_obj_set_style_text_align(listenButton, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_size(listenButton, 96, 62);
  lv_obj_set_style_pad_top(listenButton, 14, 0);
  lv_obj_align(listenButton, LV_ALIGN_CENTER, 0, 192);
  lv_label_set_text(listenButton, LV_SYMBOL_AUDIO);
  makeTappable(listenButton, Touch::Listen);

  // A warning when the Pi runs up against its limits. No permanent gauge:
  // degrees on a screen meant for album art is clutter, and the Pi normally sits
  // well within range. The number itself is in the web interface.
  lblHot = makeLabel(lyNow, &lv_font_montserrat_20, COL_WARN, LV_ALIGN_CENTER, -60, 192);
  lv_label_set_text(lblHot, LV_SYMBOL_WARNING);
  lv_obj_add_flag(lblHot, LV_OBJ_FLAG_HIDDEN);

  // A small dot above the input name when records are waiting to be linked. Not
  // a screen that pushes itself forward: you see it if you look, and tapping the
  // dot takes you to the QR code.
  linkDot = lv_obj_create(lyNow);
  lv_obj_remove_style_all(linkDot);
  lv_obj_set_size(linkDot, 10, 10);
  lv_obj_align(linkDot, LV_ALIGN_CENTER, 52, 192);
  lv_obj_set_style_radius(linkDot, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(linkDot, lv_color_hex(COL_ACCENT), 0);
  lv_obj_set_style_bg_opa(linkDot, LV_OPA_COVER, 0);
  lv_obj_add_flag(linkDot, LV_OBJ_FLAG_HIDDEN);
  // An invisible area around it: you do not hit ten pixels with a finger, and
  // since the sleeve now leads to the shelf, this is the only way to the QR
  // code.
  linkTouch = lv_obj_create(lyNow);
  lv_obj_remove_style_all(linkTouch);
  lv_obj_set_size(linkTouch, 52, 52);
  lv_obj_align(linkTouch, LV_ALIGN_CENTER, 52, 192);
  lv_obj_add_flag(linkTouch, LV_OBJ_FLAG_HIDDEN);
  makeTappable(linkTouch, Touch::Pairing);

  lv_obj_set_height(lblInput, 54);
  lv_obj_set_style_pad_top(lblInput, 10, 0);
  makeTappable(lblInput, Touch::InputLabel);

  // -- layer 2: choosing an input --------------------------------------------
  lyInputs = makeLayer();
  lblPickHead   = makeLabel(lyInputs, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0, -130);
  lblPickAbove = makeLabel(lyInputs, &lv_font_montserrat_20, COL_TRACK,   LV_ALIGN_CENTER, 0,  -62);
  lblPickCurrent    = makeLabel(lyInputs, &lv_font_montserrat_28, COL_ACCENT,  LV_ALIGN_CENTER, 0,    0);
  lblPickBelow = makeLabel(lyInputs, &lv_font_montserrat_20, COL_TRACK,   LV_ALIGN_CENTER, 0,   62);
  lv_label_set_text(lblPickHead, "INPUT");
  lv_obj_set_height(lblPickCurrent, 64);
  lv_obj_set_style_pad_top(lblPickCurrent, 16, 0);
  makeTappable(lblPickCurrent, Touch::Confirm);
  lv_obj_set_height(lblPickHead, 48);
  makeTappable(lblPickHead, Touch::Dismiss);

  // -- layer 3: the record shelf -----------------------------------------------
  //
  // The same arrangement as in the web interface: sleeves in a row, the jump
  // index as a ring of letters along the inner rim with the gap at the bottom.
  // A straight bar of letters fights a circle — it wraps onto two lines and
  // collides with the edge — while along the rim the middle stays free.
  lyBrowse = makeLayer();
  lblShelfHead = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_DIM,
                         LV_ALIGN_CENTER, 0, -150);
  lv_label_set_text(lblShelfHead, "SHELF");

  // No position arc around the rim. The letter ring already says roughly where
  // you are and the count says it exactly, so a second amber thing at the edge
  // was only competing with the letter you are on.

  // Three sleeves, all the same size. Which one is current you see from the
  // brightness and the title below — not from the size, because then one step
  // would need three new pictures instead of one, and not from a coloured
  // border either: on this screen amber means the letter you are at.
  static const int SHELF_X[3] = {-144, 0, 144};
  for (int i = 0; i < 3; i++) {
    shelfSlot[i] = lv_obj_create(lyBrowse);
    lv_obj_remove_style_all(shelfSlot[i]);
    lv_obj_set_size(shelfSlot[i], SHELF_PX + 8, SHELF_PX + 8);
    lv_obj_align(shelfSlot[i], LV_ALIGN_CENTER, SHELF_X[i], -14);
    lv_obj_set_style_radius(shelfSlot[i], 12, 0);
    lv_obj_set_style_bg_color(shelfSlot[i], lv_color_hex(0x1c1c22), 0);
    lv_obj_set_style_bg_opa(shelfSlot[i], LV_OPA_COVER, 0);
    lv_obj_clear_flag(shelfSlot[i], LV_OBJ_FLAG_SCROLLABLE);

    shelfThumb[i] = lv_img_create(shelfSlot[i]);
    lv_obj_center(shelfThumb[i]);
    // The two outer ones dimmed, so the middle comes forward without touching
    // the sizes.
    if (i != 1) {
      lv_obj_set_style_img_recolor(shelfThumb[i], lv_color_hex(COL_BACKGROUND), 0);
      lv_obj_set_style_img_recolor_opa(shelfThumb[i], LV_OPA_50, 0);
    }
  }

  lblShelfTitle   = makeLabel(lyBrowse, &lv_font_montserrat_20, COL_TEXT,
                             LV_ALIGN_CENTER, 0, 88);
  lblShelfArtist = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_DIM,
                             LV_ALIGN_CENTER, 0, 116);
  lblShelfCount  = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_TRACK,
                             LV_ALIGN_CENTER, 0, 150);

  // The way out. Pressing the knob in here *picks* an album, and with an
  // unrecognised record playing that press writes a fingerprint you cannot
  // unwrite — so browsing without choosing needed a control of its own rather
  // than the eighteen-second timeout. It sits in the gap of the letter ring, at
  // the same spot as the listen button on the volume screen, so the bottom of
  // the glass is always the one place a button lives.
  //
  // A filled plate rather than an outline, and white on it. The first version
  // drew it in COL_TRACK — the colour of the *unlit* part of the arc — on a
  // barely-there plate, which is exactly the vocabulary this screen uses for
  // "not active": it read as a greyed-out button.
  shelfBackPlate = lv_obj_create(lyBrowse);
  lv_obj_remove_style_all(shelfBackPlate);
  lv_obj_set_size(shelfBackPlate, 138, 52);
  lv_obj_align(shelfBackPlate, LV_ALIGN_CENTER, 0, 192);
  lv_obj_set_style_radius(shelfBackPlate, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(shelfBackPlate, lv_color_hex(COL_TRACK), 0);
  lv_obj_set_style_bg_opa(shelfBackPlate, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(shelfBackPlate, lv_color_hex(COL_DIM), 0);
  lv_obj_set_style_border_width(shelfBackPlate, 2, 0);
  lv_obj_set_style_border_opa(shelfBackPlate, LV_OPA_COVER, 0);
  lv_obj_clear_flag(shelfBackPlate, LV_OBJ_FLAG_CLICKABLE);

  lblShelfBack = lv_label_create(lyBrowse);
  lv_obj_set_style_text_font(lblShelfBack, &lv_font_montserrat_20, 0);
  lv_obj_set_style_text_color(lblShelfBack, lv_color_hex(COL_TEXT), 0);
  lv_obj_set_style_text_align(lblShelfBack, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_size(lblShelfBack, 138, 52);
  lv_obj_set_style_pad_top(lblShelfBack, 14, 0);
  lv_obj_align(lblShelfBack, LV_ALIGN_CENTER, 0, 192);
  lv_label_set_text(lblShelfBack, LV_SYMBOL_LEFT "  BACK");
  makeTappable(lblShelfBack, Touch::Dismiss);

  // The letter you are jumping to, large on screen. The ring stays small — that
  // shows *where* you are — but while jumping you want to read without hunting,
  // and fourteen pixels along the rim is not enough for that.
  //
  // There is a dark field behind it: the letter sits over the sleeves and would
  // otherwise disappear on a light one.
  letterVeil = lv_obj_create(lyBrowse);
  lv_obj_remove_style_all(letterVeil);
  lv_obj_set_size(letterVeil, SCREEN_W, SCREEN_H);
  lv_obj_center(letterVeil);
  lv_obj_set_style_bg_color(letterVeil, lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(letterVeil, LV_OPA_70, 0);
  lv_obj_clear_flag(letterVeil, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_flag(letterVeil, LV_OBJ_FLAG_HIDDEN);

  lblShelfLetter = lv_label_create(lyBrowse);
  lv_obj_set_style_text_font(lblShelfLetter, &font_shelf_letter, 0);
  lv_obj_set_style_text_color(lblShelfLetter, lv_color_hex(COL_ACCENT), 0);
  lv_obj_align(lblShelfLetter, LV_ALIGN_CENTER, 0, -10);
  lv_label_set_text(lblShelfLetter, "A");
  lv_obj_add_flag(lblShelfLetter, LV_OBJ_FLAG_HIDDEN);

  // The ring of letters. Upright rather than rotating with the rim: LVGL cannot
  // rotate labels (only images), and at this size upright reads better than a
  // letter lying on its side anyway.
  for (int i = 0; i < SHELF_RING_MAX; i++) {
    shelfRing[i] = lv_label_create(lyBrowse);
    lv_obj_set_style_text_font(shelfRing[i], &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(shelfRing[i], lv_color_hex(COL_TRACK), 0);
    lv_label_set_text(shelfRing[i], "");
    lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
  }

  // -- layer 4: linking ------------------------------------------------------
  lyQr = makeLayer();
  lblQrHead = makeLabel(lyQr, &lv_font_montserrat_20, COL_ACCENT, LV_ALIGN_CENTER, 0, -132);
  lv_label_set_text(lblQrHead, "UNKNOWN RECORD");
  qr = lv_qrcode_create(lyQr, 168, lv_color_hex(0x101014), lv_color_white());
  lv_obj_align(qr, LV_ALIGN_CENTER, 0, -14);
  lv_obj_set_style_border_width(qr, 6, 0);
  lv_obj_set_style_border_color(qr, lv_color_white(), 0);
  lblQrIp   = makeLabel(lyQr, &lv_font_montserrat_20, COL_TEXT,   LV_ALIGN_CENTER, 0, 116);
  lblQrHost = makeLabel(lyQr, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0, 146);
  lv_label_set_text(lblQrHost, "scan to link it");
  makeTappable(lyQr, Touch::Dismiss);

  // -- layer 5: settings -----------------------------------------------------
  // Its own layer rather than borrowing the message screen: this one is read
  // from a metre away while you stand there, so everything on it is a size up
  // and in full white instead of the grey used for asides. The only grey left
  // is the bottom line, which says what the knob does — that is genuinely an
  // aside, and it is the same line on every page.
  lySet = makeLayer();
  lblSetHead = makeLabel(lySet, &lv_font_montserrat_20, COL_ACCENT, LV_ALIGN_CENTER, 0, -120);
  lblSetBig  = makeLabel(lySet, &lv_font_montserrat_48, COL_TEXT,   LV_ALIGN_CENTER, 0,  -30);
  lblSetBody = makeLabel(lySet, &lv_font_montserrat_20, COL_TEXT,   LV_ALIGN_CENTER, 0,   10);
  lv_obj_set_style_text_align(lblSetBody, LV_TEXT_ALIGN_CENTER, 0);
  lblSetHint = makeLabel(lySet, &lv_font_montserrat_14, COL_DIM,    LV_ALIGN_CENTER, 0,  128);
  lv_obj_set_style_text_align(lblSetHint, LV_TEXT_ALIGN_CENTER, 0);

  // The same ring the volume uses, for the same reason: on a round screen the
  // rim is the one place a quantity can sit without crowding the words.
  setArc = lv_arc_create(lySet);
  lv_obj_set_size(setArc, 456, 456);
  lv_obj_center(setArc);
  lv_arc_set_bg_angles(setArc, ARC_START, ARC_END);
  lv_arc_set_range(setArc, 0, 100);
  lv_obj_remove_style(setArc, NULL, LV_PART_KNOB);
  lv_obj_clear_flag(setArc, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_arc_width(setArc, 10, LV_PART_MAIN);
  lv_obj_set_style_arc_width(setArc, 10, LV_PART_INDICATOR);
  lv_obj_set_style_arc_color(setArc, lv_color_hex(COL_TRACK), LV_PART_MAIN);
  lv_obj_set_style_arc_color(setArc, lv_color_hex(COL_ACCENT), LV_PART_INDICATOR);
  makeTappable(lySet, Touch::Dismiss);

  // -- layer 6: messages (setup, no receiver) --------------------------------
  lyMsg = makeLayer();
  lblMsgHead   = makeLabel(lyMsg, &lv_font_montserrat_20, COL_ACCENT,  LV_ALIGN_CENTER, 0, -40);
  lblMsgText = makeLabel(lyMsg, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0,  10);

  lv_obj_clear_flag(lyMsg, LV_OBJ_FLAG_HIDDEN);
  lv_label_set_text(lblMsgHead, "VinylKnob");
  lv_label_set_text(lblMsgText, "starting up...");
  lv_timer_handler();
}

// ---------------------------------------------------------------------------
static void show(lv_obj_t *which) {
  lv_obj_t *alle[] = {lyNow, lyInputs, lyBrowse, lyQr, lyMsg, lySet};
  for (lv_obj_t *o : alle) {
    if (o == which) lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
    else            lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
  }
}

void uiRender(const UiState &s) {
  if (!buf1) return;

  switch (s.screen) {
    case Screen::Volume: {
      show(lyNow);

      // The arc runs from silence to your own ceiling, not to 0 dB. Otherwise
      // it barely moves: listening happens between -60 and -20.
      const float top = (float)settings.volMaxDb;
      const float frac = s.haveVolume
          ? (s.volumeDb - (-80.0f)) / (top - (-80.0f))
          : 0.0f;
      lv_arc_set_value(arc, (int16_t)(constrain(frac, 0.0f, 1.0f) * 1000));

      // The arc takes the most prominent colour from the sleeve, as the web
      // version does. With no sleeve it falls back to the default amber.
      const uint32_t colour = artworkAccent();
      static uint32_t previousColour = 0;
      if (colour != previousColour) {
        previousColour = colour;
        Serial.printf("[screen] arc set to #%06X\n", (unsigned)colour);
      }
      lv_obj_set_style_arc_color(arc, lv_color_hex(colour), LV_PART_INDICATOR);
      lv_obj_set_style_bg_color(linkDot, lv_color_hex(colour), 0);
      lv_obj_set_style_arc_opa(arc, s.muted ? LV_OPA_30 : LV_OPA_COVER,
                               LV_PART_INDICATOR);

      // Show the dB reading only while turning. If a sleeve follows, the screen
      // stays clear: the sleeve is the image, and laying artist and title over
      // it only takes away from that. Only when there is no sleeve do we fill
      // the emptiness with the name.
      // Real artwork *is* the image and wants no text over it. An app logo is
      // there precisely because there is no artwork — then you do want the
      // title, or you see a brand and not what is playing.
      const bool realArtwork = artworkImage() && !s.artworkIsLogo;
      const bool showText = !s.turning && s.nowTitle[0] && !realArtwork;
      if (s.turning || (!showText && !s.nowTitle[0])) {
        lv_obj_clear_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtist, LV_OBJ_FLAG_HIDDEN);
        // Deliberately not lv_label_set_text_fmt with %.1f: LVGL's own printf
        // leaves floating point out by default (LV_SPRINTF_USE_FLOAT is 0) and
        // then puts a literal "f" on the screen. Plain libc snprintf instead.
        lv_obj_clear_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtist, LV_OBJ_FLAG_HIDDEN);
        if (s.haveVolume) {
          char blob[12];
          snprintf(blob, sizeof(blob), "%.1f", s.volumeDb);
          lv_label_set_text(lblVol, blob);
        } else {
          lv_label_set_text(lblVol, "--");
        }
      } else if (showText) {
        lv_obj_add_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblTitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblArtist, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(lblTitle, s.nowTitle);
        lv_label_set_text(lblArtist, s.nowArtist);
      } else {
        lv_obj_add_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtist, LV_OBJ_FLAG_HIDDEN);
      }

      // The source name only with text and no sleeve; with a sleeve, that is
      // the image and a label above it adds nothing. With a logo, no name
      // either: the logo *is* the name, and saying the same thing twice only
      // costs room on a screen that has none.
      if (s.choiceCount > 1) {
        // The track was recognised and it is on more than one of your records.
        // Say so where the source name would go, because the alternative is a
        // screen that looks settled: you would never know it was asking, and
        // the answer would never come. The sleeve is deliberately absent for
        // the same reason — any one of them would be a guess.
        lv_label_set_text_fmt(lblSource, "ON %d OF YOURS - TAP TO PICK",
                              (int)s.choiceCount);
        lv_obj_set_style_text_color(lblSource, lv_color_hex(COL_ACCENT), 0);
        lv_obj_clear_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
      } else if (showText && s.sourceApp[0] && !s.artworkIsLogo) {
        lv_label_set_text(lblSource, s.sourceApp);
        lv_obj_clear_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_color(lblSource, lv_color_hex(artworkAccent()), 0);
      } else {
        lv_obj_add_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
      }

      // The plate behind the text only when there is text or a dB reading.
      if (s.turning || showText) lv_obj_clear_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
      else                        lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);

      if (s.muted) lv_obj_clear_flag(lblMute, LV_OBJ_FLAG_HIDDEN);
      else         lv_obj_add_flag(lblMute, LV_OBJ_FLAG_HIDDEN);

      // The sleeve. artwork.cpp fetches it; here we only show what is there.
      const lv_img_dsc_t *image = artworkImage();
      if (image) {
        lv_img_set_src(imgArtwork, image);
        lv_obj_clear_flag(imgArtwork, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(scrim, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(discNoArtwork, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(imgArtwork, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(scrim, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(discNoArtwork, LV_OBJ_FLAG_HIDDEN);
      }

      // Lit while the Pi is recording; otherwise dimmed but still visible, so
      // you know it can be tapped. White when idle, the accent colour once it
      // listens. White is always legible on a dark plate; tinting it with the
      // sleeve was the very reason it used to disappear.
      lv_obj_set_style_text_color(listenButton,
          lv_color_hex(s.listening ? artworkAccent() : COL_TEXT), 0);

      // Just linked: confirm it briefly. You have recorded something the device
      // remembers permanently, and silently jumping back to the volume is too
      // little acknowledgement of that.
      if (s.justLinked) {
        lv_label_set_text(lblSource, "LINKED");
        lv_obj_set_style_text_color(lblSource, lv_color_hex(COL_ACCENT), 0);
        lv_obj_clear_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
      }

      if (s.piHot) lv_obj_clear_flag(lblHot, LV_OBJ_FLAG_HIDDEN);
      else         lv_obj_add_flag(lblHot, LV_OBJ_FLAG_HIDDEN);

      if (s.pairing > 0) {
        lv_obj_clear_flag(linkDot, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(linkTouch, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(linkDot, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(linkTouch, LV_OBJ_FLAG_HIDDEN);
      }

      lv_label_set_text(lblInput, s.inputLabel);
      lv_obj_set_style_text_color(lblInput,
          lv_color_hex(s.powered ? artworkAccent() : COL_TRACK), 0);
      break;
    }

    case Screen::Inputs: {
      show(lyInputs);
      lv_label_set_text(lblPickAbove, s.pickPrev);
      lv_label_set_text(lblPickCurrent,    s.pickLabel);
      lv_label_set_text(lblPickBelow, s.pickNext);
      break;
    }

    case Screen::Off:
      // Everything off. The backlight is switched off in main.cpp; a black
      // screen is left here so nothing glows afterwards.
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "");
      lv_label_set_text(lblMsgText, "");
      break;

    case Screen::Browse: {
      show(lyBrowse);
      const int n = shelfCount();
      if (!n) {
        lv_label_set_text(lblShelfTitle, "Nothing yet");
        lv_label_set_text(lblShelfArtist, shelfLoaded() ? "the shelf is empty"
                                                        : "fetching the shelf...");
        lv_label_set_text(lblShelfCount, "");
        for (int i = 0; i < 3; i++) lv_obj_add_flag(shelfSlot[i], LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < SHELF_RING_MAX; i++)
          lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
        break;
      }

      // The heading says what pressing will do. Without it you point at an
      // album and record a link without knowing — or the other way round, wait
      // for something that is not going to happen.
      if (s.shelfNarrowed) {
        // Not the shelf but a question, and a short one. Which record it is
        // matters more here than saying a link will happen: you know that
        // already, or you would not be looking at three sleeves instead of
        // five hundred.
        lv_label_set_text(lblShelfHead, "WHICH ONE IS ON?");
        lv_obj_set_style_text_color(lblShelfHead, lv_color_hex(COL_ACCENT), 0);
      } else if (s.shelfLinkable) {
        lv_label_set_text(lblShelfHead, "LINK TO WHAT IS PLAYING");
        lv_obj_set_style_text_color(lblShelfHead, lv_color_hex(COL_ACCENT), 0);
      } else {
        lv_label_set_text(lblShelfHead, "SHELF");
        lv_obj_set_style_text_color(lblShelfHead, lv_color_hex(COL_DIM), 0);
      }

      const int here = shelfIndex();
      for (int slot = 0; slot < 3; slot++) {
        if (!shelfSlotVisible(slot)) {
          lv_obj_add_flag(shelfSlot[slot], LV_OBJ_FLAG_HIDDEN);
          lv_obj_add_flag(shelfThumb[slot], LV_OBJ_FLAG_HIDDEN);
          continue;
        }
        lv_obj_clear_flag(shelfSlot[slot], LV_OBJ_FLAG_HIDDEN);
        const lv_img_dsc_t *image = shelfArtworkAt(slot);
        if (image) {
          lv_img_set_src(shelfThumb[slot], image);
          lv_obj_clear_flag(shelfThumb[slot], LV_OBJ_FLAG_HIDDEN);
        } else {
          // Still on its way: show the empty slot, not the previous record's.
          lv_obj_add_flag(shelfThumb[slot], LV_OBJ_FLAG_HIDDEN);
        }
      }

      lv_label_set_text(lblShelfTitle, shelfTitle(here));
      lv_label_set_text(lblShelfArtist, shelfArtist(here));
      lv_label_set_text_fmt(lblShelfCount, "%d / %d", here + 1, n);

      // The ring: one letter per initial that occurs in the shelf, spread over
      // 300 degrees with the gap at the bottom. Only repositioned when the list
      // changes — moving 27 objects on every step would be a waste.
      // Narrowed there is no ring: jumping by letter through four sleeves is
      // the same as turning, and the letters would suggest the rest of the shelf
      // is still there to walk to.
      static int ringBuiltFor = -1;
      static char ringLetters[SHELF_RING_MAX];
      static int  ringCount = 0;
      if (s.shelfNarrowed) {
        for (int i = 0; i < SHELF_RING_MAX; i++)
          lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
        ringBuiltFor = -1;   // rebuild once the whole shelf comes back
        ringCount = 0;
      } else if (ringBuiltFor != n) {
        ringBuiltFor = n;
        ringCount = 0;
        char previous = 0;
        for (int i = 0; i < n && ringCount < SHELF_RING_MAX; i++) {
          const char l = shelfLetterAt(i);
          if (l != previous) { ringLetters[ringCount++] = l; previous = l; }
        }
        for (int i = 0; i < SHELF_RING_MAX; i++) {
          if (i >= ringCount) { lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN); continue; }
          const float degrees = -150.0f +
              (ringCount > 1 ? 300.0f * i / (ringCount - 1) : 150.0f);
          const float rad = degrees * 3.14159265f / 180.0f;
          // Upright on a circle of 205: the angle only decides the position.
          const int dx = (int)(205.0f * sinf(rad));
          const int dy = (int)(-205.0f * cosf(rad));
          char blob[2] = {ringLetters[i], '\0'};
          lv_label_set_text(shelfRing[i], blob);
          lv_obj_align(shelfRing[i], LV_ALIGN_CENTER, dx, dy);
          lv_obj_clear_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
        }
      }
      const char now = shelfLetterAt(here);
      for (int i = 0; i < ringCount; i++)
        lv_obj_set_style_text_color(shelfRing[i],
            lv_color_hex(ringLetters[i] == now ? COL_ACCENT : COL_TRACK), 0);

      // The large letter only while jumping; main.cpp decides for how long.
      if (s.shelfLetter) {
        char big[2] = {s.shelfLetter, '\0'};
        lv_label_set_text(lblShelfLetter, big);
        lv_obj_clear_flag(letterVeil, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblShelfLetter, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(letterVeil, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblShelfLetter, LV_OBJ_FLAG_HIDDEN);
      }
      break;
    }

    case Screen::Pairing: {
      show(lyQr);
      lv_label_set_text(lblQrHead, "UNKNOWN RECORD");
      lv_obj_set_style_text_color(lblQrIp, lv_color_hex(COL_TEXT), 0);
      lv_label_set_text(lblQrHost, "scan to link it");
      // The QR points at the brain on the Pi, not at this panel: that is where
      // the queue lives in which you hang a record on a release.
      char adres[64];
      snprintf(adres, sizeof(adres), "http://%s:8790",
               settings.brainHost[0] ? settings.brainHost : s.ip);
      lv_qrcode_update(qr, adres, strlen(adres));
      lv_label_set_text_fmt(lblQrIp, "%d to link", s.pairing);
      break;
    }

    // Everything a phone would tell you, on the one screen this thing has.
    //
    // Turn to page through, press to leave — except on the last page, where
    // pressing hands the knob to the brightness and pressing again gives it
    // back. Every page says what the knob does, because there is nothing else
    // here to tell you.
    case Screen::Settings: {
      const bool bright = s.settingsPage == SETTINGS_BRIGHT;

      if (s.settingsPage == SETTINGS_WEB) {
        show(lyQr);
        // One address, not two. The panel's own page is reachable through the
        // web interface anyway, and a screen offering you a choice of addresses
        // when you asked "where do I go" is a screen that answered a different
        // question.
        const bool viaPi = s.brainHost[0] != '\0';
        char address[64];
        snprintf(address, sizeof(address), "http://%s", viaPi ? s.brainHost : s.ip);
        lv_label_set_text(lblQrHead, viaPi ? "WEB INTERFACE" : "THIS PANEL");
        lv_qrcode_update(qr, address, strlen(address));
        lv_label_set_text(lblQrIp, viaPi ? s.brainHost : s.ip);
        lv_obj_set_style_text_color(lblQrIp, lv_color_hex(COL_TEXT), 0);
        lv_label_set_text(lblQrHost, "turn for more, press to close");
        break;
      }

      show(lySet);
      // The ring only where there is a quantity to put on it.
      if (bright) {
        lv_arc_set_value(setArc, s.brightness);
        lv_obj_clear_flag(setArc, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(setArc, LV_OBJ_FLAG_HIDDEN);
      }
      // And the big number only next to that ring; everywhere else the body
      // text is what you came to read.
      if (bright) lv_obj_clear_flag(lblSetBig, LV_OBJ_FLAG_HIDDEN);
      else        lv_obj_add_flag(lblSetBig, LV_OBJ_FLAG_HIDDEN);

      switch (s.settingsPage) {
        case SETTINGS_WIFI:
          lv_label_set_text(lblSetHead, "WI-FI");
          lv_label_set_text_fmt(lblSetBody, "%s\n%s\n%d dBm",
                                s.wifiSsid[0] ? s.wifiSsid : "not set",
                                s.ip[0] ? s.ip : "no address", s.rssi);
          break;

        case SETTINGS_PI:
          lv_label_set_text(lblSetHead, "THE PI");
          lv_label_set_text_fmt(lblSetBody, "%s\n%s",
                                s.brainHost[0] ? s.brainHost : "not found yet",
                                s.brainUp ? "answering" : "no answer");
          break;

        case SETTINGS_AVR:
          lv_label_set_text(lblSetHead, "RECEIVER");
          lv_label_set_text_fmt(lblSetBody, "%s\n%s\n%s",
                                settings.avrHost[0] ? settings.avrHost : "no address set",
                                s.inputLabel[0] ? s.inputLabel : "-",
                                s.powered ? "on" : "off");
          break;

        case SETTINGS_BRIGHT:
          lv_label_set_text(lblSetHead, "BRIGHTNESS");
          lv_label_set_text_fmt(lblSetBig, "%d%%", s.brightness);
          lv_label_set_text(lblSetBody, "");
          break;

        case SETTINGS_CLOSE:
          lv_label_set_text(lblSetHead, "CLOSE");
          lv_label_set_text(lblSetBody, "back to the volume");
          break;
      }

      // What the knob does, in the same place every time. On the brightness
      // page it is two different things depending on whether you have taken
      // hold of it yet, and that is exactly the bit that needs saying out loud:
      // one press to take it, turn, one press to give it back.
      if (bright && s.settingsAdjust)
        lv_label_set_text(lblSetHint, "turn to change  ·  press when it is right");
      else if (bright)
        lv_label_set_text(lblSetHint, "press once, then turn to change it");
      else if (s.settingsPage == SETTINGS_CLOSE)
        lv_label_set_text(lblSetHint, "press to go back");
      else
        lv_label_set_text(lblSetHint, "turn for more, press to close");
      lv_obj_set_style_text_color(lblSetHint,
          lv_color_hex(bright && s.settingsAdjust ? COL_ACCENT : COL_DIM), 0);
      break;
    }

    case Screen::Setup:
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "No Wi-Fi yet");
      lv_label_set_text_fmt(lblMsgText, "Connect to %s\nand open %s\n\npress the knob for the address",
                            AP_SSID, s.ip[0] ? s.ip : "192.168.4.1");
      break;

    case Screen::NoAvr:
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "No receiver");
      lv_label_set_text_fmt(lblMsgText, "%s\nIs Network Control set to \"Always On\"?\n\npress the knob for the address",
                            settings.avrHost[0] ? settings.avrHost : "no address set");
      break;
  }
}

void uiSetAngle(int16_t tenths) {
  // Anything past a few degrees is a mount to fix, not a picture to bend, and
  // beyond that the uncovered corners come into view on a screen that is not
  // perfectly round. Clamped rather than rejected: a wrong number should not
  // leave the screen unreadable.
  if (tenths >  150) tenths =  150;
  if (tenths < -150) tenths = -150;
  rotTenths = tenths;
  const float rad = tenths * 0.1f * 3.14159265f / 180.0f;
  rotCos = (int32_t)(cosf(rad) * 65536.0f);
  rotSin = (int32_t)(sinf(rad) * 65536.0f);
}

void uiSetRotation(bool upsideDown) {
  lv_disp_t *d = lv_disp_get_default();
  if (d) lv_disp_set_rotation(d, upsideDown ? LV_DISP_ROT_180 : LV_DISP_ROT_NONE);
}

void uiTick() {
  if (buf1) lv_timer_handler();
}

Touch uiTakeTouch() {
  const Touch t = pending;
  pending = Touch::None;
  return t;
}
