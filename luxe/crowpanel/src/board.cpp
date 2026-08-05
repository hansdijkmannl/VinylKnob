// ---------------------------------------------------------------------------
// Paneel-initialisatie voor het Elecrow CrowPanel 2.1" Rotary Display.
//
// De volgorde hieronder is overgenomen uit Elecrow's eigen voorbeeldschets
// (example/RotaryScreen_2_1/RotaryScreen_2_1.ino) en is niet vrijblijvend: het
// LCD en de aanraakchip hangen allebei achter de PCF8574 en willen elk een
// eigen resetpuls voordat er over I2C of over de RGB-bus iets zinnigs gebeurt.
// Sla er een over en het paneel blijft zwart of de aanraakchip meldt zich niet.
//
// Wat hier NIET meer in zit is de ST7701-initialisatietabel. Die bleek geen
// paneelspecifiek raadsel maar gewoon `st7701_type5_init_operations` uit
// Arduino_GFX; Elecrow's kopie van die bibliotheek is byte voor byte gelijk aan
// upstream v1.3.1. Vandaar dat platformio.ini precies die tag vastpint — vanaf
// v1.3.5 is de API herschreven (Arduino_RGB_Display in plaats van
// Arduino_ST7701_RGBPanel) en staat er een andere waarde in register 0x36.
// ---------------------------------------------------------------------------

#include "board.h"

#include <Adafruit_CST8XX.h>
#include <Wire.h>

#include "config.h"
#include "pcf.h"

static Arduino_ESP32RGBPanel *bus = new Arduino_ESP32RGBPanel(
    PIN_LCD_CS, PIN_LCD_SCK, PIN_LCD_SDA,
    PIN_LCD_DE, PIN_LCD_VSYNC, PIN_LCD_HSYNC, PIN_LCD_PCLK,
    PIN_LCD_R0, PIN_LCD_R1, PIN_LCD_R2, PIN_LCD_R3, PIN_LCD_R4,
    PIN_LCD_G0, PIN_LCD_G1, PIN_LCD_G2, PIN_LCD_G3, PIN_LCD_G4, PIN_LCD_G5,
    PIN_LCD_B0, PIN_LCD_B1, PIN_LCD_B2, PIN_LCD_B3, PIN_LCD_B4);

Arduino_ST7701_RGBPanel *gfx = new Arduino_ST7701_RGBPanel(
    bus, GFX_NOT_DEFINED /* RST loopt via de PCF8574 */, 0 /* rotatie */,
    false /* IPS */, SCREEN_W, SCREEN_H,
    st7701_type5_init_operations, sizeof(st7701_type5_init_operations),
    true /* BGR */,
    LCD_HSYNC_FRONT, LCD_HSYNC_PULSE, LCD_HSYNC_BACK,
    LCD_VSYNC_FRONT, LCD_VSYNC_PULSE, LCD_VSYNC_BACK);

static Adafruit_CST8XX touch;
static bool touchOk = false;

// Een resetpuls zoals het paneel hem wil: hoog, laag, hoog.
static void resetPulse(uint8_t pin) {
  pcfWritePin(pin, true);
  delay(100);
  pcfWritePin(pin, false);
  delay(120);
  pcfWritePin(pin, true);
  delay(120);
}

void boardBegin() {
  pcfWritePin(PCF_PIN_LCD_POWER, true);
  delay(100);

  resetPulse(PCF_PIN_LCD_RESET);
  resetPulse(PCF_PIN_TOUCH_RST);

  // De INT-lijn van de aanraakchip wordt hier als uitgang hoog gehouden. Dat
  // ziet er vreemd uit, maar de CST826 leest die pin tijdens het opstarten om
  // zijn I2C-adres te kiezen; Elecrow doet het net zo.
  pcfWritePin(PCF_PIN_TOUCH_INT, true);
  delay(120);

  gfx->begin();
  gfx->fillScreen(BLACK);

  touchOk = touch.begin(&Wire, TOUCH_ADDR);
  Serial.println(touchOk ? F("[bord] aanraakchip gevonden")
                         : F("[bord] GEEN aanraakchip op 0x15"));

  ledcSetup(BACKLIGHT_CHAN, BACKLIGHT_FREQ, BACKLIGHT_BITS);
  ledcAttachPin(PIN_BACKLIGHT, BACKLIGHT_CHAN);
  ledcWrite(BACKLIGHT_CHAN, BACKLIGHT_LEVEL);

  // En de voedingslijn weer laag. Ook dit staat zo in Elecrow's schets: P3
  // schakelt niet het paneel zelf maar een hulplijn die na het initialiseren
  // omlaag hoort.
  pcfWritePin(PCF_PIN_LCD_POWER, false);
}

void boardBacklight(uint8_t level) {
  ledcWrite(BACKLIGHT_CHAN, level);
}

bool boardTouch(int16_t &x, int16_t &y) {
  if (!touchOk || !touch.touched()) return false;
  const CST_TS_Point p = touch.getPoint(0);
  x = p.x;
  y = p.y + TOUCH_Y_OFFSET;
  if (y < 0) y = 0;
  if (y >= SCREEN_H) y = SCREEN_H - 1;
  return true;
}
