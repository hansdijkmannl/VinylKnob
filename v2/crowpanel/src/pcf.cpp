#include "pcf.h"

#include <Wire.h>

#include "config.h"

// Alles hoog: uitgangen inactief, ingangen leesbaar.
static uint8_t shadow = 0xFF;

static void flush() {
  Wire.beginTransmission(PCF8574_ADDR);
  Wire.write(shadow);
  Wire.endTransmission();
}

void pcfBegin() {
  shadow = 0xFF;
  flush();
}

void pcfWritePin(uint8_t pin, bool high) {
  if (high) shadow |= (1 << pin);
  else      shadow &= ~(1 << pin);
  flush();
}

uint8_t pcfReadAll() {
  if (Wire.requestFrom((uint8_t)PCF8574_ADDR, (uint8_t)1) != 1) return 0xFF;
  return Wire.read();
}

bool pcfReadPin(uint8_t pin) {
  return (pcfReadAll() >> pin) & 1;
}
