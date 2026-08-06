// ---------------------------------------------------------------------------
// Scherm-implementatie met LVGL, voor het ronde 480×480-paneel.
//
// Volgt het model uit luxe/mockup/: draaien is altijd volume, dus het volume
// staat als boog langs de rand in élk scherm dat er is. Wat je zonder kijken
// wil doen zit op de knop; wat je toch aankijkt zit op het scherm.
//
// Opbouw: één scherm met vijf lagen die om beurten zichtbaar zijn. Dat is
// eenvoudiger dan lv_scr_load() en scheelt de animatie tussen schermen, die op
// een rond paneel toch niets toevoegt.
//
// De objecten worden één keer in uiBegin() gemaakt; uiRender() zet alleen nog
// teksten en waarden. Zo hoeft de lus niets te alloceren.
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <lvgl.h>

#include "board.h"
#include "config.h"
#include "artwork.h"
#include "shelf.h"
#include "settings.h"
#include "ui.h"

// -- kleuren, uit luxe/mockup/ ----------------------------------------------
#define COL_BACKGROUND 0x101014
#define COL_ACCENT      0xe8a33d
#define COL_TEXT       0xf2f2f4
#define COL_DIM     0x8b8b96
#define COL_TRACK       0x3a3a42
#define COL_WARN   0xc2451f

// De boog beslaat 270°, met de opening onderaan — net als in de mockup.
#define ARC_START 135
#define ARC_END  405

static Touch pending = Touch::None;

// -- de lagen ---------------------------------------------------------------
static lv_obj_t *lyNow, *lyInputs, *lyBrowse, *lyQr, *lyMsg;
static lv_obj_t *arc, *lblVol, *lblTitle, *lblArtist, *lblInput, *lblMute, *discNoArtwork;
static lv_obj_t *lblSource, *lblHot;
static lv_obj_t *imgArtwork, *scrim, *plateCentre, *plateBottom, *lblNoArtwork, *linkDot, *listenButton;
static lv_obj_t *linkTouch;
static lv_obj_t *lblPickHead, *lblPickAbove, *lblPickCurrent, *lblPickBelow;

// De platenkast. Zoveel letters als het alfabet plus een vakje voor alles wat
// daar niet in valt; meer plekken dan dat kan de ring niet nodig hebben.
#define SHELF_RING_MAX 27
static lv_obj_t *shelfSlot[3], *shelfThumb[3], *shelfArc;
static lv_obj_t *lblShelfHead, *lblShelfTitle, *lblShelfArtist, *lblShelfCount;
static lv_obj_t *shelfRing[SHELF_RING_MAX];
static lv_obj_t *lblShelfLetter, *letterVeil;

// Het grote lettertype uit font_kastletter.c.
LV_FONT_DECLARE(font_shelf_letter);
static lv_obj_t *lblQrIp, *lblQrHost, *qr;
static lv_obj_t *lblMsgHead, *lblMsgText;

// LVGL tekent in PSRAM: twee volledige schermen van 480×480×2 = 460 kB elk.
// Zo doet Elecrow het ook. Kleinere buffers in intern geheugen zijn sneller,
// maar dit is de opzet waarvan bekend is dat hij op dit paneel werkt.
static lv_disp_draw_buf_t drawBuf;
static lv_color_t *buf1 = nullptr;
static lv_color_t *buf2 = nullptr;

// ---------------------------------------------------------------------------
// LVGL aan het bord knopen
// ---------------------------------------------------------------------------
static void flushCb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *px) {
  const uint32_t w = area->x2 - area->x1 + 1;
  const uint32_t h = area->y2 - area->y1 + 1;
#if (LV_COLOR_16_SWAP != 0)
  gfx->draw16bitBeRGBBitmap(area->x1, area->y1, (uint16_t *)px, w, h);
#else
  gfx->draw16bitRGBBitmap(area->x1, area->y1, (uint16_t *)px, w, h);
#endif
  lv_disp_flush_ready(drv);
}

