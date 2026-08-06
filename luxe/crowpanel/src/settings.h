#pragma once

#include <Arduino.h>
#include "config.h"

struct InputDef {
  char code[16];   // protocolnaam zonder "SI", bv. "PHONO"
  char label[20];  // wat op het schermpje komt
};

struct Settings {
  char     wifiSsid[33];
  char     wifiPass[65];
  char     avrHost[48];          // IP of hostnaam van de SR7015
  uint16_t avrPort;

  // Het brein op de Pi: waar de herkenning vandaan komt. Leeg = uit, dan
  // gedraagt het paneel zich als in fase 2 en toont het alleen volume.
  char     brainHost[48];

  uint8_t  halfDbPerClick;       // 1 = 0,5 dB per klik
  uint8_t  accelFactor;          // vermenigvuldiger bij snel draaien
  uint16_t accelWindowMs;        // wat "snel" betekent
  uint8_t  encDivider;           // quadratuur-overgangen per stap (1, 2 of 4)
  int8_t   volMaxDb;             // plafond in dB (-80 .. +18)

  uint8_t  brightness;           // achtergrondverlichting 10..255
  uint16_t dimAfterS;            // dimmen na zoveel seconden rust; 0 = nooit
  bool     rotated;              // scherm 180 graden gedraaid

  // Scherm uit zodra de hoofdzone uitgaat, en weer aan zodra hij aangaat. Zet
  // je de versterker uit met de afstandsbediening — of doet je Apple TV dat
  // via HDMI — dan blijft er anders een verlicht schermpje op de kast staan
  // bij een installatie die uit is.
  bool     offWithAmp;

  uint16_t longPressMs;          // vasthouden = aan/uit
  uint16_t doublePressMs;        // dubbelklikvenster; 0 = dubbelklik uit
  int8_t   favouriteInput;       // index voor de dubbelklik; -1 = uit


  uint8_t  inputCount;           // 0 .. MAX_INPUTS
  InputDef inputs[MAX_INPUTS];   // de lijst die je met indrukken+draaien doorloopt
};

extern Settings settings;

void settingsLoad();
void settingsSave();

// Wist de wifi-gegevens, zodat het bordje weer in setup-modus opstart.
void settingsClearWifi();

// Index van deze protocolcode in de ingangenlijst, of -1.
int settingsFindInput(const char *code);

// Serialiseert naar JSON voor de webinterface. Het wifi-wachtwoord gaat er
// nooit uit; in plaats daarvan staat er of er een wachtwoord bewaard is.
void settingsToJson(String &out);

// Neemt een gedeeltelijke JSON over. Alleen aanwezige velden worden gewijzigd,
// alles wordt geklemd op een geldig bereik. Retourneert false bij kapotte JSON.
bool settingsFromJson(const String &body, String &err, bool &wifiChanged);
