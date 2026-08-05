#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// Wat het scherm moet kunnen — bewust los van hóé het getekend wordt.
//
// De bediening (knob.cpp) en de logica (main.cpp) praten alleen met deze
// functies. Er zijn twee implementaties:
//
//   ui_serial.cpp   schrijft naar de seriële poort. Daarmee is de hele
//                   bediening te bouwen en te testen zonder scherm.
//   ui_lvgl.cpp     tekent het echt, volgens luxe/mockup/. Die komt er zodra
//                   het paneel binnen is en de displaydriver van Elecrow erin
//                   zit — zie board.h.
//
// Die scheiding is er niet voor de netheid maar omdat het displaygedeelte het
// enige is dat pas met hardware op tafel te schrijven valt. De rest is nu al af.
// ---------------------------------------------------------------------------

enum class Screen : uint8_t {
  Volume,      // hoes als platenlabel, boog langs de rand
  Inputs,      // ingangenlijst
  Browse,      // platenkast doorbladeren
  Pairing,     // QR-code en IP, als er iets te koppelen valt
  Off,         // uit gezet vanuit de ingangenlijst; wakker met de knop
  Setup,       // eigen accesspoint, nog geen wifi
  NoAvr,       // wifi ja, receiver niet bereikbaar
};

// Welk scherm er nu staat, als korte naam ("volume", "off", ...). Staat in
// main.cpp — die houdt de schermtoestand bij — maar wordt hier bekendgemaakt
// omdat web.cpp hem nodig heeft voor de kopie van dit paneel in de
// webinterface. Zonder dit kon die kopie alleen het volumescherm nadoen.
const char *uiSchermNaam();

struct UiState {
  Screen   screen        = Screen::Setup;

  // volume
  float    volumeDb      = -80.0f;
  bool     haveVolume    = false;
  bool     muted         = false;
  bool     powered       = false;
  bool     turning       = false;   // toont het dB-getal tijdens het draaien

  // wat er speelt
  char     inputLabel[24] = "?";
  char     nowArtist[48]  = "";
  char     nowTitle[48]   = "";
  bool     haveArtwork    = false;
  bool     artworkIsLogo  = false;  // een app-logo, geen echte hoes
  char     sourceApp[24]  = "";     // "YouTube" als er geen hoes is
  bool     listening      = false;   // de Pi is nu aan het opnemen

  // keuzeschermen
  int      pickIndex      = 0;
  int      pickCount      = 0;
  char     pickLabel[24]  = "";
  char     pickPrev[24]   = "";
  char     pickNext[24]   = "";

  // hoeveel platen wachten er op een koppeling (0 = niets te doen)
  int      pairing        = 0;
  bool     piHot          = false;  // Pi te warm; anders niets tonen

  // De letter waar je zojuist heen sprong, groot in beeld. 0 = niet tonen.
  // Staat hier en niet in kast.cpp omdat het over tonen gaat en niet over
  // waar je bent: hoe lang hij blijft staan is een schermkeuze.
  char     shelfLetter    = 0;
  // Zou een keuze in de kast nu een koppeling zijn? Dan zegt het scherm dat,
  // want anders wijs je iets aan zonder te weten dat je iets vastlegt.
  bool     shelfLinkable  = false;
  bool     justLinked     = false;   // net gekoppeld; even bevestigen

  // netwerk
  char     ip[16]         = "";
  int      rssi           = 0;
};

void uiBegin();
void uiRender(const UiState &state);   // alleen aanroepen als er iets wijzigde
void uiTick();                          // per lus; voor animaties en aanrakingen

// Scherm 180 graden draaien zonder herstart. Handig als je de behuizing
// andersom hebt staan en het even wilt proberen.
void uiSetRotation(bool omgekeerd);

// Aanrakingen die het scherm terugmeldt aan de logica.
enum class Touch : uint8_t { None, InputLabel, Artwork, Confirm, Dismiss, Listen,
                             Pairing };
Touch uiTakeTouch();
