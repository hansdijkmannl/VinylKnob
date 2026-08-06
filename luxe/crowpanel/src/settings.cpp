#include "settings.h"

#include <ArduinoJson.h>
#include <Preferences.h>

Settings settings;

static Preferences prefs;
static const char *NS = "mknob";

// Factory list of inputs. You step through these by holding the knob and
// houden en te draaien.
static const InputDef DEFAULT_INPUTS[] = {
  {"PHONO", "Platenspeler"},
  {"CD",    "CD"},
  {"TV",    "TV"},
  {"BT",    "Bluetooth"},
};
static const uint8_t DEFAULT_INPUT_COUNT =
    sizeof(DEFAULT_INPUTS) / sizeof(DEFAULT_INPUTS[0]);

static void keyFor(char *buf, size_t n, const char *prefix, int i) {
  snprintf(buf, n, "%s%d", prefix, i);   // "code0", "label0", ...
}

void settingsLoad() {
  // Factory defaults first, then overwrite with whatever is in NVS.
  memset(&settings, 0, sizeof(settings));
  settings.avrPort        = DEF_AVR_PORT;
  settings.halfDbPerClick = DEF_HALF_DB_PER_CLICK;
  settings.accelFactor    = DEF_ACCEL_FACTOR;
  settings.accelWindowMs  = DEF_ACCEL_WINDOW_MS;
  settings.encDivider     = DEF_ENC_DIVIDER;
  settings.volMaxDb       = DEF_VOL_MAX_DB;
  settings.longPressMs    = DEF_LONG_PRESS_MS;
  settings.doublePressMs  = DEF_DOUBLE_PRESS_MS;
  settings.favouriteInput = DEF_FAVOURITE_INPUT;
  settings.inputCount     = DEFAULT_INPUT_COUNT;
  for (int i = 0; i < DEFAULT_INPUT_COUNT; i++) settings.inputs[i] = DEFAULT_INPUTS[i];

  prefs.begin(NS, true);   // read-only

  strlcpy(settings.wifiSsid, prefs.getString("ssid", "").c_str(), sizeof(settings.wifiSsid));
  strlcpy(settings.wifiPass, prefs.getString("pass", "").c_str(), sizeof(settings.wifiPass));
  strlcpy(settings.avrHost,  prefs.getString("host", "").c_str(), sizeof(settings.avrHost));
  strlcpy(settings.brainHost, prefs.getString("brein", "").c_str(), sizeof(settings.brainHost));
  settings.brightness = prefs.getUChar("bright", BACKLIGHT_LEVEL);
  settings.dimAfterS  = prefs.getUShort("dim", DEF_DIM_AFTER_S);
  settings.rotated    = prefs.getBool("rot", false);
  settings.offWithAmp = prefs.getBool("offamp", true);

  settings.avrPort        = prefs.getUShort("port",     settings.avrPort);
  settings.halfDbPerClick = prefs.getUChar ("step",     settings.halfDbPerClick);
  settings.accelFactor    = prefs.getUChar ("accel",    settings.accelFactor);
  settings.accelWindowMs  = prefs.getUShort("accelwin", settings.accelWindowMs);
  settings.encDivider     = prefs.getUChar ("encdiv",   settings.encDivider);
  settings.volMaxDb       = prefs.getChar  ("volmax",   settings.volMaxDb);
  settings.longPressMs    = prefs.getUShort("longms",   settings.longPressMs);
  settings.doublePressMs  = prefs.getUShort("dblms",    settings.doublePressMs);
  settings.favouriteInput = prefs.getChar  ("fav",      settings.favouriteInput);

  const uint8_t stored = prefs.getUChar("ninputs", 255);
  if (stored != 255) {
    settings.inputCount = min(stored, (uint8_t)MAX_INPUTS);
    for (int i = 0; i < settings.inputCount; i++) {
      char k[16];
      keyFor(k, sizeof(k), "code", i);
      String code = prefs.getString(k, "");
      keyFor(k, sizeof(k), "label", i);
      String label = prefs.getString(k, "");
      strlcpy(settings.inputs[i].code,  code.c_str(),  sizeof(settings.inputs[i].code));
      strlcpy(settings.inputs[i].label, label.c_str(), sizeof(settings.inputs[i].label));
    }
  }

  prefs.end();

  if (settings.favouriteInput >= settings.inputCount) settings.favouriteInput = -1;
}

