#pragma once

// ---------------------------------------------------------------------------
// Elecrow CrowPanel 2.1" ESP32 Rotary Display — hardware
//
// Pins come from Elecrow's wiki and are verified against their own
// voorbeeldschets, example/RotaryScreen_2_1/RotaryScreen_2_1.ino in:
// https://github.com/Elecrow-RD/CrowPanel-2.1inch-HMI-ESP32-Rotary-Display-480-480-IPS-Round-Touch-Knob-Screen
//
// Everything below comes verbatim from there. See board.cpp for the bring-up
// sequence, which was no more guessable than the pins.
// ---------------------------------------------------------------------------

// -- draaiknop --------------------------------------------------------------
#define PIN_ENC_A        42
#define PIN_ENC_B        4

// This encoder counts the other way round from version 1's: clockwise gave a
// falling volume. Measured on the real panel. It lives here and not in the
// settings because it is a property of this board, not a preference.
#define ENC_INVERT       1
// The push button hangs off the I/O expander, pin P5, not the ESP32.
#define PCF_PIN_BUTTON   5

// -- I2C (touch chip and the expander) --------------------------------------
#define PIN_I2C_SDA      38
#define PIN_I2C_SCL      39
#define PCF8574_ADDR     0x21
#define TOUCH_ADDR       0x15    // CST826, from Elecrow's sketch

// Elecrow's own code subtracts 20 pixels from the y value. That is a
// calibration of this panel, not a rounding error — leave it unless taps land
// consistently too high or too low.
#define TOUCH_Y_OFFSET   -20

// -- PCF8574 expander -------------------------------------------------------
#define PCF_PIN_TOUCH_RST 0
#define PCF_PIN_TOUCH_INT 2
#define PCF_PIN_LCD_POWER 3
#define PCF_PIN_LCD_RESET 4

// -- screen -----------------------------------------------------------------
#define PIN_BACKLIGHT    6
#define BACKLIGHT_CHAN   0       // LEDC channel
#define BACKLIGHT_FREQ   5000
#define BACKLIGHT_BITS   8
#define BACKLIGHT_LEVEL  204     // Elecrow's standaardhelderheid, 80%

// After this many seconds with no touch or turn the screen dims. Next to the
// sofa, full brightness is unpleasant in the evening, and it saves power too.
// Any touch or press brings it straight back.
#define DEF_DIM_AFTER_S  45
#define DIM_LEVEL_PCT    18
#define SCREEN_W         480
#define SCREEN_H         480

// ST7701 over parallel RGB. The three wires below (CS/SCK/SDA) are not a data
// path but the 3-wire SPI over which the panel receives its initialisation
// sequence; the pixels travel over the RGB bus underneath.
#define PIN_LCD_CS       16
#define PIN_LCD_SCK      2
#define PIN_LCD_SDA      1
#define PIN_LCD_DE       40
#define PIN_LCD_VSYNC    7
#define PIN_LCD_HSYNC    15
#define PIN_LCD_PCLK     41

#define PIN_LCD_R0  46
#define PIN_LCD_R1   3
#define PIN_LCD_R2   8
#define PIN_LCD_R3  18
#define PIN_LCD_R4  17
#define PIN_LCD_G0  14
#define PIN_LCD_G1  13
#define PIN_LCD_G2  12
#define PIN_LCD_G3  11
#define PIN_LCD_G4  10
#define PIN_LCD_G5   9
#define PIN_LCD_B0   5
#define PIN_LCD_B1  45
#define PIN_LCD_B2  48
#define PIN_LCD_B3  47
#define PIN_LCD_B4  21

// Panel timing, verbatim from Elecrow's sketch. These numbers belong to this
// panel; they are independent of the ST7701 initialisation table.
#define LCD_HSYNC_FRONT  10
#define LCD_HSYNC_PULSE   4
#define LCD_HSYNC_BACK   20
#define LCD_VSYNC_FRONT  10
#define LCD_VSYNC_PULSE   4
#define LCD_VSYNC_BACK   20

// ---------------------------------------------------------------------------
// Settings — stored in NVS and changeable later through the web interface
// ---------------------------------------------------------------------------
#define DEF_AVR_PORT           23
#define DEF_HALF_DB_PER_CLICK  1     // 1 step = 0.5 dB
// Tuned on the real panel. Measured: one detent of this encoder is exactly one
// step, so turning gently gives 0.5 dB — the finest step
// the receiver understands. The old 140 ms window was faster than anyone
// normally turns, so in practice you never got past that 0.5 dB.
#define DEF_ACCEL_FACTOR       8     // turning fast: 4.0 dB per detent
#define DEF_ACCEL_WINDOW_MS    250
#define DEF_ENC_DIVIDER        4     // quadrature transitions per step
// A safety ceiling, separate from what the receiver reports through MVMAX; the
// firmware takes the lower of the two. -15 turned out to pinch in practice.
#define DEF_VOL_MAX_DB         -6

#define DEF_LONG_PRESS_MS      1000  // hold = power on/off
#define DEF_DOUBLE_PRESS_MS    350   // double-press window; 0 = off
#define DEF_FAVOURITE_INPUT    0     // index into the input list; -1 = off

// Minimum gap between commands to the receiver. Below ~50 ms it drops them.
#define CMD_MIN_INTERVAL_MS    60

// How long Wi-Fi may be gone before the whole stack is brought up again.
#define WIFI_RETRY_AFTER_MS    15000

// The brain on the Pi. Four seconds is generous: a side lasts twenty minutes,
// so there is rarely anything to report — but put the needle down and you want
// to see it within a couple of beats.
#define BRAIN_PORT             8791
#define BRAIN_POLL_MS          4000
#define BRAIN_BUSY_MS         1000    // while the Pi is listening
#define BRAIN_RETRY_MS         30000   // after a few misses: ease off

// Fall back to the volume screen when you stop doing anything. Generous: in
// the input list you are looking and choosing, and four seconds is just too
// short to browse at your leisure.
#define IDLE_RETURN_MS         6000

#define MAX_INPUTS             8
#define AP_SSID                "MarantzKnob-setup"
// Deliberately not "marantzknob": that is the Pi, which runs avahi and serves
// the web interface you open daily. Two devices announcing the same name to the
// router gives you a DNS that resolves to the panel one time and the Pi the
// next.
#define MDNS_NAME              "marantzpanel"
