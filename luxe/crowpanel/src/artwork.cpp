#include "artwork.h"

#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include <WiFi.h>

#include "config.h"

// 480 x 480 in 16 bits: 460 kB. Fits comfortably in PSRAM and is far too large
// for internal memory — hence heap_caps_malloc rather than plain malloc.
static uint16_t *pixels = nullptr;
static uint8_t  *jpeg   = nullptr;
static bool      filled = false;
static lv_img_dsc_t beeld;

// Roomier than the ~35 kB the Pi delivers at 480 pixels, so a busy sleeve still
// fits without anything going wrong.
static const size_t JPEG_MAX = 96 * 1024;

static bool writeBlock(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (!pixels) return false;
  if (y >= ARTWORK_PX) return false;                 // klaar, de rest overslaan
  for (uint16_t r = 0; r < h; r++) {
    const int16_t py = y + r;
    if (py < 0 || py >= ARTWORK_PX) continue;
    for (uint16_t c = 0; c < w; c++) {
      const int16_t px = x + c;
      if (px < 0 || px >= ARTWORK_PX) continue;
      pixels[py * ARTWORK_PX + px] = bitmap[r * w + c];
    }
  }
  return true;
}

void artworkBegin() {
  pixels = (uint16_t *)heap_caps_malloc(ARTWORK_PX * ARTWORK_PX * 2, MALLOC_CAP_SPIRAM);
  jpeg   = (uint8_t *)heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM);
  if (!pixels || !jpeg) {
    Serial.println(F("[artwork] no PSRAM for the sleeve"));
    return;
  }
  memset(&beeld, 0, sizeof(beeld));
  beeld.header.cf         = LV_IMG_CF_TRUE_COLOR;
  beeld.header.w          = ARTWORK_PX;
  beeld.header.h          = ARTWORK_PX;
  beeld.data_size         = ARTWORK_PX * ARTWORK_PX * 2;
  beeld.data              = (const uint8_t *)pixels;
}

static uint32_t accent = 0xe8a33d;      // the default amber, as a fallback

// Find the most prominent colour, not the average: the average of a sleeve is
// always a muddy grey-brown. So a histogram over hue, weighted by saturation
// and brightness, then that hue re-emitted at fixed saturation
// terugzetten — zo is de boog altijd fel genoeg om tegen de hoes af te steken.
static void findAccent() {
  accent = 0xe8a33d;
  if (!pixels || !filled) return;

  const int BUCKETS = 24;
  float weight[BUCKETS] = {0};
  const int step = 6;                   // ~6400 monsters, ruim genoeg

  for (int y = 0; y < ARTWORK_PX; y += step) {
    for (int x = 0; x < ARTWORK_PX; x += step) {
      const uint16_t p = pixels[y * ARTWORK_PX + x];
      const float r = ((p >> 11) & 0x1F) / 31.0f;
      const float g = ((p >> 5) & 0x3F) / 63.0f;
      const float b = (p & 0x1F) / 31.0f;

      const float mx = fmaxf(r, fmaxf(g, b));
      const float mn = fminf(r, fminf(g, b));
      const float d  = mx - mn;
      if (mx < 0.12f || d < 0.07f) continue;      // te donker of te grijs

      float hue;
      if      (mx == r) hue = fmodf((g - b) / d, 6.0f);
      else if (mx == g) hue = (b - r) / d + 2.0f;
      else              hue = (r - g) / d + 4.0f;
      if (hue < 0) hue += 6.0f;

      const int bucket = ((int)(hue / 6.0f * BUCKETS)) % BUCKETS;
      weight[bucket] += (d / mx) * mx;               // verzadiging x helderheid
    }
  }

  int best = -1;
  float top = 0;
  for (int i = 0; i < BUCKETS; i++) if (weight[i] > top) { top = weight[i]; best = i; }
  if (best < 0 || top < 2.0f) {
    // A sleeve with no pronounced colour — black and white, or very dark. Then
    // no amber out of nowhere, but a cool grey-blue that suits such a sleeve.
    accent = 0x9fb4c8;
    return;
  }

  // Back to RGB at fixed saturation and brightness.
  const float hue = (best + 0.5f) / BUCKETS * 6.0f;
  const float S = 0.72f, V = 0.98f;
  const float C = V * S, X = C * (1 - fabsf(fmodf(hue, 2.0f) - 1)), m = V - C;
  float r = 0, g = 0, b = 0;
  if      (hue < 1) { r = C; g = X; }
  else if (hue < 2) { r = X; g = C; }
  else if (hue < 3) { g = C; b = X; }
  else if (hue < 4) { g = X; b = C; }
  else if (hue < 5) { r = X; b = C; }
  else               { r = C; b = X; }
  accent = ((uint32_t)((r + m) * 255) << 16) |
           ((uint32_t)((g + m) * 255) << 8) |
            (uint32_t)((b + m) * 255);
}