void settingsSave() {
  prefs.begin(NS, false);

  prefs.putString("ssid", settings.wifiSsid);
  prefs.putString("pass", settings.wifiPass);
  prefs.putString("host", settings.avrHost);
  prefs.putString("brein", settings.brainHost);
  prefs.putUChar("bright", settings.brightness);
  prefs.putUShort("dim", settings.dimAfterS);
  prefs.putBool("rot", settings.rotated);
  prefs.putBool("offamp", settings.offWithAmp);
  prefs.putUShort("port",     settings.avrPort);
  prefs.putUChar ("step",     settings.halfDbPerClick);
  prefs.putUChar ("accel",    settings.accelFactor);
  prefs.putUShort("accelwin", settings.accelWindowMs);
  prefs.putUChar ("encdiv",   settings.encDivider);
  prefs.putChar  ("volmax",   settings.volMaxDb);
  prefs.putUShort("longms",   settings.longPressMs);
  prefs.putUShort("dblms",    settings.doublePressMs);
  prefs.putChar  ("fav",      settings.favouriteInput);

  prefs.putUChar("ninputs", settings.inputCount);
  for (int i = 0; i < settings.inputCount; i++) {
    char k[16];
    keyFor(k, sizeof(k), "code", i);
    prefs.putString(k, settings.inputs[i].code);
    keyFor(k, sizeof(k), "label", i);
    prefs.putString(k, settings.inputs[i].label);
  }

  prefs.end();
}

void settingsClearWifi() {
  prefs.begin(NS, false);
  prefs.remove("ssid");
  prefs.remove("pass");
  prefs.end();
  settings.wifiSsid[0] = '\0';
  settings.wifiPass[0] = '\0';
}

int settingsFindInput(const char *code) {
  for (int i = 0; i < settings.inputCount; i++)
    if (strcmp(settings.inputs[i].code, code) == 0) return i;
  return -1;
}

void settingsToJson(String &out) {
  JsonDocument doc;

  doc["wifiSsid"]       = settings.wifiSsid;
  doc["wifiPassSet"]    = strlen(settings.wifiPass) > 0;
  doc["avrHost"]        = settings.avrHost;
  doc["breinHost"]      = settings.brainHost;
  doc["brightness"]     = settings.brightness;
  doc["dimAfterS"]      = settings.dimAfterS;
  doc["rotated"]        = settings.rotated;
  doc["offWithAmp"]     = settings.offWithAmp;
  doc["avrPort"]        = settings.avrPort;
  doc["halfDbPerClick"] = settings.halfDbPerClick;
  doc["accelFactor"]    = settings.accelFactor;
  doc["accelWindowMs"]  = settings.accelWindowMs;
  doc["encDivider"]     = settings.encDivider;
  doc["volMaxDb"]       = settings.volMaxDb;
  doc["longPressMs"]    = settings.longPressMs;
  doc["doublePressMs"]  = settings.doublePressMs;
  doc["favouriteInput"] = settings.favouriteInput;
  doc["maxInputs"]      = MAX_INPUTS;

  JsonArray arr = doc["inputs"].to<JsonArray>();
  for (int i = 0; i < settings.inputCount; i++) {
    JsonObject o = arr.add<JsonObject>();
    o["code"]  = settings.inputs[i].code;
    o["label"] = settings.inputs[i].label;
  }

  serializeJson(doc, out);
}

