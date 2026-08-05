#include "hoes.h"

#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include <WiFi.h>

#include "config.h"

// 240 x 240 in 16 bits: 115 kB. Past ruim in de PSRAM, en te groot voor het
// interne geheugen — vandaar heap_caps_malloc en niet gewoon malloc.
static uint16_t *pixels = nullptr;
static uint8_t  *jpeg   = nullptr;
static bool      gevuld = false;
static lv_img_dsc_t beeld;

// Ruimer dan de ~35 kB die de Pi levert bij 480 pixels, zodat een hoes met veel
// detail er ook nog in past zonder dat het misgaat.
static const size_t JPEG_MAX = 96 * 1024;

static bool schrijfBlok(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (!pixels) return false;
  if (y >= HOES_PX) return false;                 // klaar, de rest overslaan
  for (uint16_t r = 0; r < h; r++) {
    const int16_t py = y + r;
    if (py < 0 || py >= HOES_PX) continue;
    for (uint16_t c = 0; c < w; c++) {
      const int16_t px = x + c;
      if (px < 0 || px >= HOES_PX) continue;
      pixels[py * HOES_PX + px] = bitmap[r * w + c];
    }
  }
  return true;
}

void hoesBegin() {
  pixels = (uint16_t *)heap_caps_malloc(HOES_PX * HOES_PX * 2, MALLOC_CAP_SPIRAM);
  jpeg   = (uint8_t *)heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM);
  if (!pixels || !jpeg) {
    Serial.println(F("[hoes] geen PSRAM voor de hoes"));
    return;
  }
  memset(&beeld, 0, sizeof(beeld));
  beeld.header.cf         = LV_IMG_CF_TRUE_COLOR;
  beeld.header.w          = HOES_PX;
  beeld.header.h          = HOES_PX;
  beeld.data_size         = HOES_PX * HOES_PX * 2;
  beeld.data              = (const uint8_t *)pixels;
}

static uint32_t accent = 0xe8a33d;      // de amber uit de mockup, als terugval

// De opvallendste kleur zoeken, niet de gemiddelde: een gemiddelde van een hoes
// is altijd modderig grijsbruin. Daarom een histogram over de kleurtoon, gewogen
// met verzadiging en helderheid, en daarna de toon met vaste verzadiging
// terugzetten — zo is de boog altijd fel genoeg om tegen de hoes af te steken.
static void bepaalAccent() {
  accent = 0xe8a33d;
  if (!pixels || !gevuld) return;

  const int BAKKEN = 24;
  float gewicht[BAKKEN] = {0};
  const int stap = 6;                   // ~6400 monsters, ruim genoeg

  for (int y = 0; y < HOES_PX; y += stap) {
    for (int x = 0; x < HOES_PX; x += stap) {
      const uint16_t p = pixels[y * HOES_PX + x];
      const float r = ((p >> 11) & 0x1F) / 31.0f;
      const float g = ((p >> 5) & 0x3F) / 63.0f;
      const float b = (p & 0x1F) / 31.0f;

      const float mx = fmaxf(r, fmaxf(g, b));
      const float mn = fminf(r, fminf(g, b));
      const float d  = mx - mn;
      if (mx < 0.12f || d < 0.07f) continue;      // te donker of te grijs

      float tint;
      if      (mx == r) tint = fmodf((g - b) / d, 6.0f);
      else if (mx == g) tint = (b - r) / d + 2.0f;
      else              tint = (r - g) / d + 4.0f;
      if (tint < 0) tint += 6.0f;

      const int bak = ((int)(tint / 6.0f * BAKKEN)) % BAKKEN;
      gewicht[bak] += (d / mx) * mx;               // verzadiging x helderheid
    }
  }

  int beste = -1;
  float top = 0;
  for (int i = 0; i < BAKKEN; i++) if (gewicht[i] > top) { top = gewicht[i]; beste = i; }
  if (beste < 0 || top < 2.0f) {
    // Een hoes zonder uitgesproken kleur — zwart-wit, of heel donker. Dan geen
    // amber uit het niets, maar een koel grijsblauw dat bij zo'n hoes past.
    accent = 0x9fb4c8;
    return;
  }

  // Terug naar RGB met vaste verzadiging en helderheid.
  const float tint = (beste + 0.5f) / BAKKEN * 6.0f;
  const float S = 0.72f, V = 0.98f;
  const float C = V * S, X = C * (1 - fabsf(fmodf(tint, 2.0f) - 1)), m = V - C;
  float r = 0, g = 0, b = 0;
  if      (tint < 1) { r = C; g = X; }
  else if (tint < 2) { r = X; g = C; }
  else if (tint < 3) { g = C; b = X; }
  else if (tint < 4) { g = X; b = C; }
  else if (tint < 5) { r = X; b = C; }
  else               { r = C; b = X; }
  accent = ((uint32_t)((r + m) * 255) << 16) |
           ((uint32_t)((g + m) * 255) << 8) |
            (uint32_t)((b + m) * 255);
}

