// ---------------------------------------------------------------------------
// Talking to the receiver over telnet (port 23).
//
// De receiver stuurt statuswijzigingen ongevraagd over dezelfde verbinding.
// Pick up the remote and an "MV52" arrives here unasked, and the screen follows
// straight away.
//
// Note: the receiver accepts only ONE telnet session at a time.
// ---------------------------------------------------------------------------

#include "marantz.h"

#include <WiFi.h>

#include "config.h"
#include "settings.h"

AvrState avrState;

static WiFiClient client;
static String   rxBuf;
static int      targetHalf     = -1;   // -1 = nothing to send
static uint32_t lastCmdSent    = 0;
static uint32_t lastConnectTry = 0;
static uint32_t txCount        = 0;
static uint32_t initQueryStep  = 0;    // >0 = opening queries still running
static uint32_t initQueryAt    = 0;

uint32_t avrTxCount() { return txCount; }

static void touched() { avrState.revision++; }

int avrVolumeCeilingHalf() {
  const int own = (settings.volMaxDb + 80) * 2;
  return constrain(min(avrState.volMaxHalf, own), 0, 196);
}

int avrPendingVolumeHalf() {
  return (targetHalf >= 0) ? targetHalf : avrState.volHalfSteps;
}

bool avrSend(const char *cmd) {
  if (!client.connected()) return false;
  client.print(cmd);
  client.print('\r');
  lastCmdSent = millis();
  txCount++;
  Serial.printf("-> %s\n", cmd);
  return true;
}

void avrSetVolumeHalf(int halfSteps) {
  targetHalf = constrain(halfSteps, 0, avrVolumeCeilingHalf());
  // Run ahead locally so the screen moves immediately; the receiver confirms
  // afterwards with its own MV message.
  avrState.volHalfSteps = targetHalf;
  touched();
}

void avrReconnect() {
  client.stop();
  avrState.connected = false;
  lastConnectTry = 0;
  touched();
}

// ---------------------------------------------------------------------------
// Antwoorden verwerken
// ---------------------------------------------------------------------------
static void applyInput(const String &code) {
  strlcpy(avrState.input, code.c_str(), sizeof(avrState.input));
  // If this input is in your list, use your label for it.
  const int idx = settingsFindInput(code.c_str());
  strlcpy(avrState.inputLabel,
          (idx >= 0) ? settings.inputs[idx].label : code.c_str(),
          sizeof(avrState.inputLabel));
}

static void handleResponse(const String &line) {
  if (line.length() < 2) return;
  Serial.printf("<- %s\n", line.c_str());

  // MVMAX has to be checked before MV, or the MV branch reads "MA".
  //
  // Note: MVMAX uses the same encoding as MV and can therefore carry a half
  // step. A real receiver answers "MVMAX 695", meaning 69.5 and not 695. This
  // was a plain toInt() at first, so the value fell through the check and the
  // ceiling stayed at 98.
  if (line.startsWith("MVMAX")) {
    String digits = line.substring(5);
    digits.trim();
    if (digits.length() >= 2 && isDigit(digits[0]) && isDigit(digits[1])) {
      int half = digits.substring(0, 2).toInt() * 2;
      if (digits.length() >= 3 && digits[2] == '5') half += 1;
      if (half > 0 && half <= 196) {
        avrState.volMaxHalf = half;
        touched();
      }
    }
    return;
  }

  if (line.startsWith("MV")) {
    const String digits = line.substring(2);
    if (digits.length() < 2 || !isDigit(digits[0]) || !isDigit(digits[1])) return;
    int half = digits.substring(0, 2).toInt() * 2;
    if (digits.length() >= 3 && digits[2] == '5') half += 1;
    // Do not jump back while we are still sending a higher setting ourselves;
    // otherwise the screen judders during a fast turn.
    if (targetHalf < 0) avrState.volHalfSteps = half;
    avrState.haveVolume = true;
    touched();
    return;
  }

  if (line.startsWith("MU")) {
    avrState.muted = line.endsWith("ON");
    touched();
    return;
  }

  // ZMON/ZMOFF (main zone) and PWON/PWSTANDBY (the whole unit).
  if (line.startsWith("ZM") || line.startsWith("PW")) {
    avrState.powered = line.endsWith("ON");
    touched();
    return;
  }

  if (line.startsWith("SI")) {
    applyInput(line.substring(2));
    touched();
  }
}

static void pump() {
  while (client.available()) {
    const char c = client.read();
    if (c == '\r' || c == '\n') {
      if (rxBuf.length()) handleResponse(rxBuf);
      rxBuf = "";
    } else if (rxBuf.length() < 64) {
      rxBuf += c;
    }
  }
}

// ---------------------------------------------------------------------------
// Verbinding + beginvragen
//
// The opening queries are spread across separate loop passes rather than using
// delay(), so the web interface keeps responding while it connects.
// ---------------------------------------------------------------------------
static void runInitQueries() {
  static const char *QUERIES[] = {"PW?", "ZM?", "MV?", "MU?", "SI?"};
  const size_t count = sizeof(QUERIES) / sizeof(QUERIES[0]);

  if (initQueryStep == 0 || initQueryStep > count) {
    initQueryStep = 0;
    return;
  }
  if (millis() - initQueryAt < CMD_MIN_INTERVAL_MS) return;

  avrSend(QUERIES[initQueryStep - 1]);
  initQueryAt = millis();
  initQueryStep++;
  if (initQueryStep > count) initQueryStep = 0;
}

static void maintainConnection() {
  if (client.connected()) {
    avrState.connected = true;
    return;
  }

  if (avrState.connected) {           // net weggevallen
    avrState.connected = false;
    rxBuf = "";
    touched();
  }

  if (WiFi.status() != WL_CONNECTED)  return;
  if (strlen(settings.avrHost) == 0)  return;
  if (lastConnectTry != 0 && millis() - lastConnectTry < 3000) return;
  lastConnectTry = millis();

  Serial.printf("Connecting to %s:%u ...\n", settings.avrHost, settings.avrPort);
  if (client.connect(settings.avrHost, settings.avrPort, 2000)) {
    client.setNoDelay(true);
    avrState.connected = true;
    initQueryStep = 1;
    initQueryAt   = 0;
    Serial.println("Verbonden.");
  } else {
    Serial.println("Connection failed.");
  }
  touched();
}

void avrLoop() {
  maintainConnection();
  pump();
  runInitQueries();

  // Send the latest volume, throttled. Builds the MV command:
  // hele dB = "MV45", halve dB = "MV455".
  if (targetHalf >= 0 && initQueryStep == 0 &&
      millis() - lastCmdSent >= CMD_MIN_INTERVAL_MS) {
    char cmd[12];
    const int whole = targetHalf / 2;
    if (targetHalf % 2) snprintf(cmd, sizeof(cmd), "MV%02d5", whole);
    else                snprintf(cmd, sizeof(cmd), "MV%02d",  whole);
    avrSend(cmd);        // if it fails on a dead connection we drop this
    targetHalf = -1;     // setting; the next click sends again
  }
}
