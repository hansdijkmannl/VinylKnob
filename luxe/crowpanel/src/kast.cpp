#include "kast.h"

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
  uint32_t artiestOff;
  uint32_t titelOff;
};

static char   *tekst   = nullptr;      // het hele blok, met nullbytes ertussen
static Album  *albums  = nullptr;
static int     aantal  = 0;
static int     huidig  = 0;
static bool    geladen = false;

// -- de plaatjes ------------------------------------------------------------
// Een handvol hoezen onthouden, niet alleen de drie in beeld: heen en weer
// draaien over dezelfde plaats is precies wat je doet als je zoekt, en dan is
// opnieuw ophalen wat je net had zonde van de tijd.
#define CACHE_N 9
static const size_t PIXELS = (size_t)KAST_PX * KAST_PX;

struct Plaatje {
  int         album = -1;            // welke index hier in staat, -1 = leeg
  uint32_t    gebruikt = 0;          // voor het opruimen: hoe recent
  bool        vol = false;
  uint16_t   *px = nullptr;
  lv_img_dsc_t dsc{};
};

static Plaatje cache[CACHE_N];
static uint8_t *jpeg = nullptr;
static const size_t JPEG_MAX = 24 * 1024;   // 138 px komt niet boven ~4 kB
static uint32_t klok = 0;                   // loopt op bij elk gebruik

// Waar de decoder nu in schrijft. TJpgDec heeft één globale callback, dus hij
// wordt vlak voor elke decodering gezet; hoes.cpp doet hetzelfde.
static Plaatje *doel = nullptr;

static bool schrijfBlok(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t *bitmap) {
  if (!doel || !doel->px) return false;
  if (y >= KAST_PX) return false;
  for (uint16_t r = 0; r < h; r++) {
    const int16_t py = y + r;
    if (py < 0 || py >= KAST_PX) continue;
    for (uint16_t c = 0; c < w; c++) {
      const int16_t px = x + c;
      if (px < 0 || px >= KAST_PX) continue;
      doel->px[py * KAST_PX + px] = bitmap[r * w + c];
    }
  }
  return true;
}

void kastBegin() {
  jpeg = (uint8_t *)heap_caps_malloc(JPEG_MAX, MALLOC_CAP_SPIRAM);
  for (int i = 0; i < CACHE_N; i++) {
    cache[i].px = (uint16_t *)heap_caps_malloc(PIXELS * 2, MALLOC_CAP_SPIRAM);
    if (!cache[i].px) {
      Serial.printf("[kast] geen PSRAM voor plaatje %d\n", i);
      continue;
    }
    memset(&cache[i].dsc, 0, sizeof(cache[i].dsc));
    cache[i].dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
    cache[i].dsc.header.w  = KAST_PX;
    cache[i].dsc.header.h  = KAST_PX;
    cache[i].dsc.data_size = PIXELS * 2;
    cache[i].dsc.data      = (const uint8_t *)cache[i].px;
  }
}

// ---------------------------------------------------------------------------
// De lijst ophalen
// ---------------------------------------------------------------------------
bool kastLaad(const char *host, uint16_t poort) {
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

  char *nieuw = (char *)heap_caps_malloc(lengte + 1, MALLOC_CAP_SPIRAM);
  if (!nieuw) { http.end(); return false; }

  WiFiClient *stroom = http.getStreamPtr();
  int gelezen = 0;
  const uint32_t deadline = millis() + 10000;
  while (gelezen < lengte && millis() < deadline) {
    const int n = stroom->readBytes(nieuw + gelezen, lengte - gelezen);
    if (n <= 0) break;
    gelezen += n;
  }
  http.end();
  if (gelezen != lengte) { free(nieuw); return false; }
  nieuw[lengte] = '\0';

  // Tellen hoeveel regels er zijn, dan pas de tabel maken.
  int regels = 1;
  for (int i = 0; i < lengte; i++) if (nieuw[i] == '\n') regels++;

  Album *tabel = (Album *)heap_caps_malloc(sizeof(Album) * regels, MALLOC_CAP_SPIRAM);
  if (!tabel) { free(nieuw); return false; }

  // Ter plekke splitsen: tabs en regeleindes worden nullbytes, en we onthouden
  // waar elk stuk begint. Zo staat er geen enkele kopie van de tekst naast.
  int n = 0;
  char *p = nieuw;
  while (p < nieuw + lengte && n < regels) {
    char *eindeRegel = strchr(p, '\n');
    if (eindeRegel) *eindeRegel = '\0';

    char *tab1 = strchr(p, '\t');
    if (!tab1) { if (!eindeRegel) break; p = eindeRegel + 1; continue; }
    *tab1 = '\0';
    char *tab2 = strchr(tab1 + 1, '\t');
    if (!tab2) { if (!eindeRegel) break; p = eindeRegel + 1; continue; }
    *tab2 = '\0';

    tabel[n].id         = (uint16_t)atoi(p);
    tabel[n].artiestOff = (uint32_t)(tab1 + 1 - nieuw);
    tabel[n].titelOff   = (uint32_t)(tab2 + 1 - nieuw);
    n++;

    if (!eindeRegel) break;
    p = eindeRegel + 1;
  }

  if (tekst)  free(tekst);
  if (albums) free(albums);
  tekst  = nieuw;
  albums = tabel;
  aantal = n;
  huidig = 0;
  geladen = n > 0;

  // De hoezen die er lagen horen bij de vorige lijst.
  for (int i = 0; i < CACHE_N; i++) { cache[i].album = -1; cache[i].vol = false; }

  Serial.printf("[kast] %d albums geladen (%d kB)\n", aantal, lengte / 1024);
  return geladen;
}

