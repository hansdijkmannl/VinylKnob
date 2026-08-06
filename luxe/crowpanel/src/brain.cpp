#include "brain.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"
#include "settings.h"

BrainState brainState;
bool brainWantsToListen = true;   // main.cpp zet dit op basis van de ingang

static uint32_t nextPoll = 0;
static uint8_t  missers       = 0;

// De timeouts zijn met opzet kort. Dit gebeurt in dezelfde lus die de knop
// afhandelt, dus elke milliseconde die we hier wachten voel je aan het volume.
// Een Pi op je eigen netwerk antwoordt in tientallen milliseconden; duurt het
// langer, dan is hij er niet en heeft doorwachten geen zin.
static const uint16_t VERBIND_TIMEOUT_MS = 400;
static const uint16_t READ_TIMEOUT_MS    = 800;

void brainBegin() {
  brainState = BrainState();
}

static void clear() {
  if (!brainState.bereikbaar && !brainState.speelt) return;
  brainState.bereikbaar = false;
  brainState.speelt     = false;
  brainState.listening   = false;
  brainState.onShelf     = false;
  brainState.canLink = false;
  brainState.haveArtwork   = false;
  brainState.artworkIsLogo = false;
  brainState.artist[0] = '\0';
  brainState.title[0]   = '\0';
  brainState.album[0]   = '\0';
  brainState.app[0]     = '\0';
  brainState.revision++;
}

void brainAskLookup() {
  if (settings.brainHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/luister", settings.brainHost, BRAIN_PORT);
  HTTPClient http;
  http.setConnectTimeout(VERBIND_TIMEOUT_MS);
  http.setTimeout(READ_TIMEOUT_MS);
  if (!http.begin(url)) return;
  http.POST("");
  http.end();
  // Meteen weer polsen. Zes seconden wachten (want het antwoord duurt toch
  // tien) was fout gedacht: dan blijft het icoontje al die tijd donker en lijkt
  // je tik niet aangekomen. De vlag "luistert" is er juist meteen.
  nextPoll = millis() + 300;
}

bool brainLink(uint16_t releaseId) {
  if (settings.brainHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return false;
  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/koppel?id=%u",
           settings.brainHost, BRAIN_PORT, (unsigned)releaseId);
  HTTPClient http;
  http.setConnectTimeout(VERBIND_TIMEOUT_MS);
  // Ruimer dan de rest: het brein legt hier een vingerafdruk vast en dat duurt
  // langer dan een peiling. Blokkeert de lus even, maar dit gebeurt alleen op
  // jouw druk op de knop.
  http.setTimeout(8000);
  if (!http.begin(url)) return false;
  const int code = http.POST("");
  http.end();
  // Meteen opnieuw peilen, zodat het scherm de nieuwe naam heeft voordat je
  // hebt kunnen kijken.
  nextPoll = millis() + 200;
  return code == HTTP_CODE_OK;
}

void brainLoop() {
  if (settings.brainHost[0] == '\0') return;      // geen Pi ingesteld
  if (WiFi.status() != WL_CONNECTED) return;

  const uint32_t now = millis();
  if (now < nextPoll) return;

  // Na een paar mislukte pogingen rustiger aan doen. Anders staat een
  // uitgeschakelde Pi elke paar seconden de lus op te houden.
  // Sneller polsen zolang de Pi bezig is: dan verandert er ook echt iets.
  const uint32_t interval = (missers >= 3)      ? BRAIN_RETRY_MS
                          : brainState.listening ? BRAIN_BUSY_MS
                                                : BRAIN_POLL_MS;
  nextPoll = now + interval;

  // Meesturen of luisteren zinvol is. Staat de receiver op de Apple TV, dan
  // valt er niets te herkennen en hoeft de Pi Shazam niet lastig te vallen —
  // en dat is precies waar we zuinig mee wilden zijn.
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/nu?luister=%d",
           settings.brainHost, BRAIN_PORT, brainWantsToListen ? 1 : 0);

  HTTPClient http;
  http.setConnectTimeout(VERBIND_TIMEOUT_MS);
  http.setTimeout(READ_TIMEOUT_MS);
  if (!http.begin(url)) { missers++; clear(); return; }

  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    http.end();
    if (missers < 255) missers++;
    clear();
    return;
  }

  JsonDocument doc;
  const DeserializationError fout = deserializeJson(doc, http.getString());
  http.end();
  if (fout) { if (missers < 255) missers++; return; }

  missers = 0;

  BrainState fresh;
  fresh.bereikbaar = true;
  fresh.speelt   = doc["speelt"] | false;
  fresh.listening = doc["luistert"] | false;
  fresh.onShelf   = doc["kast"]   | false;
  fresh.canLink = doc["koppelbaar"] | false;
  fresh.haveArtwork   = doc["hoes"] | false;
  fresh.artworkIsLogo = doc["logo"] | false;
  fresh.linkable = doc["koppelen"] | 0;
  fresh.hot     = doc["heet"] | false;
  strlcpy(fresh.artist, doc["artiest"] | "", sizeof(fresh.artist));
  strlcpy(fresh.title,   doc["titel"]   | "", sizeof(fresh.title));
  strlcpy(fresh.album,   doc["album"]   | "", sizeof(fresh.album));
  strlcpy(fresh.app,     doc["app"]     | "", sizeof(fresh.app));

  // Alleen de revisie ophogen als er werkelijk iets anders is; anders zou het
  // scherm elke paar seconden opnieuw tekenen zonder reden.
  const bool anders =
      fresh.bereikbaar != brainState.bereikbaar ||
      fresh.speelt     != brainState.speelt     ||
      fresh.listening   != brainState.listening   ||
      fresh.onShelf     != brainState.onShelf     ||
      fresh.canLink != brainState.canLink ||
      fresh.haveArtwork   != brainState.haveArtwork   ||
      fresh.artworkIsLogo != brainState.artworkIsLogo ||
      strcmp(fresh.artist, brainState.artist) != 0 ||
      strcmp(fresh.title,   brainState.title)   != 0 ||
      strcmp(fresh.album,   brainState.album)   != 0 ||
      strcmp(fresh.app,     brainState.app)     != 0 ||
      fresh.linkable   != brainState.linkable  ||
      fresh.hot       != brainState.hot;

  fresh.revision = brainState.revision + (anders ? 1 : 0);
  brainState = fresh;
}
