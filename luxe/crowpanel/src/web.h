#pragma once

#include <Arduino.h>

void webBegin();
void webLoop();

// Wordt in main.cpp gezet: true als we het setup-accesspoint draaien in plaats
// van op je eigen wifi te zitten.
extern bool netApMode;

// Wordt door de webinterface gezet als er een herstart is gevraagd.
extern bool rebootRequested;
