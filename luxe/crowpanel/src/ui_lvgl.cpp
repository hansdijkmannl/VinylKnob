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
#include "hoes.h"
#include "kast.h"
#include "settings.h"
#include "ui.h"

// -- kleuren, uit luxe/mockup/ ----------------------------------------------
#define KL_ACHTERGROND 0x101014
#define KL_ACCENT      0xe8a33d
#define KL_TEKST       0xf2f2f4
#define KL_GEDEMPT     0x8b8b96
#define KL_SPOOR       0x3a3a42
#define KL_WAARSCHUW   0xc2451f

// De boog beslaat 270°, met de opening onderaan — net als in de mockup.
#define BOOG_START 135
#define BOOG_EIND  405

static Touch pending = Touch::None;

// -- de lagen ---------------------------------------------------------------
static lv_obj_t *lyNow, *lyInputs, *lyBrowse, *lyQr, *lyMsg;
static lv_obj_t *arc, *lblVol, *lblTitel, *lblArtiest, *lblIngang, *lblMute, *hoes;
static lv_obj_t *lblBron, *lblHeet;
static lv_obj_t *imgHoes, *sluier, *plaatMidden, *plaatOnder, *lblGeenHoes, *puntKoppel, *knopLuister;
static lv_obj_t *vlakKoppel;
static lv_obj_t *lblPickKop, *lblPickBoven, *lblPickNu, *lblPickOnder;

// De platenkast. Zoveel letters als het alfabet plus een vakje voor alles wat
// daar niet in valt; meer plekken dan dat kan de ring niet nodig hebben.
#define KAST_RING_MAX 27
static lv_obj_t *kastVak[3], *kastHoesje[3], *kastBoog;
static lv_obj_t *lblKastKop, *lblKastTitel, *lblKastArtiest, *lblKastTeller;
static lv_obj_t *kastRing[KAST_RING_MAX];
static lv_obj_t *lblKastLetter, *vlakLetter;

// Het grote lettertype uit font_kastletter.c.
LV_FONT_DECLARE(font_kastletter);
static lv_obj_t *lblQrIp, *lblQrHost, *qr;
static lv_obj_t *lblMsgKop, *lblMsgTekst;

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
static lv_obj_t *maakLaag() {
  lv_obj_t *o = lv_obj_create(lv_scr_act());
  lv_obj_remove_style_all(o);
  lv_obj_set_size(o, SCREEN_W, SCREEN_H);
  lv_obj_center(o);
  lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
  return o;
}

static lv_obj_t *maakLabel(lv_obj_t *ouder, const lv_font_t *font, uint32_t kleur,
                           lv_align_t uitlijning, lv_coord_t dx, lv_coord_t dy) {
  lv_obj_t *l = lv_label_create(ouder);
  lv_obj_set_style_text_font(l, font, 0);
  lv_obj_set_style_text_color(l, lv_color_hex(kleur), 0);
  lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
  lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
  lv_obj_set_width(l, SCREEN_W - 150);
  lv_obj_align(l, uitlijning, dx, dy);
  lv_label_set_text(l, "");
  return l;
}

static void tikCb(lv_event_t *e) {
  pending = (Touch)(uintptr_t)lv_event_get_user_data(e);
}

