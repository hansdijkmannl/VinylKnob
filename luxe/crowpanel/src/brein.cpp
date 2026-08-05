#include "brein.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"
#include "settings.h"

BreinState breinState;
bool breinWilLuisteren = true;   // main.cpp zet dit op basis van de ingang

static uint32_t volgendeVraag = 0;
static uint8_t  missers       = 0;

// De timeouts zijn met opzet kort. Dit gebeurt in dezelfde lus die de knop
// afhandelt, dus elke milliseconde die we hier wachten voel je aan het volume.
// Een Pi op je eigen netwerk antwoordt in tientallen milliseconden; duurt het
// langer, dan is hij er niet en heeft doorwachten geen zin.
static const uint16_t VERBIND_TIMEOUT_MS = 400;
static const uint16_t LEES_TIMEOUT_MS    = 800;

void breinBegin() {
  breinState = BreinState();
}

static void leeg() {
  if (!breinState.bereikbaar && !breinState.speelt) return;
  breinState.bereikbaar = false;
  breinState.speelt     = false;
  breinState.luistert   = false;
  breinState.inKast     = false;
  breinState.koppelbaar = false;
  breinState.haveHoes   = false;
  breinState.hoesIsLogo = false;
  breinState.artiest[0] = '\0';
  breinState.titel[0]   = '\0';
  breinState.album[0]   = '\0';
  breinState.app[0]     = '\0';
  breinState.revision++;
}

void breinVraagOpzoeking() {
  if (settings.breinHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/luister", settings.breinHost, BREIN_PORT);
  HTTPClient http;
  http.setConnectTimeout(VERBIND_TIMEOUT_MS);
  http.setTimeout(LEES_TIMEOUT_MS);
  if (!http.begin(url)) return;
  http.POST("");
  http.end();
  // Meteen weer polsen. Zes seconden wachten (want het antwoord duurt toch
  // tien) was fout gedacht: dan blijft het icoontje al die tijd donker en lijkt
  // je tik niet aangekomen. De vlag "luistert" is er juist meteen.
  volgendeVraag = millis() + 300;
}

bool breinKoppel(uint16_t releaseId) {
  if (settings.breinHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return false;
  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/koppel?id=%u",
           settings.breinHost, BREIN_PORT, (unsigned)releaseId);
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
  volgendeVraag = millis() + 200;
  return code == HTTP_CODE_OK;
}

void breinLoop() {
  if (settings.breinHost[0] == '\0') return;      // geen Pi ingesteld
  if (WiFi.status() != WL_CONNECTED) return;

  const uint32_t now = millis();
  if (now < volgendeVraag) return;

  // Na een paar mislukte pogingen rustiger aan doen. Anders staat een
  // uitgeschakelde Pi elke paar seconden de lus op te houden.
  // Sneller polsen zolang de Pi bezig is: dan verandert er ook echt iets.
  const uint32_t interval = (missers >= 3)      ? BREIN_RETRY_MS
                          : breinState.luistert ? BREIN_BEZIG_MS
                                                : BREIN_POLL_MS;
  volgendeVraag = now + interval;

  // Meesturen of luisteren zinvol is. Staat de receiver op de Apple TV, dan
  // valt er niets te herkennen en hoeft de Pi Shazam niet lastig te vallen —
  // en dat is precies waar we zuinig mee wilden zijn.
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/nu?luister=%d",
           settings.breinHost, BREIN_PORT, breinWilLuisteren ? 1 : 0);

  HTTPClient http;
  http.setConnectTimeout(VERBIND_TIMEOUT_MS);
  http.setTimeout(LEES_TIMEOUT_MS);
  if (!http.begin(url)) { missers++; leeg(); return; }

  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    http.end();
    if (missers < 255) missers++;
    leeg();
    return;
  }

  JsonDocument doc;
  const DeserializationError fout = deserializeJson(doc, http.getString());
  http.end();
  if (fout) { if (missers < 255) missers++; return; }

  missers = 0;

  BreinState nieuw;
  nieuw.bereikbaar = true;
  nieuw.speelt   = doc["speelt"] | false;
  nieuw.luistert = doc["luistert"] | false;
  nieuw.inKast   = doc["kast"]   | false;
  nieuw.koppelbaar = doc["koppelbaar"] | false;
  nieuw.haveHoes   = doc["hoes"] | false;
  nieuw.hoesIsLogo = doc["logo"] | false;
  nieuw.koppelen = doc["koppelen"] | 0;
  nieuw.heet     = doc["heet"] | false;
  strlcpy(nieuw.artiest, doc["artiest"] | "", sizeof(nieuw.artiest));
  strlcpy(nieuw.titel,   doc["titel"]   | "", sizeof(nieuw.titel));
  strlcpy(nieuw.album,   doc["album"]   | "", sizeof(nieuw.album));
  strlcpy(nieuw.app,     doc["app"]     | "", sizeof(nieuw.app));

  // Alleen de revisie ophogen als er werkelijk iets anders is; anders zou het
  // scherm elke paar seconden opnieuw tekenen zonder reden.
  const bool anders =
      nieuw.bereikbaar != breinState.bereikbaar ||
      nieuw.speelt     != breinState.speelt     ||
      nieuw.luistert   != breinState.luistert   ||
      nieuw.inKast     != breinState.inKast     ||
      nieuw.koppelbaar != breinState.koppelbaar ||
      nieuw.haveHoes   != breinState.haveHoes   ||
      nieuw.hoesIsLogo != breinState.hoesIsLogo ||
      strcmp(nieuw.artiest, breinState.artiest) != 0 ||
      strcmp(nieuw.titel,   breinState.titel)   != 0 ||
      strcmp(nieuw.album,   breinState.album)   != 0 ||
      strcmp(nieuw.app,     breinState.app)     != 0 ||
      nieuw.koppelen   != breinState.koppelen  ||
      nieuw.heet       != breinState.heet;

  nieuw.revision = breinState.revision + (anders ? 1 : 0);
  breinState = nieuw;
}
