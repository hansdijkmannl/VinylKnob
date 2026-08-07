#include "apps.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include <WiFi.h>

#include "config.h"

struct App {
  char name[28];
  char id[48];
  bool hasIcon;
  int  slot;          // index into icons[], -1 = not fetched yet
};

static App  list[APPS_MAX];
static int  count   = 0;
static int  current = 0;
static bool loaded  = false;

// Every logo is kept. Two dozen tiles of 120 pixels is 690 kB of PSRAM in the
// worst case, on a board with eight megabytes of it — so an eviction policy
// here would be machinery guarding against a shortage that cannot happen. The
// shelf needs one because five hundred sleeves genuinely do not fit.
static const size_t PIXELS = (size_t)APPS_PX * APPS_PX;
static uint16_t   *pixels[APPS_MAX];
static lv_img_dsc_t dsc[APPS_MAX];
static int          icons = 0;

static uint8_t *jpeg = nullptr;
static const size_t JPEG_MAX = 12 * 1024;   // a 120 px logo is about 2 kB

static uint16_t *target = nullptr;

static bool writeBlock(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (!target) return false;
  if (y >= APPS_PX) return false;
  for (uint16_t r = 0; r < h; r++) {
    const int16_t py = y + r;
    if (py < 0 || py >= APPS_PX) continue;
    for (uint16_t c = 0; c < w; c++) {
      const int16_t px = x + c;
      if (px < 0 || px >= APPS_PX) continue;
      target[py * APPS_PX + px] = bitmap[r * w + c];
    }
  }
  return true;
}

void appsBegin() {
  jpeg = (uint8_t *)heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM);
  for (int i = 0; i < APPS_MAX; i++) pixels[i] = nullptr;
}

// ---------------------------------------------------------------------------
bool appsLoad(const char *host, uint16_t port) {
  if (!host || !host[0] || WiFi.status() != WL_CONNECTED) return false;

  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/appletv/apps", host, port);

  HTTPClient http;
  http.setConnectTimeout(1000);
  http.setTimeout(6000);
  if (!http.begin(url)) return false;
  if (http.GET() != HTTP_CODE_OK) { http.end(); return false; }

  // Small enough to parse as JSON, unlike the shelf: two dozen names is a
  // couple of kilobytes where a collection is five hundred lines.
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, http.getStream());
  http.end();
  if (err) return false;

  count = 0;
  for (JsonObjectConst a : doc["apps"].as<JsonArrayConst>()) {
    if (count >= APPS_MAX) break;
    strlcpy(list[count].name, a["name"] | "", sizeof(list[count].name));
    strlcpy(list[count].id,   a["id"]   | "", sizeof(list[count].id));
    list[count].hasIcon = a["icon"] | false;
    list[count].slot    = -1;
    if (list[count].id[0]) count++;
  }
  current = 0;
  loaded  = count > 0;
  Serial.printf("[apps] %d apps loaded\n", count);
  return loaded;
}

bool appsLoaded() { return loaded; }
int  appsCount()  { return count; }
int  appsIndex()  { return current; }

static int wrap(int i) {
  if (count <= 0) return 0;
  return ((i % count) + count) % count;
}

void appsMove(int steps) { current = wrap(current + steps); }

const char *appsName(int index) {
  if (!loaded || index < 0 || index >= count) return "";
  return list[index].name;
}

const char *appsId(int index) {
  if (!loaded || index < 0 || index >= count) return "";
  return list[index].id;
}

bool appsHasIcon(int index) {
  if (!loaded || index < 0 || index >= count) return false;
  return list[index].hasIcon;
}

static int visibleAt(int slot) { return wrap(current + slot - 1); }

const lv_img_dsc_t *appsIconAt(int slot) {
  if (!loaded || slot < 0 || slot > 2) return nullptr;
  const int i = visibleAt(slot);
  if (list[i].slot < 0) return nullptr;
  return &dsc[list[i].slot];
}

// ---------------------------------------------------------------------------
static bool fetchIcon(const char *host, uint16_t port, int index) {
  if (!jpeg || index < 0 || index >= count) return false;
  if (!list[index].hasIcon || list[index].slot >= 0) return false;
  if (icons >= APPS_MAX || WiFi.status() != WL_CONNECTED) return false;

  uint16_t *px = pixels[icons];
  if (!px) {
    px = (uint16_t *)heap_caps_malloc(PIXELS * 2, MALLOC_CAP_SPIRAM);
    if (!px) return false;
    pixels[icons] = px;
  }

  char url[160];
  snprintf(url, sizeof(url), "http://%s:%u/appletv/icon?id=%s&px=%d",
           host, port, list[index].id, APPS_PX);

  HTTPClient http;
  http.setConnectTimeout(600);
  http.setTimeout(2500);
  if (!http.begin(url)) return false;
  if (http.GET() != HTTP_CODE_OK) {
    http.end();
    // The Pi says there is none after all. Remember that, or we ask again on
    // every turn of the knob for a picture that does not exist.
    list[index].hasIcon = false;
    return false;
  }

  const int length = http.getSize();
  if (length <= 0 || (size_t)length > JPEG_MAX) { http.end(); return false; }

  WiFiClient *stream = http.getStreamPtr();
  int got = 0;
  const uint32_t deadline = millis() + 2500;
  while (got < length && millis() < deadline) {
    const int n = stream->readBytes(jpeg + got, length - got);
    if (n <= 0) break;
    got += n;
  }
  http.end();
  if (got != length) return false;

  target = px;
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(writeBlock);
  const JRESULT r = TJpgDec.drawJpg(0, 0, jpeg, got);
  target = nullptr;
  if (r != JDR_OK) return false;

  memset(&dsc[icons], 0, sizeof(dsc[icons]));
  dsc[icons].header.cf = LV_IMG_CF_TRUE_COLOR;
  dsc[icons].header.w  = APPS_PX;
  dsc[icons].header.h  = APPS_PX;
  dsc[icons].data_size = PIXELS * 2;
  dsc[icons].data      = (const uint8_t *)px;
  list[index].slot = icons++;
  return true;
}

bool appsLoop(const char *host, uint16_t port) {
  if (!loaded) return false;
  // The three on screen first, then quietly onward through the rest — so the
  // tiles beside you are already there by the time you turn to them.
  for (int slot = 0; slot < 3; slot++)
    if (fetchIcon(host, port, visibleAt(slot))) return true;
  for (int i = 0; i < count; i++)
    if (fetchIcon(host, port, i)) return true;
  return false;
}
