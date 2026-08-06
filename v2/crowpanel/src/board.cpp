// ---------------------------------------------------------------------------
// Panel bring-up for the Elecrow CrowPanel 2.1" Rotary Display.
//
// The order below comes from Elecrow's own example sketch
// (example/RotaryScreen_2_1/RotaryScreen_2_1.ino) and is not optional: the LCD
// and the touch chip both hang off the PCF8574 and each want their own reset
// pulse before anything sensible happens over I2C or the RGB bus. Skip one and
// the panel stays black, or the touch chip never announces itself.
//
// What is NOT in here any more is the ST7701 initialisation table. That turned
// out not to be a panel-specific riddle but plain
// `st7701_type5_init_operations` from Arduino_GFX; Elecrow's copy of that
// library is byte for byte identical to upstream v1.3.1. Which is why
// platformio.ini pins exactly that tag — from v1.3.5 the API was rewritten
// (Arduino_RGB_Display instead of Arduino_ST7701_RGBPanel) and register 0x36
// holds a different value.
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
    bus, GFX_NOT_DEFINED /* RST runs through the PCF8574 */, 0 /* rotation */,
    false /* IPS */, SCREEN_W, SCREEN_H,
    st7701_type5_init_operations, sizeof(st7701_type5_init_operations),
    true /* BGR */,
    LCD_HSYNC_FRONT, LCD_HSYNC_PULSE, LCD_HSYNC_BACK,
    LCD_VSYNC_FRONT, LCD_VSYNC_PULSE, LCD_VSYNC_BACK);

static Adafruit_CST8XX touch;
static bool touchOk = false;

// A reset pulse the way the panel wants it: high, low, high.
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

  // The touch chip's INT line is driven high as an output here. That looks odd,
  // but the CST826 reads that pin at boot to pick its I2C address; Elecrow does
  // the same.
  pcfWritePin(PCF_PIN_TOUCH_INT, true);
  delay(120);

  gfx->begin();
  gfx->fillScreen(BLACK);

  touchOk = touch.begin(&Wire, TOUCH_ADDR);
  Serial.println(touchOk ? F("[board] touch chip found")
                         : F("[board] NO touch chip at 0x15"));

  ledcSetup(BACKLIGHT_CHAN, BACKLIGHT_FREQ, BACKLIGHT_BITS);
  ledcAttachPin(PIN_BACKLIGHT, BACKLIGHT_CHAN);
  ledcWrite(BACKLIGHT_CHAN, BACKLIGHT_LEVEL);

  // And the power line back low. This is in Elecrow's sketch too: P3 does not
  // switch the panel itself but a helper line that after initialisation
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