static void touchCb(lv_indev_drv_t *, lv_indev_data_t *data) {
  int16_t x, y;
  if (boardTouch(x, y)) {
    // Niet zelf spiegelen bij een gedraaid scherm: LVGL doet dat al in
    // lv_indev.c zodra disp_drv.rotated op 180 staat. Deed ik het hier ook, dan
    // hieven de twee elkaar op en landde elke tik op het spiegelbeeld — precies
    // de fout waardoor de luisterknop niet meer reageerde.
    data->point.x = x;
    data->point.y = y;
    data->state   = LV_INDEV_STATE_PRESSED;
  } else {
    data->state = LV_INDEV_STATE_RELEASED;
  }
}

// ---------------------------------------------------------------------------
// Bouwstenen
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
    // Zonder PSRAM heeft doorgaan geen zin: dan is er niets om in te tekenen.
    Serial.println(F("[scherm] geen PSRAM voor de tekenbuffers"));
    return;
  }
  lv_disp_draw_buf_init(&drawBuf, buf1, buf2, SCREEN_W * SCREEN_H);

  static lv_disp_drv_t dispDrv;
  lv_disp_drv_init(&dispDrv);
  dispDrv.hor_res  = SCREEN_W;
  dispDrv.ver_res  = SCREEN_H;
  dispDrv.flush_cb = flushCb;
  dispDrv.draw_buf = &drawBuf;
  // Draaien doet LVGL zelf. Het alternatief was de scanrichting van de ST7701
  // omzetten in register 0x36, maar die tabel komt ongewijzigd uit Arduino_GFX
  // en daar wil ik vanaf blijven. Bij 180 graden is de bewerking bovendien
  // niets meer dan de pixels omgekeerd wegschrijven.
  dispDrv.sw_rotate = 1;
  dispDrv.rotated   = settings.rotated ? LV_DISP_ROT_180 : LV_DISP_ROT_NONE;
  lv_disp_drv_register(&dispDrv);

  static lv_indev_drv_t indevDrv;
  lv_indev_drv_init(&indevDrv);
  indevDrv.type    = LV_INDEV_TYPE_POINTER;
  indevDrv.read_cb = touchCb;
  lv_indev_drv_register(&indevDrv);

  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);
  lv_obj_clear_flag(lv_scr_act(), LV_OBJ_FLAG_SCROLLABLE);

  // -- laag 1: wat er speelt -------------------------------------------------
  lyNow = makeLayer();

  // De hoes vult het hele scherm en ligt onderop — zo hoort het volgens
  // luxe/mockup/: de plaat is de achtergrond, niet een postzegel in het midden.
  // Volgorde van aanmaken bepaalt bij LVGL de stapeling, dus dit moet vóór de
  // boog en de teksten.
  imgArtwork = lv_img_create(lyNow);
  lv_obj_center(imgArtwork);
  lv_obj_add_flag(imgArtwork, LV_OBJ_FLAG_HIDDEN);
  makeTappable(imgArtwork, Touch::Artwork);

  // Een sluier eroverheen, anders verdwijnt het dB-getal in een lichte hoes.
  // Vast en niet slim: op een klein rond scherm is een voorspelbare leesbaarheid
  // meer waard dan een sluier die per plaat anders uitpakt.
  scrim = lv_obj_create(lyNow);
  lv_obj_remove_style_all(scrim);
  lv_obj_set_size(scrim, SCREEN_W, SCREEN_H);
  lv_obj_center(scrim);
  lv_obj_set_style_bg_color(scrim, lv_color_hex(COL_BACKGROUND), 0);
  // Licht: de leesbaarheid komt niet meer van een donkere waas over alles, maar
  // van zachte plaatjes achter de tekst zelf. Zo blijft de hoes hoes.
  lv_obj_set_style_bg_opa(scrim, LV_OPA_20, 0);
  lv_obj_add_flag(scrim, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(scrim, LV_OBJ_FLAG_CLICKABLE);

  // Zacht plaatje achter het dB-getal en de titel. Alleen daar waar tekst staat,
  // zodat de rest van de hoes onaangetast blijft.
  plateCentre = lv_obj_create(lyNow);
  lv_obj_remove_style_all(plateCentre);
  lv_obj_set_size(plateCentre, 320, 132);
  lv_obj_align(plateCentre, LV_ALIGN_CENTER, 0, 16);
  lv_obj_set_style_radius(plateCentre, 66, 0);
  lv_obj_set_style_bg_color(plateCentre, lv_color_hex(COL_BACKGROUND), 0);
  lv_obj_set_style_bg_opa(plateCentre, LV_OPA_50, 0);
  lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(plateCentre, LV_OBJ_FLAG_CLICKABLE);

  // Zonder hoes een donkere schijf met een muzieksymbool, zodat er altijd iets
  // in het midden staat in plaats van een gat.
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
  // Waar de titel vandaan komt, als er geen hoes is. Bij YouTube blijft het bij
  // tekst — die app geeft geen afbeelding door — en dan is "YouTube" boven de
  // videotitel informatiever dan een leeg vlak.
  lblSource    = makeLabel(lyNow, &lv_font_montserrat_14, COL_ACCENT,    LV_ALIGN_CENTER,  0, -60);
  lblMute    = makeLabel(lyNow, &lv_font_montserrat_20, COL_WARN, LV_ALIGN_CENTER, 0, -100);
  lv_label_set_text(lblMute, "MUTE");
  lv_obj_add_flag(lblMute, LV_OBJ_FLAG_HIDDEN);

  // Het aanraakvlak van de ingangsnaam moet groter zijn dan de letters zelf:
  // op een aanraakscherm wil je zo'n 44 punten, niet de hoogte van een regel.
  // Luisterknop onderin: bovenaan lag hij over de hoes heen. Hier staat hij
  // onder de ingangsnaam, waar toch al tekst staat., en is zelf aan te
  // tikken om er een af te dwingen. Ruim aanraakvlak, want op een rond scherm
  // is de bovenrand krap.
  // Een donker plaatje eronder: het icoontje stond anders op een lichte hoes
  // vrijwel onzichtbaar, en meekleuren met de hoes maakt dat alleen erger.
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

  // Waarschuwing als de Pi tegen zijn grenzen loopt. Geen permanente meter:
  // graden op een scherm voor albumhoezen is rommel, en de Pi zit normaal ruim
  // binnen zijn bereik. Wil je het getal zien, dan staat het op de orenpagina.
  lblHot = makeLabel(lyNow, &lv_font_montserrat_20, COL_WARN, LV_ALIGN_CENTER, -60, 192);
  lv_label_set_text(lblHot, LV_SYMBOL_WARNING);
  lv_obj_add_flag(lblHot, LV_OBJ_FLAG_HIDDEN);

  // Klein stipje boven de ingangsnaam als er platen op koppeling wachten. Geen
  // scherm dat zichzelf naar voren dringt: je ziet het als je kijkt, en tikken
  // op de hoes brengt je naar de QR-code.
  linkDot = lv_obj_create(lyNow);
  lv_obj_remove_style_all(linkDot);
  lv_obj_set_size(linkDot, 10, 10);
  lv_obj_align(linkDot, LV_ALIGN_CENTER, 52, 192);
  lv_obj_set_style_radius(linkDot, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(linkDot, lv_color_hex(COL_ACCENT), 0);
  lv_obj_set_style_bg_opa(linkDot, LV_OPA_COVER, 0);
  lv_obj_add_flag(linkDot, LV_OBJ_FLAG_HIDDEN);
  // Een onzichtbaar vlak eromheen: tien pixels raak je niet met een vinger, en
  // sinds de hoes naar de platenkast leidt is dit de enige weg naar de QR-code.
  linkTouch = lv_obj_create(lyNow);
  lv_obj_remove_style_all(linkTouch);
  lv_obj_set_size(linkTouch, 52, 52);
  lv_obj_align(linkTouch, LV_ALIGN_CENTER, 52, 192);
  lv_obj_add_flag(linkTouch, LV_OBJ_FLAG_HIDDEN);
  makeTappable(linkTouch, Touch::Pairing);

  lv_obj_set_height(lblInput, 54);
  lv_obj_set_style_pad_top(lblInput, 10, 0);
  makeTappable(lblInput, Touch::InputLabel);

  // -- laag 2: ingang kiezen -------------------------------------------------
  lyInputs = makeLayer();
  lblPickHead   = makeLabel(lyInputs, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0, -130);
  lblPickAbove = makeLabel(lyInputs, &lv_font_montserrat_20, COL_TRACK,   LV_ALIGN_CENTER, 0,  -62);
  lblPickCurrent    = makeLabel(lyInputs, &lv_font_montserrat_28, COL_ACCENT,  LV_ALIGN_CENTER, 0,    0);
  lblPickBelow = makeLabel(lyInputs, &lv_font_montserrat_20, COL_TRACK,   LV_ALIGN_CENTER, 0,   62);
  lv_label_set_text(lblPickHead, "INGANG");
  lv_obj_set_height(lblPickCurrent, 64);
  lv_obj_set_style_pad_top(lblPickCurrent, 16, 0);
  makeTappable(lblPickCurrent, Touch::Confirm);
  lv_obj_set_height(lblPickHead, 48);
  makeTappable(lblPickHead, Touch::Dismiss);

  // -- laag 3: platenkast ----------------------------------------------------
  //
  // Dezelfde opzet als in de webinterface: de hoezen op een rij, de sprongindex
  // als letterring langs de binnenrand met de opening onderaan. Een rechte
  // letterbalk wringt in een cirkel — hij loopt over twee regels en botst met
  // de rand — terwijl langs de omtrek het midden vrij blijft voor de hoezen.
  lyBrowse = makeLayer();
  lblShelfHead = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_DIM,
                         LV_ALIGN_CENTER, 0, -150);
  lv_label_set_text(lblShelfHead, "PLATENKAST");

  // De positieboog, net binnen de letterring.
  shelfArc = lv_arc_create(lyBrowse);
  lv_obj_set_size(shelfArc, 452, 452);
  lv_obj_center(shelfArc);
  lv_arc_set_bg_angles(shelfArc, 0, 360);
  lv_arc_set_range(shelfArc, 0, 1000);
  lv_obj_remove_style(shelfArc, NULL, LV_PART_KNOB);
  lv_obj_clear_flag(shelfArc, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_arc_width(shelfArc, 4, LV_PART_MAIN);
  lv_obj_set_style_arc_width(shelfArc, 4, LV_PART_INDICATOR);
  lv_obj_set_style_arc_opa(shelfArc, LV_OPA_20, LV_PART_MAIN);
  lv_obj_set_style_arc_color(shelfArc, lv_color_hex(COL_TRACK), LV_PART_MAIN);
  lv_obj_set_style_arc_color(shelfArc, lv_color_hex(COL_ACCENT), LV_PART_INDICATOR);

  // Drie hoezen, alle drie even groot. Welke de huidige is zie je aan de rand
  // en aan de titel eronder — niet aan het formaat, want dan zou één stap drie
  // nieuwe plaatjes vergen in plaats van één.
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
    // De twee buitenste gedempt, zodat het midden vooraan staat zonder dat er
    // aan het formaat gesleuteld hoeft te worden.
    if (i != 1) {
      lv_obj_set_style_img_recolor(shelfThumb[i], lv_color_hex(COL_BACKGROUND), 0);
      lv_obj_set_style_img_recolor_opa(shelfThumb[i], LV_OPA_50, 0);
    }
  }
  lv_obj_set_style_border_color(shelfSlot[1], lv_color_hex(COL_ACCENT), 0);
  lv_obj_set_style_border_width(shelfSlot[1], 3, 0);

  lblShelfTitle   = makeLabel(lyBrowse, &lv_font_montserrat_20, COL_TEXT,
                             LV_ALIGN_CENTER, 0, 88);
  lblShelfArtist = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_DIM,
                             LV_ALIGN_CENTER, 0, 116);
  lblShelfCount  = makeLabel(lyBrowse, &lv_font_montserrat_14, COL_TRACK,
                             LV_ALIGN_CENTER, 0, 150);

  // De letter waar je heen springt, groot in beeld. De ring blijft klein — die
  // laat zien wáár je bent — maar tijdens het springen wil je lezen zonder te
  // zoeken, en veertien pixels langs de rand zijn daar te weinig voor.
  //
  // Er ligt een donker vlak achter: de letter staat over de hoezen heen en zou
  // op een lichte hoes anders wegvallen.
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

  // De letterring. Rechtop en niet meedraaiend met de rand: LVGL kan labels
  // niet roteren (alleen afbeeldingen), en rechtop leest op dit formaat toch
  // beter dan een letter die op zijn kant staat.
  for (int i = 0; i < SHELF_RING_MAX; i++) {
    shelfRing[i] = lv_label_create(lyBrowse);
    lv_obj_set_style_text_font(shelfRing[i], &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(shelfRing[i], lv_color_hex(COL_TRACK), 0);
    lv_label_set_text(shelfRing[i], "");
    lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
  }

  // -- laag 4: koppelen ------------------------------------------------------
  lyQr = makeLayer();
  lv_obj_t *qKop = makeLabel(lyQr, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0, -130);
  lv_label_set_text(qKop, "ONBEKENDE PLAAT");
  qr = lv_qrcode_create(lyQr, 168, lv_color_hex(0x101014), lv_color_white());
  lv_obj_align(qr, LV_ALIGN_CENTER, 0, -14);
  lv_obj_set_style_border_width(qr, 6, 0);
  lv_obj_set_style_border_color(qr, lv_color_white(), 0);
  lblQrIp   = makeLabel(lyQr, &lv_font_montserrat_20, COL_TEXT,   LV_ALIGN_CENTER, 0, 116);
  lblQrHost = makeLabel(lyQr, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0, 146);
  lv_label_set_text(lblQrHost, "scan om te koppelen");
  makeTappable(lyQr, Touch::Dismiss);

  // -- laag 5: meldingen (setup, geen receiver) ------------------------------
  lyMsg = makeLayer();
  lblMsgHead   = makeLabel(lyMsg, &lv_font_montserrat_20, COL_ACCENT,  LV_ALIGN_CENTER, 0, -40);
  lblMsgText = makeLabel(lyMsg, &lv_font_montserrat_14, COL_DIM, LV_ALIGN_CENTER, 0,  10);

  lv_obj_clear_flag(lyMsg, LV_OBJ_FLAG_HIDDEN);
  lv_label_set_text(lblMsgHead, "MarantzKnob");
  lv_label_set_text(lblMsgText, "opstarten...");
  lv_timer_handler();
}

