// ---------------------------------------------------------------------------
// Praten met de Marantz over telnet (poort 23).
//
// De receiver stuurt statuswijzigingen ongevraagd over dezelfde verbinding.
// Pak je de afstandsbediening, dan komt hier spontaan een "MV52" binnen en
// loopt het schermpje meteen mee.
//
// Let op: de AVR accepteert maar EEN telnet-sessie tegelijk.
// ---------------------------------------------------------------------------

#include "marantz.h"

#include <WiFi.h>

#include "config.h"
#include "settings.h"

AvrState avrState;

static WiFiClient client;
static String   rxBuf;
static int      targetHalf     = -1;   // -1 = niets te versturen
static uint32_t lastCmdSent    = 0;
static uint32_t lastConnectTry = 0;
static uint32_t txCount        = 0;
static uint32_t initQueryStep  = 0;    // >0 = beginvragen nog bezig
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
  // Lokaal vooruitlopen zodat het schermpje direct meebeweegt; de AVR
  // bevestigt daarna met een eigen MV-bericht.
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
  // Staat deze ingang in jouw lijst, gebruik dan jouw label.
  const int idx = settingsFindInput(code.c_str());
  strlcpy(avrState.inputLabel,
          (idx >= 0) ? settings.inputs[idx].label : code.c_str(),
          sizeof(avrState.inputLabel));
}

static void handleResponse(const String &line) {
  if (line.length() < 2) return;
  Serial.printf("<- %s\n", line.c_str());

  // MVMAX moet voor MV gecontroleerd worden, anders leest de MV-tak "MA".
  //
  // Let op: MVMAX gebruikt dezelfde codering als MV en kan dus een halve stap
  // bevatten. Een echte SR7015 antwoordt "MVMAX 695", oftewel 69,5 en niet 695.
  // Dit stond er eerst als een gewone toInt(), waardoor de waarde door de
  // controle viel en het plafond op 98 bleef staan.
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
    // Niet terugspringen als we zelf nog een hogere stand aan het versturen
    // zijn; anders schokt het schermpje tijdens snel draaien.
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

  // ZMON/ZMOFF (hoofdzone) en PWON/PWSTANDBY (heel toestel).
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
// De beginvragen worden uitgesmeerd over losse loop-rondes in plaats van met
// delay(), zodat de webinterface tijdens het verbinden blijft reageren.
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

  Serial.printf("Verbinden met %s:%u ...\n", settings.avrHost, settings.avrPort);
  if (client.connect(settings.avrHost, settings.avrPort, 2000)) {
    client.setNoDelay(true);
    avrState.connected = true;
    initQueryStep = 1;
    initQueryAt   = 0;
    Serial.println("Verbonden.");
  } else {
    Serial.println("Verbinden mislukt.");
  }
  touched();
}

void avrLoop() {
  maintainConnection();
  pump();
  runInitQueries();

  // Laatste volumestand versturen, gethrottled. Bouwt het MV-commando:
  // hele dB = "MV45", halve dB = "MV455".
  if (targetHalf >= 0 && initQueryStep == 0 &&
      millis() - lastCmdSent >= CMD_MIN_INTERVAL_MS) {
    char cmd[12];
    const int whole = targetHalf / 2;
    if (targetHalf % 2) snprintf(cmd, sizeof(cmd), "MV%02d5", whole);
    else                snprintf(cmd, sizeof(cmd), "MV%02d",  whole);
    avrSend(cmd);        // mislukt hij door een dode verbinding, dan laten we
    targetHalf = -1;     // deze stand vallen; de volgende klik stuurt opnieuw
  }
}
