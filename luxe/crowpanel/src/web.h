#pragma once

#include <Arduino.h>

void webBegin();
void webLoop();

// Set in main.cpp: true when we are running the setup access point instead of
// sitting on your own network.
extern bool netApMode;

// Set by the web interface when a restart has been asked for.
extern bool rebootRequested;