uint32_t hoesAccent() { return accent; }

void hoesWis() { gevuld = false; accent = 0xe8a33d; }

const lv_img_dsc_t *hoesBeeld() { return gevuld ? &beeld : nullptr; }

static bool haalEnDecodeer(const char *url) {
  HTTPClient http;
  http.setConnectTimeout(600);
  http.setTimeout(2500);                 // een hoes mag wat langer duren dan /nu
  if (!http.begin(url)) { Serial.println(F("[hoes] begin() mislukt")); return false; }
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[hoes] GET %s -> %d\n", url, code);
    http.end();
    return false;
  }

  const int lengte = http.getSize();
  if (lengte <= 0 || (size_t)lengte > JPEG_MAX) {
    Serial.printf("[hoes] lengte %d past niet (max %u)\n", lengte, (unsigned)JPEG_MAX);
    http.end();
    return false;
  }

  WiFiClient *stroom = http.getStreamPtr();
  size_t gelezen = 0;
  const uint32_t deadline = millis() + 3000;
  while (gelezen < (size_t)lengte && millis() < deadline) {
    const int n = stroom->readBytes(jpeg + gelezen, lengte - gelezen);
    if (n <= 0) break;
    gelezen += n;
  }
  http.end();
  if (gelezen != (size_t)lengte) {
    Serial.printf("[hoes] maar %u van %d bytes gelezen\n", (unsigned)gelezen, lengte);
    return false;
  }

  memset(pixels, 0, HOES_PX * HOES_PX * 2);
  // Vlak voor het decoderen en niet één keer bij het opstarten: TJpgDec heeft
  // één globale callback, en kast.cpp decodeert in zijn eigen buffers. Wie het
  // laatst instelde wint, dus stelt iedereen het zelf in.
  //
  // LVGL bewaart lv_color_t als een gewone uint16 in de volgorde van de chip
  // (LV_COLOR_16_SWAP staat op 0), en TJpgDec levert precies zulke woorden.
  // Omwisselen is dan juist fout: dat geeft de negatief-achtige kleuren met
  // oranje en groen die je krijgt als hoog en laag byte verwisseld zijn.
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(schrijfBlok);
  const JRESULT r = TJpgDec.drawJpg(0, 0, jpeg, gelezen);
  gevuld = (r == JDR_OK);
  if (!gevuld) {
    Serial.printf("[hoes] decoderen mislukt (%d)\n", r);
  } else {
    // Twee pixels ter controle: hiermee is te vergelijken of de kleurvolgorde
    // klopt, zonder naar het scherm te hoeven kijken.
    bepaalAccent();
    Serial.printf("[hoes] %u bytes, accent #%06X\n", (unsigned)gelezen, (unsigned)accent);
  }
  return gevuld;
}

bool hoesLaad(const char *host, uint16_t poort) {
  if (!pixels || !jpeg) { Serial.println(F("[hoes] geen buffers")); return false; }
  if (WiFi.status() != WL_CONNECTED) { Serial.println(F("[hoes] geen wifi")); return false; }
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/hoes", host, poort);
  return haalEnDecodeer(url);
}

bool hoesLaadAlbum(const char *host, uint16_t poort, uint16_t releaseId) {
  if (!pixels || !jpeg) return false;
  if (WiFi.status() != WL_CONNECTED) return false;
  // Dezelfde maat als /hoes levert, want hij komt op dezelfde plek terecht:
  // schermvullend achter het volume.
  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/kasthoes?id=%u&px=%d",
           host, poort, (unsigned)releaseId, HOES_PX);
  return haalEnDecodeer(url);
}
