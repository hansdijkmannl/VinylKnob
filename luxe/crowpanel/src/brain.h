#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// Wat er speelt, opgehaald bij de Pi.
//
// Waarom over HTTP en niet over de USB-kabel die er toch al ligt: die kabel
// draagt wel degelijk serieel (op de Pi verschijnt hij als /dev/ttyACM0), maar
// hem gebruiken zou een eigen protocol met framing vergen, een seriële client
// op de Pi, en het opgeven van de monitor waarmee dit paneel te volgen is. Het
// paneel zit al op wifi — dat moet, voor telnet naar de receiver — en de Pi
// serveert al HTTP. Eén GET is dan genoeg.
//
// De Pi is de kant die weet wat er speelt; het paneel vraagt het alleen op.
// Daarom staat hier geen logica over herkennen, alleen over ophalen.
// ---------------------------------------------------------------------------

struct BrainState {
  bool bereikbaar = false;
  bool speelt     = false;      // er loopt een plaat
  bool listening   = false;      // de Pi neemt nu op of zoekt op
  bool onShelf     = false;      // gevonden in je eigen Discogs-collectie
  // Er staat een opzoeking open die niets opleverde: wijs je nu een album aan
  // in de kast, dan wordt dat eraan gekoppeld en leert het apparaat deze kant.
  bool canLink = false;
  bool haveArtwork   = false;      // er staat een hoes klaar op /hoes
  bool artworkIsLogo = false;      // ...maar het is het app-logo, geen echte hoes
  char artist[48] = "";
  char title[64]   = "";
  char album[64]   = "";
  char app[24]     = "";      // "YouTube", als de Apple TV de bron is
  bool hot       = false;      // Pi op de hoogste ventilatorstand of geknepen
  uint8_t linkable = 0;         // platen die op een koppeling wachten
  uint32_t revision = 0;        // loopt op zodra er iets wijzigt
};

extern BrainState brainState;

// Zet main.cpp: heeft luisteren nu zin? Gaat mee bij elke peiling, zodat de Pi
// niet op de Apple TV staat te herkennen.
extern bool brainWantsToListen;

void brainBegin();
void brainLoop();               // per lus aanroepen; regelt zelf zijn tempo

// Koppel dit album aan de plaat die nu draait maar niet herkend werd. De Pi
// legt het vast en maakt er meteen een vingerafdruk van, zodat dezelfde kant de
// volgende keer zonder dienst herkend wordt. Geeft false als het misging.
bool brainLink(uint16_t releaseId);

// Vraag de Pi nu te luisteren. Gebruikt als de ingang naar je favoriet gaat:
// dat is het moment waarop je de naald neerzet.
void brainAskLookup();
