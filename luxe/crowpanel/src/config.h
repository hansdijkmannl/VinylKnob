#pragma once

// ---------------------------------------------------------------------------
// Elecrow CrowPanel 2.1" ESP32 Rotary Display — hardware
//
// Pinnen komen uit de wiki van Elecrow en zijn geverifieerd tegen hun eigen
// voorbeeldschets, example/RotaryScreen_2_1/RotaryScreen_2_1.ino in:
// https://github.com/Elecrow-RD/CrowPanel-2.1inch-HMI-ESP32-Rotary-Display-480-480-IPS-Round-Touch-Knob-Screen
//
// Alles hieronder komt letterlijk daaruit. Zie board.cpp voor de opstartvolgorde,
// die net zo min te raden was als de pinnen.
// ---------------------------------------------------------------------------

// -- draaiknop --------------------------------------------------------------
#define PIN_ENC_A        42
#define PIN_ENC_B        4

// Deze encoder telt andersom dan die van versie 1: rechtsom gaf een dalend
// volume. Gemeten op het echte paneel, 1 augustus 2026. Staat hier en niet in
// de instellingen omdat het een eigenschap van dít bord is, geen voorkeur.
#define ENC_INVERT       1
// De drukknop hangt niet aan de ESP32 maar aan de I/O-uitbreider, pin P5.
#define PCF_PIN_BUTTON   5

// -- I2C (aanraakchip en de uitbreider) -------------------------------------
#define PIN_I2C_SDA      38
#define PIN_I2C_SCL      39
#define PCF8574_ADDR     0x21
#define TOUCH_ADDR       0x15    // CST826, uit Elecrow's schets

// Elecrow trekt in hun eigen code 20 pixels van de y-waarde af. Dat is een
// kalibratie van dit paneel, geen afrondingsfout — laat staan tenzij tikken
// stelselmatig te hoog of te laag uitkomen.
#define TOUCH_Y_OFFSET   -20

// -- PCF8574-uitbreider -----------------------------------------------------
#define PCF_PIN_TOUCH_RST 0
#define PCF_PIN_TOUCH_INT 2
#define PCF_PIN_LCD_POWER 3
#define PCF_PIN_LCD_RESET 4

// -- scherm -----------------------------------------------------------------
#define PIN_BACKLIGHT    6
#define BACKLIGHT_CHAN   0       // LEDC-kanaal
#define BACKLIGHT_FREQ   5000
#define BACKLIGHT_BITS   8
#define BACKLIGHT_LEVEL  204     // Elecrow's standaardhelderheid, 80%

// Na zoveel seconden zonder aanraking of draaien zakt het scherm terug. Naast
// de bank is vol licht 's avonds hinderlijk, en het scheelt ook stroom. Elke
// aanraking of klik zet het meteen weer aan.
#define DEF_DIM_AFTER_S  45
#define DIM_LEVEL_PCT    18
#define SCREEN_W         480
#define SCREEN_H         480

// ST7701 over RGB-parallel. De drie draadjes hieronder (CS/SCK/SDA) zijn geen
// datapad maar de 3-draads SPI waarover het paneel zijn initialisatiereeks
// krijgt; de pixels lopen over de RGB-bus eronder.
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

// Paneeltiming, letterlijk uit Elecrow's schets. Deze getallen horen bij dit
// paneel; ze staan los van de ST7701-initialisatietabel.
#define LCD_HSYNC_FRONT  10
#define LCD_HSYNC_PULSE   4
#define LCD_HSYNC_BACK   20
#define LCD_VSYNC_FRONT  10
#define LCD_VSYNC_PULSE   4
#define LCD_VSYNC_BACK   20

// ---------------------------------------------------------------------------
// Instellingen — worden in NVS bewaard en zijn later via het brein te wijzigen
// ---------------------------------------------------------------------------
#define DEF_AVR_PORT           23
#define DEF_HALF_DB_PER_CLICK  1     // 1 stap = 0,5 dB
// Afgesteld op het echte paneel, 1 augustus 2026. Gemeten: één detent van deze
// encoder is precies één stap, dus rustig draaien geeft 0,5 dB — de fijnste stap
// die de Marantz kent. Het oude venster van 140 ms was sneller dan je normaal
// draait, waardoor je in de praktijk nooit uit die 0,5 dB kwam.
#define DEF_ACCEL_FACTOR       8     // snel draaien: 4,0 dB per detent
#define DEF_ACCEL_WINDOW_MS    250
#define DEF_ENC_DIVIDER        4     // quadratuur-overgangen per stap
// Veiligheidsplafond, los van wat de receiver zelf via MVMAX meldt; de firmware
// neemt de laagste van de twee. -15 bleek in de praktijk te knijpen.
#define DEF_VOL_MAX_DB         -6

#define DEF_LONG_PRESS_MS      1000  // vasthouden = aan/uit
#define DEF_DOUBLE_PRESS_MS    350   // dubbelklikvenster; 0 = uit
#define DEF_FAVOURITE_INPUT    0     // index in de ingangenlijst; -1 = uit

// Minimale tijd tussen commando's naar de AVR. Onder ~50 ms laat hij ze vallen.
#define CMD_MIN_INTERVAL_MS    60

// Hoe lang wifi weg mag zijn voordat de hele stack opnieuw wordt opgezet.
#define WIFI_RETRY_AFTER_MS    15000

// Het brein op de Pi. Vier seconden is ruim: een plaatkant duurt twintig
// minuten, dus er valt zelden iets te melden — maar zet je de naald neer, dan
// wil je het binnen een paar tellen zien.
#define BREIN_PORT             8791
#define BREIN_POLL_MS          4000
#define BREIN_BEZIG_MS         1000    // terwijl de Pi luistert
#define BREIN_RETRY_MS         30000   // na een paar missers: rustiger aan

// Terugvallen naar het volumescherm als je niets meer doet. Ruim genomen: in
// de ingangenlijst ben je aan het kijken en kiezen, en dan is vier seconden net
// te kort om rustig te bladeren.
#define IDLE_RETURN_MS         6000

#define MAX_INPUTS             8
#define AP_SSID                "MarantzKnob-setup"
// Bewust niet "marantzknob": zo heet de Pi, en die draait avahi én serveert de
// webinterface die je dagelijks opent. Twee apparaten die dezelfde naam bij de
// router aanmelden geeft een DNS die de ene keer het paneel en de andere keer
// de Pi teruggeeft.
#define MDNS_NAME              "marantzpaneel"