bool kastGeladen() { return geladen; }
int  kastAantal()  { return aantal; }
int  kastIndex()   { return huidig; }

const char *kastArtiest(int index) {
  if (!geladen || index < 0 || index >= aantal) return "";
  return tekst + albums[index].artiestOff;
}

const char *kastTitel(int index) {
  if (!geladen || index < 0 || index >= aantal) return "";
  return tekst + albums[index].titelOff;
}

uint16_t kastId(int index) {
  if (!geladen || index < 0 || index >= aantal) return 0;
  return albums[index].id;
}

char kastLetterVan(int index) {
  const char *naam = kastArtiest(index);
  if (!naam[0]) naam = kastTitel(index);
  const char c = toupper((unsigned char)naam[0]);
  return (c >= 'A' && c <= 'Z') ? c : '#';
}

static int omheen(int i) {
  if (aantal <= 0) return 0;
  return ((i % aantal) + aantal) % aantal;
}

void kastGa(int stappen) { huidig = omheen(huidig + stappen); }
void kastZet(int index)  { huidig = omheen(index); }

void kastSpring(int richting) {
  if (!geladen) return;
  const char hier = kastLetterVan(huidig);

  if (richting > 0) {
    // Naar het eerste album van de volgende letter.
    for (int i = 1; i <= aantal; i++) {
      const int k = omheen(huidig + i);
      if (kastLetterVan(k) != hier) { huidig = k; return; }
    }
  } else {
    // Terug: eerst naar het begin van deze letter. Sta je daar al, dan door
    // naar het begin van de vorige. Dat is hoe een sprongindex hoort te voelen
    // — één keer terug brengt je bovenaan de letter waar je in zit.
    int begin = huidig;
    while (begin > 0 && kastLetterVan(begin - 1) == hier) begin--;
    if (begin != huidig) { huidig = begin; return; }
    if (begin == 0) { huidig = aantal - 1; return; }
    const char vorige = kastLetterVan(begin - 1);
    int start = begin - 1;
    while (start > 0 && kastLetterVan(start - 1) == vorige) start--;
    huidig = start;
  }
}

// ---------------------------------------------------------------------------
// De plaatjes
// ---------------------------------------------------------------------------
static Plaatje *zoek(int album) {
  for (int i = 0; i < CACHE_N; i++)
    if (cache[i].album == album && cache[i].vol) return &cache[i];
  return nullptr;
}

static int zichtbaar(int plek) { return omheen(huidig + plek - 1); }

const lv_img_dsc_t *kastHoes(int plek) {
  if (!geladen || plek < 0 || plek > 2) return nullptr;
  Plaatje *p = zoek(zichtbaar(plek));
  if (!p) return nullptr;
  p->gebruikt = ++klok;
  return &p->dsc;
}

// Het minst recent gebruikte plekje dat niet in beeld staat. In beeld staande
// hoezen weggooien om er een in beeld staande hoes in te zetten zou betekenen
// dat ze om de beurt verdwijnen zodra de cache krap wordt.
static Plaatje *vrijPlekje() {
  Plaatje *beste = nullptr;
  for (int i = 0; i < CACHE_N; i++) {
    if (!cache[i].px) continue;
    if (!cache[i].vol) return &cache[i];
    bool inBeeld = false;
    for (int plek = 0; plek < 3; plek++)
      if (cache[i].album == zichtbaar(plek)) inBeeld = true;
    if (inBeeld) continue;
    if (!beste || cache[i].gebruikt < beste->gebruikt) beste = &cache[i];
  }
  return beste;
}

static bool haalHoes(const char *host, uint16_t poort, int album) {
  if (!jpeg || album < 0 || album >= aantal) return false;
  if (WiFi.status() != WL_CONNECTED) return false;

  Plaatje *plek = vrijPlekje();
  if (!plek || !plek->px) return false;

  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/kasthoes?id=%u&px=%d",
           host, poort, (unsigned)albums[album].id, KAST_PX);

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

  memset(plek->px, 0, PIXELS * 2);
  doel = plek;
  TJpgDec.setJpgScale(1);
  TJpgDec.setSwapBytes(false);
  TJpgDec.setCallback(schrijfBlok);
  const JRESULT r = TJpgDec.drawJpg(0, 0, jpeg, gelezen);
  doel = nullptr;

  if (r != JDR_OK) { plek->vol = false; plek->album = -1; return false; }
  plek->album    = album;
  plek->vol      = true;
  plek->gebruikt = ++klok;
  return true;
}

// Zodra je stilhoudt gaan we halen. Tweehonderd milliseconde is lang genoeg om
// niet tijdens het draaien te beginnen, en kort genoeg dat de hoes er staat
// voordat je hebt kunnen kijken.
static const uint32_t RUST_MS = 200;
static uint32_t laatsteStap = 0;
static int      vorigeIndex = -1;

bool kastLus(const char *host, uint16_t poort) {
  if (!geladen || !host || !host[0]) return false;

  if (huidig != vorigeIndex) {
    vorigeIndex = huidig;
    laatsteStap = millis();
    return false;                        // eerst de tekst laten bijkomen
  }
  if (millis() - laatsteStap < RUST_MS) return false;

  // Één per aanroep: dan blijft de lus reageren op de knop terwijl de rest
  // binnenkomt. Midden eerst — dat is degene waar je naar kijkt.
  static const int VOLGORDE[3] = {1, 2, 0};
  for (int i = 0; i < 3; i++) {
    const int album = zichtbaar(VOLGORDE[i]);
    if (zoek(album)) continue;
    return haalHoes(host, poort, album);
  }
  return false;
}