uint32_t artworkAccent() { return accent; }

void artworkClear() { filled = false; accent = 0xe8a33d; }

const lv_img_dsc_t *artworkImage() { return filled ? &beeld : nullptr; }

static bool haalEnDecodeer(const char *url) {
  HTTPClient http;
  http.setConnectTimeout(600);
  http.setTimeout(2500);                 // a sleeve may take longer than /nu
  if (!http.begin(url)) { Serial.println(F("[artwork] begin() failed")); return false; }
  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("[artwork] GET %s -> %d\n", url, code);
    http.end();
    return false;
  }

  const int lengte = http.getSize();
  if (lengte <= 0 || (size_t)lengte > JPEG_MAX) {
    Serial.printf("[artwork] length %d does not fit (max %u)\n", lengte, (unsigned)JPEG_MAX);
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
    Serial.printf("[artwork] only read %u of %d bytes\n", (unsigned)gelezen, lengte);
    return false;
  }

  memset(pixels, 0, ARTWORK_PX * ARTWORK_PX * 2);
  // Right before decoding rather than once at startup: TJpgDec has a single
  // global callback, and shelf.cpp decodes into its own buffers. Whoever set it
  // last wins, so everyone sets it themselves.
  //
  // LVGL stores lv_color_t as a plain uint16 in the chip's own byte order
  // (LV_COLOR_16_SWAP is 0), and TJpgDec produces exactly such words. Swapping
  // is therefore wrong: that gives the negative-looking oranges and greens you
  // get when the high and low bytes are exchanged.
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(writeBlock);
  const JRESULT r = TJpgDec.drawJpg(0, 0, jpeg, gelezen);
  filled = (r == JDR_OK);
  if (!filled) {
    Serial.printf("[artwork] decoding failed (%d)\n", r);
  } else {
    // Twee pixels ter controle: hiermee is te vergelijken of de kleurvolgorde
    // is right, without having to look at the screen.
    findAccent();
    Serial.printf("[artwork] %u bytes, accent #%06X\n", (unsigned)gelezen, (unsigned)accent);
  }
  return filled;
}

bool artworkLoad(const char *host, uint16_t poort) {
  if (!pixels || !jpeg) { Serial.println(F("[artwork] no buffers")); return false; }
  if (WiFi.status() != WL_CONNECTED) { Serial.println(F("[artwork] no Wi-Fi")); return false; }
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/hoes", host, poort);
  return haalEnDecodeer(url);
}

bool artworkLoadAlbum(const char *host, uint16_t poort, uint16_t releaseId) {
  if (!pixels || !jpeg) return false;
  if (WiFi.status() != WL_CONNECTED) return false;
  // The same size /hoes delivers, because it ends up in the same place:
  // full-screen behind the volume.
  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/kasthoes?id=%u&px=%d",
           host, poort, (unsigned)releaseId, ARTWORK_PX);
  return haalEnDecodeer(url);
}
