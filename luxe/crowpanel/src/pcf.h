#pragma once

#include <Arduino.h>

// ---------------------------------------------------------------------------
// PCF8574 I/O-uitbreider op 0x21.
//
// Op dit bord hangt er meer aan dan je zou verwachten: de drukknop van de
// draaiknop, maar ook de voeding en de reset van het LCD en de aanraakchip.
// Vandaar een gedeelde helper in plaats van drie plekken die hetzelfde doen.
//
// De PCF8574 is quasi-bidirectioneel: een pin lees je alleen goed als je er
// eerst een 1 naar geschreven hebt. Daarom houden we een schaduwbyte bij waarin
// alle ingangen hoog blijven staan.
// ---------------------------------------------------------------------------

void    pcfBegin();                          // Wire moet al gestart zijn
void    pcfWritePin(uint8_t pin, bool high);
bool    pcfReadPin(uint8_t pin);
uint8_t pcfReadAll();