bool settingsFromJson(const String &body, String &err, bool &wifiChanged) {
  JsonDocument doc;
  const DeserializationError e = deserializeJson(doc, body);
  if (e) {
    err = e.c_str();
    return false;
  }

  wifiChanged = false;

  if (doc["wifiSsid"].is<const char *>()) {
    const char *v = doc["wifiSsid"];
    if (strcmp(v, settings.wifiSsid) != 0) wifiChanged = true;
    strlcpy(settings.wifiSsid, v, sizeof(settings.wifiSsid));
  }
  // An empty password field means "leave it", not "clear it". Otherwise the
  // web interface would wipe your password every time you changed anything.
  if (doc["wifiPass"].is<const char *>()) {
    const char *v = doc["wifiPass"];
    if (strlen(v) > 0) {
      strlcpy(settings.wifiPass, v, sizeof(settings.wifiPass));
      wifiChanged = true;
    }
  }

  if (doc["avrHost"].is<const char *>())
    strlcpy(settings.avrHost, doc["avrHost"], sizeof(settings.avrHost));
  if (doc["breinHost"].is<const char *>())
    strlcpy(settings.brainHost, doc["breinHost"], sizeof(settings.brainHost));
  if (doc["brightness"].is<int>())
    settings.brightness = constrain((int)doc["brightness"], 10, 255);
  if (doc["dimAfterS"].is<int>())
    settings.dimAfterS = constrain((int)doc["dimAfterS"], 0, 3600);
  if (doc["rotated"].is<bool>())
    settings.rotated = doc["rotated"];
  if (doc["offWithAmp"].is<bool>())
    settings.offWithAmp = doc["offWithAmp"];

  if (!doc["avrPort"].isNull())
    settings.avrPort = constrain((int)doc["avrPort"], 1, 65535);
  if (!doc["halfDbPerClick"].isNull())
    settings.halfDbPerClick = constrain((int)doc["halfDbPerClick"], 1, 20);
  if (!doc["accelFactor"].isNull())
    settings.accelFactor = constrain((int)doc["accelFactor"], 1, 20);
  if (!doc["accelWindowMs"].isNull())
    settings.accelWindowMs = constrain((int)doc["accelWindowMs"], 40, 600);
  if (!doc["encDivider"].isNull()) {
    const int v = (int)doc["encDivider"];
    settings.encDivider = (v == 1 || v == 2) ? v : 4;
  }
  if (!doc["volMaxDb"].isNull())
    settings.volMaxDb = constrain((int)doc["volMaxDb"], -80, 18);
  if (!doc["longPressMs"].isNull())
    settings.longPressMs = constrain((int)doc["longPressMs"], 400, 3000);
  if (!doc["doublePressMs"].isNull()) {
    const int v = (int)doc["doublePressMs"];
    settings.doublePressMs = (v <= 0) ? 0 : constrain(v, 200, 800);
  }

  if (doc["inputs"].is<JsonArray>()) {
    JsonArray arr = doc["inputs"].as<JsonArray>();
    uint8_t n = 0;
    for (JsonObject o : arr) {
      if (n >= MAX_INPUTS) break;
      const char *code = o["code"] | "";
      if (strlen(code) == 0) continue;          // lege regels overslaan
      strlcpy(settings.inputs[n].code, code, sizeof(settings.inputs[n].code));
      const char *label = o["label"] | "";
      // Empty label? Use the protocol code; better than nothing.
      strlcpy(settings.inputs[n].label, strlen(label) ? label : code,
              sizeof(settings.inputs[n].label));
      n++;
    }
    settings.inputCount = n;
  }

  // The favourite comes after the list, because it indexes into it.
  if (!doc["favouriteInput"].isNull()) {
    const int v = (int)doc["favouriteInput"];
    settings.favouriteInput = (v >= 0 && v < settings.inputCount) ? (int8_t)v : -1;
  }
  if (settings.favouriteInput >= settings.inputCount) settings.favouriteInput = -1;

  settingsSave();
  return true;
}
