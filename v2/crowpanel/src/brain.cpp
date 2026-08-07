#include "brain.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"
#include "settings.h"

BrainState brainState;
bool brainWantsToListen = true;   // main.cpp sets this from the current input

static uint32_t nextPoll = 0;
static uint8_t  misses       = 0;

// The timeouts are deliberately short. This runs in the same loop that handles
// the knob, so every millisecond spent waiting here is felt in the volume. A Pi
// on your own network answers in tens of milliseconds; longer than that and it
// is not there, so waiting achieves nothing.
static const uint16_t CONNECT_TIMEOUT_MS = 400;
static const uint16_t READ_TIMEOUT_MS    = 800;

void brainBegin() {
  brainState = BrainState();
}

static void clear() {
  if (!brainState.reachable && !brainState.playing) return;
  brainState.reachable = false;
  brainState.playing     = false;
  brainState.listening   = false;
  brainState.onShelf     = false;
  brainState.canLink = false;
  brainState.haveArtwork   = false;
  brainState.artworkIsLogo = false;
  brainState.artist[0] = '\0';
  brainState.title[0]   = '\0';
  brainState.album[0]   = '\0';
  brainState.app[0]     = '\0';
  // And the question lapses with it: with the Pi gone there is nothing to hang
  // an answer on, so the shelf should not still be narrowed down to three.
  brainState.choiceCount = 0;
  brainState.revision++;
}

void brainAskLookup() {
  if (settings.brainHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return;
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/listen", settings.brainHost, BRAIN_PORT);
  HTTPClient http;
  http.setConnectTimeout(CONNECT_TIMEOUT_MS);
  http.setTimeout(READ_TIMEOUT_MS);
  if (!http.begin(url)) return;
  http.POST("");
  http.end();
  // Poll again straight away. Waiting six seconds (since the answer takes ten
  // anyway) was wrong thinking: the icon then stays dark all that time and your
  // tap looks like it never landed. The "listening" flag is there immediately.
  nextPoll = millis() + 300;
}

bool brainLink(uint16_t releaseId) {
  if (settings.brainHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return false;
  char url[112];
  snprintf(url, sizeof(url), "http://%s:%u/link?id=%u",
           settings.brainHost, BRAIN_PORT, (unsigned)releaseId);
  HTTPClient http;
  http.setConnectTimeout(CONNECT_TIMEOUT_MS);
  // Roomier than the rest: the brain records fingerprints here and that takes
  // longer than a poll. It stalls the loop briefly, but only ever on your own
  // press of the knob.
  http.setTimeout(8000);
  if (!http.begin(url)) return false;
  const int code = http.POST("");
  http.end();
  // Poll again at once, so the screen has the new name before you have had a
  // chance to look.
  nextPoll = millis() + 200;
  return code == HTTP_CODE_OK;
}

// One short POST to the Pi. Nothing comes back worth reading: these are all
// commands, and the thing that shows the result is the television.
static bool atvPost(const char *path) {
  if (settings.brainHost[0] == '\0' || WiFi.status() != WL_CONNECTED) return false;
  char url[160];
  snprintf(url, sizeof(url), "http://%s:%u%s", settings.brainHost, BRAIN_PORT, path);
  HTTPClient http;
  http.setConnectTimeout(CONNECT_TIMEOUT_MS);
  http.setTimeout(READ_TIMEOUT_MS);
  if (!http.begin(url)) return false;
  const int code = http.POST("");
  http.end();
  return code == HTTP_CODE_OK;
}

bool atvKey(const char *name) {
  char path[64];
  snprintf(path, sizeof(path), "/appletv/key?name=%s", name);
  return atvPost(path);
}

bool atvPower(bool on) {
  return atvPost(on ? "/appletv/power?on=1" : "/appletv/power?on=0");
}

bool atvLaunch(const char *bundleId) {
  char path[128];
  snprintf(path, sizeof(path), "/appletv/launch?id=%s", bundleId);
  return atvPost(path);
}

void brainLoop() {
  if (settings.brainHost[0] == '\0') return;      // no Pi configured
  if (WiFi.status() != WL_CONNECTED) return;

  const uint32_t now = millis();
  if (now < nextPoll) return;

  // Ease off after a few failures. Otherwise a Pi that is switched off holds
  // the loop up every few seconds.
  // Poll faster while the Pi is busy: that is when things actually change.
  const uint32_t interval = (misses >= 3)      ? BRAIN_RETRY_MS
                          : brainState.listening ? BRAIN_BUSY_MS
                                                : BRAIN_POLL_MS;
  nextPoll = now + interval;

  // Send along whether listening makes sense. With the receiver on the Apple
  // TV there is nothing to recognise and the Pi need not bother Shazam — which
  // is exactly what we wanted to be frugal with.
  char url[96];
  snprintf(url, sizeof(url), "http://%s:%u/now?listen=%d",
           settings.brainHost, BRAIN_PORT, brainWantsToListen ? 1 : 0);

  HTTPClient http;
  http.setConnectTimeout(CONNECT_TIMEOUT_MS);
  http.setTimeout(READ_TIMEOUT_MS);
  if (!http.begin(url)) { misses++; clear(); return; }

  const int code = http.GET();
  if (code != HTTP_CODE_OK) {
    http.end();
    if (misses < 255) misses++;
    clear();
    return;
  }

  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, http.getString());
  http.end();
  if (err) { if (misses < 255) misses++; return; }

  misses = 0;

  BrainState fresh;
  fresh.reachable = true;
  fresh.playing   = doc["playing"] | false;
  fresh.listening = doc["listening"] | false;
  fresh.onShelf   = doc["onShelf"]   | false;
  fresh.canLink = doc["canLink"] | false;
  fresh.haveArtwork   = doc["artwork"] | false;
  fresh.artworkIsLogo = doc["logo"] | false;
  fresh.linkable = doc["linkable"] | 0;
  fresh.hot     = doc["hot"] | false;
  strlcpy(fresh.artist, doc["artist"] | "", sizeof(fresh.artist));
  strlcpy(fresh.title,   doc["title"]   | "", sizeof(fresh.title));
  strlcpy(fresh.album,   doc["album"]   | "", sizeof(fresh.album));
  strlcpy(fresh.app,     doc["app"]     | "", sizeof(fresh.app));

  // Which of your records this track is on, when it is on more than one.
  for (JsonVariantConst v : doc["choices"].as<JsonArrayConst>()) {
    if (fresh.choiceCount >= SHELF_FILTER_MAX) break;
    fresh.choices[fresh.choiceCount++] = v.as<uint16_t>();
  }

  // Only bump the revision when something genuinely differs; otherwise the
  // screen redraws every few seconds for no reason.
  const bool differs =
      fresh.reachable != brainState.reachable ||
      fresh.playing     != brainState.playing     ||
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
      fresh.choiceCount != brainState.choiceCount ||
      memcmp(fresh.choices, brainState.choices,
             fresh.choiceCount * sizeof(uint16_t)) != 0 ||
      fresh.hot       != brainState.hot;

  if (fresh.choiceCount != brainState.choiceCount) {
    // Worth a line in the log: it is the only state here you cannot read off
    // the screen without opening the shelf first.
    Serial.printf("[brain] %d record%s to choose between\n",
                  fresh.choiceCount, fresh.choiceCount == 1 ? "" : "s");
  }

  fresh.revision = brainState.revision + (differs ? 1 : 0);
  brainState = fresh;
}