static void maakTikbaar(lv_obj_t *o, Touch wat) {
  lv_obj_add_flag(o, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_event_cb(o, tikCb, LV_EVENT_CLICKED, (void *)(uintptr_t)wat);
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

  lv_obj_set_style_bg_color(lv_scr_act(), lv_color_hex(KL_ACHTERGROND), 0);
  lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);
  lv_obj_clear_flag(lv_scr_act(), LV_OBJ_FLAG_SCROLLABLE);

  // -- laag 1: wat er speelt -------------------------------------------------
  lyNow = maakLaag();

  // De hoes vult het hele scherm en ligt onderop — zo hoort het volgens
  // luxe/mockup/: de plaat is de achtergrond, niet een postzegel in het midden.
  // Volgorde van aanmaken bepaalt bij LVGL de stapeling, dus dit moet vóór de
  // boog en de teksten.
  imgHoes = lv_img_create(lyNow);
  lv_obj_center(imgHoes);
  lv_obj_add_flag(imgHoes, LV_OBJ_FLAG_HIDDEN);
  maakTikbaar(imgHoes, Touch::Artwork);

  // Een sluier eroverheen, anders verdwijnt het dB-getal in een lichte hoes.
  // Vast en niet slim: op een klein rond scherm is een voorspelbare leesbaarheid
  // meer waard dan een sluier die per plaat anders uitpakt.
  sluier = lv_obj_create(lyNow);
  lv_obj_remove_style_all(sluier);
  lv_obj_set_size(sluier, SCREEN_W, SCREEN_H);
  lv_obj_center(sluier);
  lv_obj_set_style_bg_color(sluier, lv_color_hex(KL_ACHTERGROND), 0);
  // Licht: de leesbaarheid komt niet meer van een donkere waas over alles, maar
  // van zachte plaatjes achter de tekst zelf. Zo blijft de hoes hoes.
  lv_obj_set_style_bg_opa(sluier, LV_OPA_20, 0);
  lv_obj_add_flag(sluier, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(sluier, LV_OBJ_FLAG_CLICKABLE);

  // Zacht plaatje achter het dB-getal en de titel. Alleen daar waar tekst staat,
  // zodat de rest van de hoes onaangetast blijft.
  plaatMidden = lv_obj_create(lyNow);
  lv_obj_remove_style_all(plaatMidden);
  lv_obj_set_size(plaatMidden, 320, 132);
  lv_obj_align(plaatMidden, LV_ALIGN_CENTER, 0, 16);
  lv_obj_set_style_radius(plaatMidden, 66, 0);
  lv_obj_set_style_bg_color(plaatMidden, lv_color_hex(KL_ACHTERGROND), 0);
  lv_obj_set_style_bg_opa(plaatMidden, LV_OPA_50, 0);
  lv_obj_add_flag(plaatMidden, LV_OBJ_FLAG_HIDDEN);
  lv_obj_clear_flag(plaatMidden, LV_OBJ_FLAG_CLICKABLE);

  // Zonder hoes een donkere schijf met een muzieksymbool, zodat er altijd iets
  // in het midden staat in plaats van een gat.
  hoes = lv_obj_create(lyNow);
  lv_obj_remove_style_all(hoes);
  lv_obj_set_size(hoes, 232, 232);
  lv_obj_center(hoes);
  lv_obj_set_style_radius(hoes, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(hoes, lv_color_hex(0x1c1c22), 0);
  lv_obj_set_style_bg_opa(hoes, LV_OPA_COVER, 0);
  lv_obj_set_style_border_color(hoes, lv_color_hex(KL_SPOOR), 0);
  lv_obj_set_style_border_width(hoes, 1, 0);
  maakTikbaar(hoes, Touch::Artwork);

  lblGeenHoes = lv_label_create(hoes);
  lv_obj_center(lblGeenHoes);
  lv_obj_set_style_text_font(lblGeenHoes, &lv_font_montserrat_48, 0);
  lv_obj_set_style_text_color(lblGeenHoes, lv_color_hex(KL_SPOOR), 0);
  lv_label_set_text(lblGeenHoes, LV_SYMBOL_AUDIO);

  arc = lv_arc_create(lyNow);
  lv_obj_set_size(arc, 456, 456);
  lv_obj_center(arc);
  lv_arc_set_bg_angles(arc, BOOG_START, BOOG_EIND);
  lv_arc_set_range(arc, 0, 1000);
  lv_arc_set_value(arc, 0);
  lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
  lv_obj_clear_flag(arc, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_arc_width(arc, 10, LV_PART_MAIN);
  lv_obj_set_style_arc_width(arc, 10, LV_PART_INDICATOR);
  lv_obj_set_style_arc_color(arc, lv_color_hex(KL_SPOOR), LV_PART_MAIN);
  lv_obj_set_style_arc_color(arc, lv_color_hex(KL_ACCENT), LV_PART_INDICATOR);

  lblVol     = maakLabel(lyNow, &lv_font_montserrat_48, KL_TEKST,    LV_ALIGN_CENTER,  0, -14);
  lblTitel   = maakLabel(lyNow, &lv_font_montserrat_20, KL_TEKST,    LV_ALIGN_CENTER,  0,  30);
  lblArtiest = maakLabel(lyNow, &lv_font_montserrat_14, KL_GEDEMPT,  LV_ALIGN_CENTER,  0,  56);
  lblIngang  = maakLabel(lyNow, &lv_font_montserrat_28, KL_ACCENT,   LV_ALIGN_CENTER,  0, 146);
  // Waar de titel vandaan komt, als er geen hoes is. Bij YouTube blijft het bij
  // tekst — die app geeft geen afbeelding door — en dan is "YouTube" boven de
  // videotitel informatiever dan een leeg vlak.
  lblBron    = maakLabel(lyNow, &lv_font_montserrat_14, KL_ACCENT,    LV_ALIGN_CENTER,  0, -60);
  lblMute    = maakLabel(lyNow, &lv_font_montserrat_20, KL_WAARSCHUW, LV_ALIGN_CENTER, 0, -100);
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
  plaatOnder = lv_obj_create(lyNow);
  lv_obj_remove_style_all(plaatOnder);
  lv_obj_set_size(plaatOnder, 132, 56);
  lv_obj_align(plaatOnder, LV_ALIGN_CENTER, 0, 192);
  lv_obj_set_style_radius(plaatOnder, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(plaatOnder, lv_color_hex(KL_ACHTERGROND), 0);
  lv_obj_set_style_bg_opa(plaatOnder, LV_OPA_60, 0);
  lv_obj_clear_flag(plaatOnder, LV_OBJ_FLAG_CLICKABLE);

  knopLuister = lv_label_create(lyNow);
  lv_obj_set_style_text_font(knopLuister, &lv_font_montserrat_28, 0);
  lv_obj_set_style_text_color(knopLuister, lv_color_hex(KL_SPOOR), 0);
  lv_obj_set_style_text_align(knopLuister, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_set_size(knopLuister, 96, 62);
  lv_obj_set_style_pad_top(knopLuister, 14, 0);
  lv_obj_align(knopLuister, LV_ALIGN_CENTER, 0, 192);
  lv_label_set_text(knopLuister, LV_SYMBOL_AUDIO);
  maakTikbaar(knopLuister, Touch::Listen);

  // Waarschuwing als de Pi tegen zijn grenzen loopt. Geen permanente meter:
  // graden op een scherm voor albumhoezen is rommel, en de Pi zit normaal ruim
  // binnen zijn bereik. Wil je het getal zien, dan staat het op de orenpagina.
  lblHeet = maakLabel(lyNow, &lv_font_montserrat_20, KL_WAARSCHUW, LV_ALIGN_CENTER, -60, 192);
  lv_label_set_text(lblHeet, LV_SYMBOL_WARNING);
  lv_obj_add_flag(lblHeet, LV_OBJ_FLAG_HIDDEN);

  // Klein stipje boven de ingangsnaam als er platen op koppeling wachten. Geen
  // scherm dat zichzelf naar voren dringt: je ziet het als je kijkt, en tikken
  // op de hoes brengt je naar de QR-code.
  puntKoppel = lv_obj_create(lyNow);
  lv_obj_remove_style_all(puntKoppel);
  lv_obj_set_size(puntKoppel, 10, 10);
  lv_obj_align(puntKoppel, LV_ALIGN_CENTER, 52, 192);
  lv_obj_set_style_radius(puntKoppel, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(puntKoppel, lv_color_hex(KL_ACCENT), 0);
  lv_obj_set_style_bg_opa(puntKoppel, LV_OPA_COVER, 0);
  lv_obj_add_flag(puntKoppel, LV_OBJ_FLAG_HIDDEN);
  // Een onzichtbaar vlak eromheen: tien pixels raak je niet met een vinger, en
  // sinds de hoes naar de platenkast leidt is dit de enige weg naar de QR-code.
  vlakKoppel = lv_obj_create(lyNow);
  lv_obj_remove_style_all(vlakKoppel);
  lv_obj_set_size(vlakKoppel, 52, 52);
  lv_obj_align(vlakKoppel, LV_ALIGN_CENTER, 52, 192);
  lv_obj_add_flag(vlakKoppel, LV_OBJ_FLAG_HIDDEN);
  maakTikbaar(vlakKoppel, Touch::Pairing);

  lv_obj_set_height(lblIngang, 54);
  lv_obj_set_style_pad_top(lblIngang, 10, 0);
  maakTikbaar(lblIngang, Touch::InputLabel);

  // -- laag 2: ingang kiezen -------------------------------------------------
  lyInputs = maakLaag();
  lblPickKop   = maakLabel(lyInputs, &lv_font_montserrat_14, KL_GEDEMPT, LV_ALIGN_CENTER, 0, -130);
  lblPickBoven = maakLabel(lyInputs, &lv_font_montserrat_20, KL_SPOOR,   LV_ALIGN_CENTER, 0,  -62);
  lblPickNu    = maakLabel(lyInputs, &lv_font_montserrat_28, KL_ACCENT,  LV_ALIGN_CENTER, 0,    0);
  lblPickOnder = maakLabel(lyInputs, &lv_font_montserrat_20, KL_SPOOR,   LV_ALIGN_CENTER, 0,   62);
  lv_label_set_text(lblPickKop, "INGANG");
  lv_obj_set_height(lblPickNu, 64);
  lv_obj_set_style_pad_top(lblPickNu, 16, 0);
  maakTikbaar(lblPickNu, Touch::Confirm);
  lv_obj_set_height(lblPickKop, 48);
  maakTikbaar(lblPickKop, Touch::Dismiss);

  // -- laag 3: platenkast ----------------------------------------------------
  //
  // Dezelfde opzet als in de webinterface: de hoezen op een rij, de sprongindex
  // als letterring langs de binnenrand met de opening onderaan. Een rechte
  // letterbalk wringt in een cirkel — hij loopt over twee regels en botst met
  // de rand — terwijl langs de omtrek het midden vrij blijft voor de hoezen.
  lyBrowse = maakLaag();
  lblKastKop = maakLabel(lyBrowse, &lv_font_montserrat_14, KL_GEDEMPT,
                         LV_ALIGN_CENTER, 0, -150);
  lv_label_set_text(lblKastKop, "PLATENKAST");

  // De positieboog, net binnen de letterring.
  kastBoog = lv_arc_create(lyBrowse);
  lv_obj_set_size(kastBoog, 452, 452);
  lv_obj_center(kastBoog);
  lv_arc_set_bg_angles(kastBoog, 0, 360);
  lv_arc_set_range(kastBoog, 0, 1000);
  lv_obj_remove_style(kastBoog, NULL, LV_PART_KNOB);
  lv_obj_clear_flag(kastBoog, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_arc_width(kastBoog, 4, LV_PART_MAIN);
  lv_obj_set_style_arc_width(kastBoog, 4, LV_PART_INDICATOR);
  lv_obj_set_style_arc_opa(kastBoog, LV_OPA_20, LV_PART_MAIN);
  lv_obj_set_style_arc_color(kastBoog, lv_color_hex(KL_SPOOR), LV_PART_MAIN);
  lv_obj_set_style_arc_color(kastBoog, lv_color_hex(KL_ACCENT), LV_PART_INDICATOR);

  // Drie hoezen, alle drie even groot. Welke de huidige is zie je aan de rand
  // en aan de titel eronder — niet aan het formaat, want dan zou één stap drie
  // nieuwe plaatjes vergen in plaats van één.
  static const int KAST_X[3] = {-144, 0, 144};
  for (int i = 0; i < 3; i++) {
    kastVak[i] = lv_obj_create(lyBrowse);
    lv_obj_remove_style_all(kastVak[i]);
    lv_obj_set_size(kastVak[i], KAST_PX + 8, KAST_PX + 8);
    lv_obj_align(kastVak[i], LV_ALIGN_CENTER, KAST_X[i], -14);
    lv_obj_set_style_radius(kastVak[i], 12, 0);
    lv_obj_set_style_bg_color(kastVak[i], lv_color_hex(0x1c1c22), 0);
    lv_obj_set_style_bg_opa(kastVak[i], LV_OPA_COVER, 0);
    lv_obj_clear_flag(kastVak[i], LV_OBJ_FLAG_SCROLLABLE);

    kastHoesje[i] = lv_img_create(kastVak[i]);
    lv_obj_center(kastHoesje[i]);
    // De twee buitenste gedempt, zodat het midden vooraan staat zonder dat er
    // aan het formaat gesleuteld hoeft te worden.
    if (i != 1) {
      lv_obj_set_style_img_recolor(kastHoesje[i], lv_color_hex(KL_ACHTERGROND), 0);
      lv_obj_set_style_img_recolor_opa(kastHoesje[i], LV_OPA_50, 0);
    }
  }
  lv_obj_set_style_border_color(kastVak[1], lv_color_hex(KL_ACCENT), 0);
  lv_obj_set_style_border_width(kastVak[1], 3, 0);

  lblKastTitel   = maakLabel(lyBrowse, &lv_font_montserrat_20, KL_TEKST,
                             LV_ALIGN_CENTER, 0, 88);
  lblKastArtiest = maakLabel(lyBrowse, &lv_font_montserrat_14, KL_GEDEMPT,
                             LV_ALIGN_CENTER, 0, 116);
  lblKastTeller  = maakLabel(lyBrowse, &lv_font_montserrat_14, KL_SPOOR,
                             LV_ALIGN_CENTER, 0, 150);

  // De letter waar je heen springt, groot in beeld. De ring blijft klein — die
  // laat zien wáár je bent — maar tijdens het springen wil je lezen zonder te
  // zoeken, en veertien pixels langs de rand zijn daar te weinig voor.
  //
  // Er ligt een donker vlak achter: de letter staat over de hoezen heen en zou
  // op een lichte hoes anders wegvallen.
  vlakLetter = lv_obj_create(lyBrowse);
  lv_obj_remove_style_all(vlakLetter);
  lv_obj_set_size(vlakLetter, SCREEN_W, SCREEN_H);
  lv_obj_center(vlakLetter);
  lv_obj_set_style_bg_color(vlakLetter, lv_color_hex(KL_ACHTERGROND), 0);
  lv_obj_set_style_bg_opa(vlakLetter, LV_OPA_70, 0);
  lv_obj_clear_flag(vlakLetter, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_add_flag(vlakLetter, LV_OBJ_FLAG_HIDDEN);

  lblKastLetter = lv_label_create(lyBrowse);
  lv_obj_set_style_text_font(lblKastLetter, &font_kastletter, 0);
  lv_obj_set_style_text_color(lblKastLetter, lv_color_hex(KL_ACCENT), 0);
  lv_obj_align(lblKastLetter, LV_ALIGN_CENTER, 0, -10);
  lv_label_set_text(lblKastLetter, "A");
  lv_obj_add_flag(lblKastLetter, LV_OBJ_FLAG_HIDDEN);

  // De letterring. Rechtop en niet meedraaiend met de rand: LVGL kan labels
  // niet roteren (alleen afbeeldingen), en rechtop leest op dit formaat toch
  // beter dan een letter die op zijn kant staat.
  for (int i = 0; i < KAST_RING_MAX; i++) {
    kastRing[i] = lv_label_create(lyBrowse);
    lv_obj_set_style_text_font(kastRing[i], &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(kastRing[i], lv_color_hex(KL_SPOOR), 0);
    lv_label_set_text(kastRing[i], "");
    lv_obj_add_flag(kastRing[i], LV_OBJ_FLAG_HIDDEN);
  }

  // -- laag 4: koppelen ------------------------------------------------------
  lyQr = maakLaag();
  lv_obj_t *qKop = maakLabel(lyQr, &lv_font_montserrat_14, KL_GEDEMPT, LV_ALIGN_CENTER, 0, -130);
  lv_label_set_text(qKop, "ONBEKENDE PLAAT");
  qr = lv_qrcode_create(lyQr, 168, lv_color_hex(0x101014), lv_color_white());
  lv_obj_align(qr, LV_ALIGN_CENTER, 0, -14);
  lv_obj_set_style_border_width(qr, 6, 0);
  lv_obj_set_style_border_color(qr, lv_color_white(), 0);
  lblQrIp   = maakLabel(lyQr, &lv_font_montserrat_20, KL_TEKST,   LV_ALIGN_CENTER, 0, 116);
  lblQrHost = maakLabel(lyQr, &lv_font_montserrat_14, KL_GEDEMPT, LV_ALIGN_CENTER, 0, 146);
  lv_label_set_text(lblQrHost, "scan om te koppelen");
  maakTikbaar(lyQr, Touch::Dismiss);

  // -- laag 5: meldingen (setup, geen receiver) ------------------------------
  lyMsg = maakLaag();
  lblMsgKop   = maakLabel(lyMsg, &lv_font_montserrat_20, KL_ACCENT,  LV_ALIGN_CENTER, 0, -40);
  lblMsgTekst = maakLabel(lyMsg, &lv_font_montserrat_14, KL_GEDEMPT, LV_ALIGN_CENTER, 0,  10);

  lv_obj_clear_flag(lyMsg, LV_OBJ_FLAG_HIDDEN);
  lv_label_set_text(lblMsgKop, "MarantzKnob");
  lv_label_set_text(lblMsgTekst, "opstarten...");
  lv_timer_handler();
}

// ---------------------------------------------------------------------------
static void toon(lv_obj_t *welke) {
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
      toon(lyNow);

      // De boog loopt van stilte tot je eigen plafond, niet tot 0 dB. Anders
      // beweegt hij nauwelijks: luisteren doe je tussen -60 en -20.
      const float top = (float)settings.volMaxDb;
      const float frac = s.haveVolume
          ? (s.volumeDb - (-80.0f)) / (top - (-80.0f))
          : 0.0f;
      lv_arc_set_value(arc, (int16_t)(constrain(frac, 0.0f, 1.0f) * 1000));

      // De boog neemt de opvallendste kleur uit de hoes over, net als de
      // webversie. Zonder hoes valt hij terug op de amber uit de mockup.
      const uint32_t kleur = hoesAccent();
      static uint32_t vorigeKleur = 0;
      if (kleur != vorigeKleur) {
        vorigeKleur = kleur;
        Serial.printf("[scherm] boog op #%06X\n", (unsigned)kleur);
      }
      lv_obj_set_style_arc_color(arc, lv_color_hex(kleur), LV_PART_INDICATOR);
      lv_obj_set_style_bg_color(puntKoppel, lv_color_hex(kleur), 0);
      lv_obj_set_style_arc_opa(arc, s.muted ? LV_OPA_30 : LV_OPA_COVER,
                               LV_PART_INDICATOR);

      // Het dB-getal alleen tonen terwijl je draait. Staat er daarna een hoes,
      // dan blijft het scherm leeg: de hoes is het beeld, en artiest en titel
      // eroverheen zetten haalt daar juist vanaf. Alleen als er géén hoes is
      // vullen we de leegte met de naam.
      // Een echte hoes ís het beeld, daar hoort geen tekst overheen. Een
      // app-logo staat er juist omdát er geen hoes is — dan wil je de titel er
      // wel bij, anders zie je alleen een merk en niet wat er draait.
      const bool echteHoes = hoesBeeld() && !s.artworkIsLogo;
      const bool toonTekst = !s.turning && s.nowTitle[0] && !echteHoes;
      if (s.turning || (!toonTekst && !s.nowTitle[0])) {
        lv_obj_clear_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtiest, LV_OBJ_FLAG_HIDDEN);
        // Bewust niet lv_label_set_text_fmt met %.1f: LVGL's eigen printf laat
        // drijvende komma standaard weg (LV_SPRINTF_USE_FLOAT staat op 0) en
        // zet dan letterlijk "f" op het scherm. Gewoon snprintf van de libc.
        lv_obj_clear_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtiest, LV_OBJ_FLAG_HIDDEN);
        if (s.haveVolume) {
          char tekst[12];
          snprintf(tekst, sizeof(tekst), "%.1f", s.volumeDb);
          lv_label_set_text(lblVol, tekst);
        } else {
          lv_label_set_text(lblVol, "--");
        }
      } else if (toonTekst) {
        lv_obj_add_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblTitel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblArtiest, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(lblTitel, s.nowTitle);
        lv_label_set_text(lblArtiest, s.nowArtist);
      } else {
        lv_obj_add_flag(lblVol, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblTitel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblArtiest, LV_OBJ_FLAG_HIDDEN);
      }

      // De bronnaam alleen bij tekst zonder hoes; staat er een hoes, dan is
      // die het beeld en heeft een etiket erboven geen toegevoegde waarde.
      // Bij een logo geen naam erbij: dat logo ís de naam, en twee keer
      // hetzelfde zeggen kost alleen ruimte op een scherm dat het niet heeft.
      if (toonTekst && s.sourceApp[0] && !s.artworkIsLogo) {
        lv_label_set_text(lblBron, s.sourceApp);
        lv_obj_clear_flag(lblBron, LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_style_text_color(lblBron, lv_color_hex(hoesAccent()), 0);
      } else {
        lv_obj_add_flag(lblBron, LV_OBJ_FLAG_HIDDEN);
      }

      // Plaatje achter de tekst alleen als er tekst of een dB-getal staat.
      if (s.turning || toonTekst) lv_obj_clear_flag(plaatMidden, LV_OBJ_FLAG_HIDDEN);
      else                        lv_obj_add_flag(plaatMidden, LV_OBJ_FLAG_HIDDEN);

      if (s.muted) lv_obj_clear_flag(lblMute, LV_OBJ_FLAG_HIDDEN);
      else         lv_obj_add_flag(lblMute, LV_OBJ_FLAG_HIDDEN);

      // De hoes. hoes.cpp haalt hem op; hier alleen tonen wat er ligt.
      const lv_img_dsc_t *plaat = hoesBeeld();
      if (plaat) {
        lv_img_set_src(imgHoes, plaat);
        lv_obj_clear_flag(imgHoes, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(sluier, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(plaatMidden, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(hoes, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(imgHoes, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(sluier, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(plaatMidden, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(hoes, LV_OBJ_FLAG_HIDDEN);
      }

      // Oplichten terwijl de Pi opneemt; anders gedempt maar wel zichtbaar,
      // zodat je weet dat je erop kunt tikken.
      // Wit als hij niets doet, accentkleur zodra hij luistert. Wit is op een
      // donker plaatje altijd leesbaar; meekleuren met de hoes was juist de
      // reden dat hij wegviel.
      lv_obj_set_style_text_color(knopLuister,
          lv_color_hex(s.listening ? hoesAccent() : KL_TEKST), 0);

      // Net gekoppeld: dat even bevestigen. Je hebt zojuist iets vastgelegd wat
      // het apparaat blijvend onthoudt, en dan is stilzwijgend terugspringen
      // naar het volume te weinig.
      if (s.justLinked) {
        lv_label_set_text(lblBron, "GEKOPPELD");
        lv_obj_set_style_text_color(lblBron, lv_color_hex(KL_ACCENT), 0);
        lv_obj_clear_flag(lblBron, LV_OBJ_FLAG_HIDDEN);
      }

      if (s.piHot) lv_obj_clear_flag(lblHeet, LV_OBJ_FLAG_HIDDEN);
      else         lv_obj_add_flag(lblHeet, LV_OBJ_FLAG_HIDDEN);

      if (s.pairing > 0) {
        lv_obj_clear_flag(puntKoppel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(vlakKoppel, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(puntKoppel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(vlakKoppel, LV_OBJ_FLAG_HIDDEN);
      }

      lv_label_set_text(lblIngang, s.inputLabel);
      lv_obj_set_style_text_color(lblIngang,
          lv_color_hex(s.powered ? hoesAccent() : KL_SPOOR), 0);
      break;
    }

    case Screen::Inputs: {
      toon(lyInputs);
      lv_label_set_text(lblPickBoven, s.pickPrev);
      lv_label_set_text(lblPickNu,    s.pickLabel);
      lv_label_set_text(lblPickOnder, s.pickNext);
      break;
    }

    case Screen::Off:
      // Alles uit. De achtergrondverlichting gaat in main.cpp uit; hier blijft
      // een zwart scherm over zodat er ook niets nagloeit.
      toon(lyMsg);
      lv_label_set_text(lblMsgKop, "");
      lv_label_set_text(lblMsgTekst, "");
      break;

    case Screen::Browse: {
      toon(lyBrowse);
      const int n = kastAantal();
      if (!n) {
        lv_label_set_text(lblKastTitel, "Nog niets");
        lv_label_set_text(lblKastArtiest, kastGeladen() ? "de kast is leeg"
                                                        : "kast ophalen...");
        lv_label_set_text(lblKastTeller, "");
        for (int i = 0; i < 3; i++) lv_obj_add_flag(kastVak[i], LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < KAST_RING_MAX; i++)
          lv_obj_add_flag(kastRing[i], LV_OBJ_FLAG_HIDDEN);
        break;
      }

      // De kop vertelt wat drukken gaat doen. Zonder dat wijs je een album aan
      // en leg je zonder het te weten een koppeling vast — of andersom, sta je
      // te wachten op iets dat niet gebeurt.
      if (s.shelfLinkable) {
        lv_label_set_text(lblKastKop, "KOPPEL AAN WAT SPEELT");
        lv_obj_set_style_text_color(lblKastKop, lv_color_hex(KL_ACCENT), 0);
      } else {
        lv_label_set_text(lblKastKop, "PLATENKAST");
        lv_obj_set_style_text_color(lblKastKop, lv_color_hex(KL_GEDEMPT), 0);
      }

      const int hier = kastIndex();
      for (int plek = 0; plek < 3; plek++) {
        lv_obj_clear_flag(kastVak[plek], LV_OBJ_FLAG_HIDDEN);
        const lv_img_dsc_t *plaat = kastHoes(plek);
        if (plaat) {
          lv_img_set_src(kastHoesje[plek], plaat);
          lv_obj_clear_flag(kastHoesje[plek], LV_OBJ_FLAG_HIDDEN);
        } else {
          // Nog onderweg: dan het lege vakje, geen hoes van de vorige plaat.
          lv_obj_add_flag(kastHoesje[plek], LV_OBJ_FLAG_HIDDEN);
        }
      }

      lv_label_set_text(lblKastTitel, kastTitel(hier));
      lv_label_set_text(lblKastArtiest, kastArtiest(hier));
      lv_label_set_text_fmt(lblKastTeller, "%d / %d", hier + 1, n);

      lv_arc_set_value(kastBoog, n > 1 ? (int16_t)((int32_t)hier * 1000 / (n - 1)) : 0);

      // De ring: één letter per beginletter die in de kast voorkomt, verdeeld
      // over 300 graden met de opening onderaan. Alleen opnieuw plaatsen als de
      // lijst veranderde — bij elke stap 27 objecten verzetten is zonde.
      static int ringVoor = -1;
      static char ringLetters[KAST_RING_MAX];
      static int  ringN = 0;
      if (ringVoor != n) {
        ringVoor = n;
        ringN = 0;
        char vorige = 0;
        for (int i = 0; i < n && ringN < KAST_RING_MAX; i++) {
          const char l = kastLetterVan(i);
          if (l != vorige) { ringLetters[ringN++] = l; vorige = l; }
        }
        for (int i = 0; i < KAST_RING_MAX; i++) {
          if (i >= ringN) { lv_obj_add_flag(kastRing[i], LV_OBJ_FLAG_HIDDEN); continue; }
          const float graden = -150.0f +
              (ringN > 1 ? 300.0f * i / (ringN - 1) : 150.0f);
          const float rad = graden * 3.14159265f / 180.0f;
          // Rechtop op een cirkel van 205: rotatie bepaalt alleen de plek.
          const int dx = (int)(205.0f * sinf(rad));
          const int dy = (int)(-205.0f * cosf(rad));
          char tekst[2] = {ringLetters[i], '\0'};
          lv_label_set_text(kastRing[i], tekst);
          lv_obj_align(kastRing[i], LV_ALIGN_CENTER, dx, dy);
          lv_obj_clear_flag(kastRing[i], LV_OBJ_FLAG_HIDDEN);
        }
      }
      const char nu = kastLetterVan(hier);
      for (int i = 0; i < ringN; i++)
        lv_obj_set_style_text_color(kastRing[i],
            lv_color_hex(ringLetters[i] == nu ? KL_ACCENT : KL_SPOOR), 0);

      // De grote letter alleen terwijl je springt; main.cpp bepaalt hoe lang.
      if (s.shelfLetter) {
        char groot[2] = {s.shelfLetter, '\0'};
        lv_label_set_text(lblKastLetter, groot);
        lv_obj_clear_flag(vlakLetter, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(lblKastLetter, LV_OBJ_FLAG_HIDDEN);
      } else {
        lv_obj_add_flag(vlakLetter, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(lblKastLetter, LV_OBJ_FLAG_HIDDEN);
      }
      break;
    }

    case Screen::Pairing: {
      toon(lyQr);
      // De QR wijst naar het brein op de Pi, niet naar dit paneel: dáár staat
      // de wachtrij waar je een plaat aan een release hangt.
      char adres[64];
      snprintf(adres, sizeof(adres), "http://%s:8790",
               settings.breinHost[0] ? settings.breinHost : s.ip);
      lv_qrcode_update(qr, adres, strlen(adres));
      lv_label_set_text_fmt(lblQrIp, "%d te koppelen", s.pairing);
      break;
    }

    case Screen::Setup:
      toon(lyMsg);
      lv_label_set_text(lblMsgKop, "Nog geen wifi");
      lv_label_set_text_fmt(lblMsgTekst, "Verbind met %s\nen ga naar %s",
                            AP_SSID, s.ip[0] ? s.ip : "192.168.4.1");
      break;

    case Screen::NoAvr:
      toon(lyMsg);
      lv_label_set_text(lblMsgKop, "Geen receiver");
      lv_label_set_text_fmt(lblMsgTekst, "%s\nNetwerkbesturing op \"Altijd aan\"?",
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
