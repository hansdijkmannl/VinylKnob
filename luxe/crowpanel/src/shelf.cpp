#include "shelf.h"

#include <HTTPClient.h>
#include <TJpg_Decoder.h>
#include <WiFi.h>

#include "config.h"

// -- de lijst ---------------------------------------------------------------
// Alle namen achter elkaar in één blok tekst, met per album twee verwijzingen
// erin. Dat scheelt 549 losse toewijzingen op een hoop die daar niet van houdt,
// en het blok komt precies zo binnen als het over de lijn ging.
struct Album {
  uint16_t id;
  uint32_t artistOff;
  uint32_t titleOff;
};

static char   *blob   = nullptr;      // het hele blok, met nullbytes ertussen
static Album  *albums  = nullptr;
static int     count  = 0;
static int     current  = 0;
static bool    loaded = false;

// -- de plaatjes ------------------------------------------------------------
// Een handvol hoezen onthouden, niet alleen de drie in beeld: heen en weer
// draaien over dezelfde plaats is precies wat je doet als je zoekt, en dan is
// opnieuw ophalen wat je net had zonde van de tijd.
#define CACHE_N 9
static const size_t PIXELS = (size_t)SHELF_PX * SHELF_PX;

struct Thumb {
  int         album = -1;            // welke index hier in staat, -1 = leeg
  uint32_t    usedAt = 0;          // voor het opruimen: hoe recent
  bool        vol = false;
  uint16_t   *px = nullptr;
  lv_img_dsc_t dsc{};
};

static Thumb cache[CACHE_N];
static uint8_t *jpeg = nullptr;
static const size_t JPEG_MAX = 24 * 1024;   // 138 px komt niet boven ~4 kB
static uint32_t tick = 0;                   // loopt op bij elk gebruik

// Waar de decoder nu in schrijft. TJpgDec heeft één globale callback, dus hij
// wordt vlak voor elke decodering gezet; hoes.cpp doet hetzelfde.
static Thumb *target = nullptr;

static bool writeBlock(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (!target || !target->px) return false;
  if (y >= SHELF_PX) return false;
  for (uint16_t r = 0; r < h; r++) {
    const int16_t py = y + r;
    if (py < 0 || py >= SHELF_PX) continue;
    for (uint16_t c = 0; c < w; c++) {
      const int16_t px = x + c;
      if (px < 0 || px >= SHELF_PX) continue;
      target->px[py * SHELF_PX + px] = bitmap[r * w + c];
    }
  }
  return true;
}

void shelfBegin() {
  jpeg = (uint8_t *)heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM);
  for (int i = 0; i < CACHE_N; i++) {
    cache[i].px = (uint16_t *)heap_caps_malloc(PIXELS * 2, MALLOC_CAP_SPIRAM);
    if (!cache[i].px) {
      Serial.printf("[kast] geen PSRAM voor plaatje %d\n", i);
      continue;
    }
    memset(&cache[i].dsc, 0, sizeof(cache[i].dsc));
    cache[i].dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
    cache[i].dsc.header.w  = SHELF_PX;
    cache[i].dsc.header.h  = SHELF_PX;
    cache[i].dsc.data_size = PIXELS * 2;
    cache[i].dsc.data      = (const uint8_t *)cache[i].px;
  }
}

