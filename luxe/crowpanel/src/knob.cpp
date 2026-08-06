#include "knob.h"

#include "config.h"
#include "pcf.h"
#include "settings.h"

// ---------------------------------------------------------------------------
// Quadratuur, table-based, in een ISR. Ongewijzigd overgenomen uit versie 1.
// ---------------------------------------------------------------------------
static const int8_t ENC_TABLE[16] = {
     0, -1,  1,  0,
     1,  0,  0, -1,
    -1,  0,  0,  1,
     0,  1, -1,  0
};

static volatile uint8_t encPrevState = 0;
static volatile int32_t encSubSteps  = 0;

static void IRAM_ATTR encoderIsr() {
  const uint8_t cur = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  const int8_t step = ENC_TABLE[(encPrevState << 2) | cur];
  encSubSteps += ENC_INVERT ? -step : step;
  encPrevState = cur;
}

// ---------------------------------------------------------------------------
// Toestand van de drukknop
// ---------------------------------------------------------------------------
static bool     swStable        = true;    // true = los
static bool     swLastRead      = true;
static uint32_t swLastChange    = 0;
static uint32_t swPressedAt     = 0;
static uint32_t lastButtonRead  = 0;
static bool     turnedWhileHeld = false;
static bool     longFired       = false;
static bool     resetFired      = false;
static bool     consumedByDouble = false;
static bool     pendingSingle   = false;
static uint32_t pendingSingleAt = 0;
static uint32_t lastReleaseAt   = 0;

// Acht seconden vasthouden wist de wifi-gegevens.
static const uint32_t WIFI_RESET_HOLD_MS = 8000;

void knobBegin() {
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  pinMode(PIN_ENC_B, INPUT_PULLUP);
  encPrevState = (digitalRead(PIN_ENC_A) << 1) | digitalRead(PIN_ENC_B);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encoderIsr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encoderIsr, CHANGE);
}

KnobInput knobPoll() {
  KnobInput out;
  const uint32_t now = millis();

  // -- drukknop, via I2C en dus niet elke lus -------------------------------
  // Vijf milliseconden is ruim snel genoeg voor een vinger en houdt de I2C-bus
  // vrij voor de aanraakchip.
  bool pressEdge = false, releaseEdge = false;
  if (now - lastButtonRead >= 5) {
    lastButtonRead = now;
    const bool raw = pcfReadPin(PCF_PIN_BUTTON);      // hoog = los
    if (raw != swLastRead) {
      swLastRead   = raw;
      swLastChange = now;
    }
    if (now - swLastChange >= 25 && raw != swStable) {
      swStable = raw;
      if (!raw) pressEdge = true;
      else      releaseEdge = true;
    }
  }
  out.held = !swStable;

  // -- encoder --------------------------------------------------------------
  int32_t sub;
  noInterrupts();
  sub = encSubSteps;
  encSubSteps = 0;
  interrupts();

  static int32_t carry = 0;
  carry += sub;
  const int divider = settings.encDivider ? settings.encDivider : 4;
  out.steps = carry / divider;
  carry -= out.steps * divider;

  // -- net ingedrukt --------------------------------------------------------
  if (pressEdge) {
    if (settings.doublePressMs > 0 && pendingSingle &&
        now - lastReleaseAt <= settings.doublePressMs) {
      pendingSingle    = false;
      consumedByDouble = true;
      out.event = KnobEvent::DoublePress;
    } else {
      consumedByDouble = false;
    }
    swPressedAt     = now;
    turnedWhileHeld = false;
    longFired       = false;
    resetFired      = false;
  }

  if (out.steps != 0 && out.held) turnedWhileHeld = true;
  out.turnedWhileHeld = turnedWhileHeld && out.held;

  // -- vasthouden. Niet als het gebaar al een draai of dubbelklik was. -------
  if (out.held && !turnedWhileHeld && !consumedByDouble &&
      out.event == KnobEvent::None) {
    if (!longFired && now - swPressedAt >= settings.longPressMs) {
      longFired = true;
      out.event = KnobEvent::LongPress;
    } else if (!resetFired && now - swPressedAt >= WIFI_RESET_HOLD_MS) {
      resetFired = true;
      out.event = KnobEvent::WifiReset;
    }
  }

  // -- net losgelaten -------------------------------------------------------
  if (releaseEdge) {
    const bool handled = consumedByDouble || turnedWhileHeld || longFired || resetFired;
    if (!handled) {
      if (settings.doublePressMs > 0) {
        // Even afwachten of er een tweede klik komt.
        pendingSingle = true;
        lastReleaseAt = now;
        pendingSingleAt = now;
      } else if (out.event == KnobEvent::None) {
        out.event = KnobEvent::ShortPress;
      }
    }
    consumedByDouble = false;
  }

  // -- enkelklik die geen dubbelklik bleek ----------------------------------
  if (pendingSingle && now - pendingSingleAt > settings.doublePressMs &&
      out.event == KnobEvent::None) {
    pendingSingle = false;
    out.event = KnobEvent::ShortPress;
  }

  return out;
}