// ---------------------------------------------------------------------------
static void show(lv_obj_t *welke) {
  lv_obj_t *alle[] = {lyNow, lyInputs, lyBrowse, lyQr, lyMsg};
  for (lv_obj_t *o : alle) {
    if (o == welke) lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
    else            lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
  }
}

void uiRender(const UiState &s) {
  if (!buf1) return;

  switch (s.screen) {
    case Screen::Volume: {
      show(lyNow);

      // De boog loopt van stilte tot je eigen plafond, niet tot 0 dB. Anders
      // beweegt hij nauwelijks: luisteren doe je tussen -60 en -20.
      const float top = (float)settings.volMaxDb;
      const float frac = s.haveVolume
          ? (s.volumeDb - (-80.0f)) / (top - (-80.0f))
          : 0.0f;
      lv_arc_set_value(arc, (int16_t)(constrain(frac, 0.0f, 1.0f) * 1000));

      // De boog neemt de opvallendste kleur uit de hoes over, net als de
      // webversie. Zonder hoes valt hij terug op de amber uit de mockup.
      const uint32_t colour = artworkAccent();
      static uint32_t previousColour = 0;
      if (colour != previousColour) {
        previousColour = colour;
        Serial.printf("[scherm] boog op #%06X\n", (unsigned)colour);
      }
      lv_obj_set_style_arc_color(arc, lv_color_hex(colour), LV_PART_INDICATOR);
      lv_obj_set_style_bg_color(linkDot, lv_color_hex(colour), 0);
      lv_obj_set_style_arc_opa(arc, s.muted ? LV_OPA_30 : LV_OPA_COVER,
                               LV_PART_INDICATOR);

      // Het dB-getal alleen tonen terwijl je draait. Staat er daarna een hoes,
      // dan blijft het scherm leeg: de hoes is het beeld, en artiest en titel
      // eroverheen zetten haalt daar juist vanaf. Alleen als er géén hoes is
      // vullen we de leegte met de naam.
      // Een echte hoes ís het beeld, daar hoort geen tekst overheen. Een
      // app-logo staat er juist omdát er geen hoes is — dan wil je de titel er
      // wel bij, anders zie je alleen een merk en niet wat er draait.
      const bool realArtwork = artworkImage() && !s.artworkIsLogo;
      const bool showText = !s.turning && s.nowTitle[0] && !realArtwork;
      if (s.turning || (!showText && !s.nowTitle[0])) {
        lv_obj_clear_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitle, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtist, LV_OBJ_FLAG_HIDDEN);
        // Bewust niet lv_label_set_text_fmt met %.1f: LVGL's eigen printf laat
        // drijvende komma standaard weg (LV_SPRINTF_USE_FLOAT staat op 0) en
        // zet dan letterlijk "f" op het scherm. Gewoon snprintf van de libc.
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

      // De bronnaam alleen bij tekst zonder hoes; staat er een hoes, dan is
      // die het beeld en heeft een etiket erboven geen toegevoegde waarde.
      // Bij een logo geen naam erbij: dat logo ís de naam, en twee keer
      // hetzelfde zeggen kost alleen ruimte op een scherm dat het niet heeft.
      if (showText && s.sourceApp[0] && !s.artworkIsLogo) {
        lv_label_set_text(lblSource, s.sourceApp);
        lv_obj_clear_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_color(lblSource, lv_color_hex(artworkAccent()), 0);
      } else {
        lv_obj_add_flag(lblSource, LV_OBJ_FLAG_HIDDEN);
      }

      // Plaatje achter de tekst alleen als er tekst of een dB-getal staat.
      if (s.turning || showText) lv_obj_clear_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);
      else                        lv_obj_add_flag(plateCentre, LV_OBJ_FLAG_HIDDEN);

      if (s.muted) lv_obj_clear_flag(lblMute, LV_OBJ_FLAG_HIDDEN);
      else         lv_obj_add_flag(lblMute, LV_OBJ_FLAG_HIDDEN);

      // De hoes. hoes.cpp haalt hem op; hier alleen tonen wat er ligt.
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

      // Oplichten terwijl de Pi opneemt; anders gedempt maar wel zichtbaar,
      // zodat je weet dat je erop kunt tikken.
      // Wit als hij niets doet, accentkleur zodra hij luistert. Wit is op een
      // donker plaatje altijd leesbaar; meekleuren met de hoes was juist de
      // reden dat hij wegviel.
      lv_obj_set_style_text_color(listenButton,
          lv_color_hex(s.listening ? artworkAccent() : COL_TEXT), 0);

      // Net gekoppeld: dat even bevestigen. Je hebt zojuist iets vastgelegd wat
      // het apparaat blijvend onthoudt, en dan is stilzwijgend terugspringen
      // naar het volume te weinig.
      if (s.justLinked) {
        lv_label_set_text(lblSource, "GEKOPPELD");
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
      // Alles uit. De achtergrondverlichting gaat in main.cpp uit; hier blijft
      // een zwart scherm over zodat er ook niets nagloeit.
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "");
      lv_label_set_text(lblMsgText, "");
      break;

    case Screen::Browse: {
      show(lyBrowse);
      const int n = shelfCount();
      if (!n) {
        lv_label_set_text(lblShelfTitle, "Nog niets");
        lv_label_set_text(lblShelfArtist, shelfLoaded() ? "de kast is leeg"
                                                        : "kast ophalen...");
        lv_label_set_text(lblShelfCount, "");
        for (int i = 0; i < 3; i++) lv_obj_add_flag(shelfSlot[i], LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < SHELF_RING_MAX; i++)
          lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
        break;
      }

      // De kop vertelt wat drukken gaat doen. Zonder dat wijs je een album aan
      // en leg je zonder het te weten een koppeling vast — of andersom, sta je
      // te wachten op iets dat niet gebeurt.
      if (s.shelfLinkable) {
        lv_label_set_text(lblShelfHead, "KOPPEL AAN WAT SPEELT");
        lv_obj_set_style_text_color(lblShelfHead, lv_color_hex(COL_ACCENT), 0);
      } else {
        lv_label_set_text(lblShelfHead, "PLATENKAST");
        lv_obj_set_style_text_color(lblShelfHead, lv_color_hex(COL_DIM), 0);
      }

      const int hier = shelfIndex();
      for (int slot = 0; slot < 3; slot++) {
        lv_obj_clear_flag(shelfSlot[slot], LV_OBJ_FLAG_HIDDEN);
        const lv_img_dsc_t *image = shelfArtworkAt(slot);
        if (image) {
          lv_img_set_src(shelfThumb[slot], image);
          lv_obj_clear_flag(shelfThumb[slot], LV_OBJ_FLAG_HIDDEN);
        } else {
          // Nog onderweg: dan het lege vakje, geen hoes van de vorige plaat.
          lv_obj_add_flag(shelfThumb[slot], LV_OBJ_FLAG_HIDDEN);
        }
      }

      lv_label_set_text(lblShelfTitle, shelfTitle(hier));
      lv_label_set_text(lblShelfArtist, shelfArtist(hier));
      lv_label_set_text_fmt(lblShelfCount, "%d / %d", hier + 1, n);

      lv_arc_set_value(shelfArc, n > 1 ? (int16_t)((int32_t)hier * 1000 / (n - 1)) : 0);

      // De ring: één letter per beginletter die in de kast voorkomt, verdeeld
      // over 300 graden met de opening onderaan. Alleen opnieuw plaatsen als de
      // lijst veranderde — bij elke stap 27 objecten verzetten is zonde.
      static int ringBuiltFor = -1;
      static char ringLetters[SHELF_RING_MAX];
      static int  ringCount = 0;
      if (ringBuiltFor != n) {
        ringBuiltFor = n;
        ringCount = 0;
        char previous = 0;
        for (int i = 0; i < n && ringCount < SHELF_RING_MAX; i++) {
          const char l = shelfLetterAt(i);
          if (l != previous) { ringLetters[ringCount++] = l; previous = l; }
        }
        for (int i = 0; i < SHELF_RING_MAX; i++) {
          if (i >= ringCount) { lv_obj_add_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN); continue; }
          const float graden = -150.0f +
              (ringCount > 1 ? 300.0f * i / (ringCount - 1) : 150.0f);
          const float rad = graden * 3.14159265f / 180.0f;
          // Rechtop op een cirkel van 205: rotatie bepaalt alleen de plek.
          const int dx = (int)(205.0f * sinf(rad));
          const int dy = (int)(-205.0f * cosf(rad));
          char blob[2] = {ringLetters[i], '\0'};
          lv_label_set_text(shelfRing[i], blob);
          lv_obj_align(shelfRing[i], LV_ALIGN_CENTER, dx, dy);
          lv_obj_clear_flag(shelfRing[i], LV_OBJ_FLAG_HIDDEN);
        }
      }
      const char now = shelfLetterAt(hier);
      for (int i = 0; i < ringCount; i++)
        lv_obj_set_style_text_color(shelfRing[i],
            lv_color_hex(ringLetters[i] == now ? COL_ACCENT : COL_TRACK), 0);

      // De grote letter alleen terwijl je springt; main.cpp bepaalt hoe lang.
      if (s.shelfLetter) {
        char groot[2] = {s.shelfLetter, '\0'};
        lv_label_set_text(lblShelfLetter, groot);
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
      // De QR wijst naar het brein op de Pi, niet naar dit paneel: dáár staat
      // de wachtrij waar je een plaat aan een release hangt.
      char adres[64];
      snprintf(adres, sizeof(adres), "http://%s:8790",
               settings.brainHost[0] ? settings.brainHost : s.ip);
      lv_qrcode_update(qr, adres, strlen(adres));
      lv_label_set_text_fmt(lblQrIp, "%d te koppelen", s.pairing);
      break;
    }

    case Screen::Setup:
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "Nog geen wifi");
      lv_label_set_text_fmt(lblMsgText, "Verbind met %s\nen ga naar %s",
                            AP_SSID, s.ip[0] ? s.ip : "192.168.4.1");
      break;

    case Screen::NoAvr:
      show(lyMsg);
      lv_label_set_text(lblMsgHead, "Geen receiver");
      lv_label_set_text_fmt(lblMsgText, "%s\nNetwerkbesturing op \"Altijd aan\"?",
                            settings.avrHost[0] ? settings.avrHost : "geen adres ingesteld");
      break;
  }
}

void uiSetRotation(bool omgekeerd) {
  lv_disp_t *d = lv_disp_get_default();
  if (d) lv_disp_set_rotation(d, omgekeerd ? LV_DISP_ROT_180 : LV_DISP_ROT_NONE);
}

void uiTick() {
  if (buf1) lv_timer_handler();
}

Touch uiTakeTouch() {
  const Touch t = pending;
  pending = Touch::None;
  return t;
}