// ---------------------------------------------------------------------------
// De lijst ophalen
// ---------------------------------------------------------------------------
bool shelfLoad(const char *host, uint16_t poort) {
  if (!host || !host[0] || WiFi.status() != WL_CONNECTED) return false;

  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/kast", host, poort);

  HTTPClient http;
  http.setConnectTimeout(1000);
  http.setTimeout(8000);                 // 25 kB over wifi mag even duren
  if (!http.begin(url)) return false;
  if (http.GET() != HTTP_CODE_OK) { http.end(); return false; }

  const int lengte = http.getSize();
  if (lengte <= 0 || lengte > 512 * 1024) { http.end(); return false; }

  char *fresh = (char *)heap_caps_malloc(lengte + 1, MALLOC_CAP_SPIRAM);
  if (!fresh) { http.end(); return false; }

  WiFiClient *stroom = http.getStreamPtr();
  int gelezen = 0;
  const uint32_t deadline = millis() + 10000;
  while (gelezen < lengte && millis() < deadline) {
    const int n = stroom->readBytes(fresh + gelezen, lengte - gelezen);
    if (n <= 0) break;
    gelezen += n;
  }
  http.end();
  if (gelezen != lengte) { free(fresh); return false; }
  fresh[lengte] = '\0';

  // Tellen hoeveel regels er zijn, dan pas de tabel maken.
  int lines = 1;
  for (int i = 0; i < lengte; i++) if (fresh[i] == '\n') lines++;

  Album *tabel = (Album *)heap_caps_malloc(sizeof(Album) * lines, MALLOC_CAP_SPIRAM);
  if (!tabel) { free(fresh); return false; }

  // Ter plekke splitsen: tabs en regeleindes worden nullbytes, en we onthouden
  // waar elk stuk begint. Zo staat er geen enkele kopie van de tekst naast.
  int n = 0;
  char *p = fresh;
  while (p < fresh + lengte && n < lines) {
    char *eindeRegel = strchr(p, '\n');
    if (eindeRegel) *eindeRegel = '\0';

    char *tab1 = strchr(p, '\t');
    if (!tab1) { if (!eindeRegel) break; p = eindeRegel + 1; continue; }
    *tab1 = '\0';
    char *tab2 = strchr(tab1 + 1, '\t');
    if (!tab2) { if (!eindeRegel) break; p = eindeRegel + 1; continue; }
    *tab2 = '\0';

    tabel[n].id         = (uint16_t)atoi(p);
    tabel[n].artistOff = (uint32_t)(tab1 + 1 - fresh);
    tabel[n].titleOff   = (uint32_t)(tab2 + 1 - fresh);
    n++;

    if (!eindeRegel) break;
    p = eindeRegel + 1;
  }

  if (blob)  free(blob);
  if (albums) free(albums);
  blob  = fresh;
  albums = tabel;
  count = n;
  current = 0;
  loaded = n > 0;

  // De hoezen die er lagen horen bij de vorige lijst.
  for (int i = 0; i < CACHE_N; i++) { cache[i].album = -1; cache[i].vol = false; }

  Serial.printf("[kast] %d albums geladen (%d kB)\n", count, lengte / 1024);
  return loaded;
}

bool shelfLoaded() { return loaded; }
int  shelfCount()  { return count; }
int  shelfIndex()   { return current; }

const char *shelfArtist(int index) {
  if (!loaded || index < 0 || index >= count) return "";
  return blob + albums[index].artistOff;
}

const char *shelfTitle(int index) {
  if (!loaded || index < 0 || index >= count) return "";
  return blob + albums[index].titleOff;
}

uint16_t shelfReleaseId(int index) {
  if (!loaded || index < 0 || index >= count) return 0;
  return albums[index].id;
}

char shelfLetterAt(int index) {
  const char *naam = shelfArtist(index);
  if (!naam[0]) naam = shelfTitle(index);
  const char c = toupper((unsigned char)naam[0]);
  return (c >= 'A' && c <= 'Z') ? c : '#';
}

static int wrap(int i) {
  if (count <= 0) return 0;
  return ((i % count) + count) % count;
}

void shelfMove(int steps) { current = wrap(current + steps); }
void shelfSet(int index)  { current = wrap(index); }

void shelfJump(int direction) {
  if (!loaded) return;
  const char hier = shelfLetterAt(current);

  if (direction > 0) {
    // Naar het eerste album van de volgende letter.
    for (int i = 1; i <= count; i++) {
      const int k = wrap(current + i);
      if (shelfLetterAt(k) != hier) { current = k; return; }
    }
  } else {
    // Terug: eerst naar het begin van deze letter. Sta je daar al, dan door
    // naar het begin van de vorige. Dat is hoe een sprongindex hoort te voelen
    // — één keer terug brengt je bovenaan de letter waar je in zit.
    int begin = current;
    while (begin > 0 && shelfLetterAt(begin - 1) == hier) begin--;
    if (begin != current) { current = begin; return; }
    if (begin == 0) { current = count - 1; return; }
    const char previous = shelfLetterAt(begin - 1);
    int start = begin - 1;
    while (start > 0 && shelfLetterAt(start - 1) == previous) start--;
    current = start;
  }
}

// ---------------------------------------------------------------------------
// De plaatjes
// ---------------------------------------------------------------------------
static Thumb *zoek(int album) {
  for (int i = 0; i < CACHE_N; i++)
    if (cache[i].album == album && cache[i].vol) return &cache[i];
  return nullptr;
}

static int visibleAt(int slot) { return wrap(current + slot - 1); }

const lv_img_dsc_t *shelfArtworkAt(int slot) {
  if (!loaded || slot < 0 || slot > 2) return nullptr;
  Thumb *p = zoek(visibleAt(slot));
  if (!p) return nullptr;
  p->usedAt = ++tick;
  return &p->dsc;
}

// Het minst recent gebruikte plekje dat niet in beeld staat. In beeld staande
// hoezen weggooien om er een in beeld staande hoes in te zetten zou betekenen
// dat ze om de beurt verdwijnen zodra de cache krap wordt.
static Thumb *freeSlot() {
  Thumb *best = nullptr;
  for (int i = 0; i < CACHE_N; i++) {
    if (!cache[i].px) continue;
    if (!cache[i].vol) return &cache[i];
    bool inBeeld = false;
    for (int slot = 0; slot < 3; slot++)
      if (cache[i].album == visibleAt(slot)) inBeeld = true;
    if (inBeeld) continue;
    if (!best || cache[i].usedAt < best->usedAt) best = &cache[i];
  }
  return best;
}

static bool fetchArtwork(const char *host, uint16_t poort, int album) {
  if (!jpeg || album < 0 || album >= count) return false;
  if (WiFi.status() != WL_CONNECTED) return false;

  Thumb *slot = freeSlot();
  if (!slot || !slot->px) return false;

  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/kasthoes?id=%u&px=%d",
           host, poort, (unsigned)albums[album].id, SHELF_PX);

  HTTPClient http;
  http.setConnectTimeout(600);
  http.setTimeout(2500);
  if (!http.begin(url)) return false;
  if (http.GET() != HTTP_CODE_OK) { http.end(); return false; }

  const int lengte = http.getSize();
  if (lengte <= 0 || (size_t)lengte > JPEG_MAX) { http.end(); return false; }

  WiFiClient *stroom = http.getStreamPtr();
  int gelezen = 0;
  const uint32_t deadline = millis() + 3000;
  while (gelezen < lengte && millis() < deadline) {
    const int n = stroom->readBytes(jpeg + gelezen, lengte - gelezen);
    if (n <= 0) break;
    gelezen += n;
  }
  http.end();
  if (gelezen != lengte) return false;

  memset(slot->px, 0, PIXELS * 2);
  target = slot;
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(writeBlock);
  const JRESULT r = TJpgDec.drawJpg(0, 0, jpeg, gelezen);
  target = nullptr;

  if (r != JDR_OK) { slot->vol = false; slot->album = -1; return false; }
  slot->album    = album;
  slot->vol      = true;
  slot->usedAt = ++tick;
  return true;
}

// Zodra je stilhoudt gaan we halen. Tweehonderd milliseconde is lang genoeg om
// niet tijdens het draaien te beginnen, en kort genoeg dat de hoes er staat
// voordat je hebt kunnen kijken.
static const uint32_t RUST_MS = 200;
static uint32_t lastStep = 0;
static int      previousIndex = -1;

bool shelfLoop(const char *host, uint16_t poort) {
  if (!loaded || !host || !host[0]) return false;

  if (current != previousIndex) {
    previousIndex = current;
    lastStep = millis();
    return false;                        // eerst de tekst laten bijkomen
  }
  if (millis() - lastStep < RUST_MS) return false;

  // Één per aanroep: dan blijft de lus reageren op de knop terwijl de rest
  // binnenkomt. Midden eerst — dat is degene waar je naar kijkt.
  static const int ORDER[3] = {1, 2, 0};
  for (int i = 0; i < 3; i++) {
    const int album = visibleAt(ORDER[i]);
    if (zoek(album)) continue;
    return fetchArtwork(host, poort, album);
  }
  return false;
}
