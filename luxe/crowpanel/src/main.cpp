// ---------------------------------------------------------------------------
// MarantzKnob luxe — firmware voor het Elecrow CrowPanel 2.1" Rotary Display.
//
// Fase 2 uit luxe/PLAN.md: het paneel als bediening. Telnet naar de SR7015,
// volume met de knop, ingang via het scherm. Nog zonder de Pi — die komt in
// fase 4 en voegt herkenning en hoezen toe.
//
// Bediening volgens luxe/mockup/:
//   draaien                  volume; in een keuzescherm de lijstpositie
//   kort drukken             mute aan/uit
//   dubbel drukken           direct naar je favoriete ingang
//   vasthouden (1 s)         versterker aan/uit
//   vasthouden (8 s)         wifi wissen, opstarten in setup-modus
//   tik op de ingangsnaam    ingangenlijst
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "brain.h"
#include "config.h"
#include "board.h"
#include "artwork.h"
#include "shelf.h"
#include "knob.h"
#include "marantz.h"
#include "pcf.h"
#include "settings.h"
#include "ui.h"
#include "web.h"

bool netApMode = false;                // web.cpp leest dit
// rebootRequested wordt in web.cpp gedefinieerd; web.h verklaart hem extern.

static UiState ui;
static bool     uiDirty      = true;
static uint32_t lastRevision = 0;
static uint32_t idleReturnAt = 0;
static uint32_t turningUntil = 0;
static uint32_t ownListenUntil = 0;   // eigen tik, tot de Pi het overneemt

// De grote letter in de platenkast: tot wanneer hij blijft staan.
static const uint32_t LETTER_MS = 900;
static uint32_t letterUntil = 0;

// Hoe lang "gekoppeld" in beeld blijft nadat je een album aan een onherkende
// plaat hebt gehangen.
static const uint32_t LINKED_MS = 3000;
static uint32_t linkedUntil = 0;

// Zelf een album aangewezen. Blijft staan tot het brein iets anders meldt --
// speelt er even later echt een plaat, dan wint die. Dat is met opzet: wat er
// werkelijk klinkt is waarheid, wat jij aanwees was een keuze.
static bool     userPicked = false;
static uint32_t pickedAtRevision = 0;
static char     pickedArtist[48] = "";
static char     pickedTitle[48]   = "";

// -- schermhelderheid -------------------------------------------------------
// Naast de bank is vol licht 's avonds hinderlijk. Elke aanraking of klik zet
// hem meteen weer aan; dimmen gaat vanzelf als je een tijd niets doet.
static uint32_t lastTouchAt = 0;
static bool     dimmed           = false;

static void screenWake() {
  lastTouchAt = millis();

  // Stond hij uit, dan is elke aanraking of klik het aanknopje. Dat is het hele
  // antwoord op "kan ik hem ook weer aanzetten met de knop": ja, en met de
  // dubbele functie dat je meteen weer bij het volume zit.
  if (ui.screen == Screen::Off) {
    ui.screen = Screen::Volume;
    uiDirty = true;
  }
  if (dimmed) dimmed = false;
  boardBacklight(settings.brightness);
}

static void screenDimLoop() {
  if (ui.screen == Screen::Off) return;      // uit is uit

  // Verandert de instelling terwijl je aan de schuif zit, dan meteen toepassen.
  // Anders zou "realtime" alleen op papier staan.
  static uint8_t appliedBrightness = 0;
  if (!dimmed && appliedBrightness != settings.brightness) {
    appliedBrightness = settings.brightness;
    boardBacklight(appliedBrightness);
  }
  // Zet je de stand om in de webinterface, dan meteen toepassen.
  static int8_t appliedRotation = -1;
  if (appliedRotation != (int8_t)settings.rotated) {
    appliedRotation = settings.rotated;
    uiSetRotation(settings.rotated);
    uiDirty = true;
  }

  if (settings.dimAfterS == 0 || dimmed) return;
  if (millis() - lastTouchAt < (uint32_t)settings.dimAfterS * 1000) return;
  dimmed = true;
  boardBacklight((settings.brightness * DIM_LEVEL_PCT) / 100);
}

// Eén wachtrijplekje, zodat een ingangkeuze na een ZMON netjes op afstand van
// het vorige commando gaat zonder de lus te blokkeren.
static char     pendingCmd[24] = "";
static uint32_t pendingAt      = 0;

// Kandidaat-ingang die nog niet verstuurd is.
static int      pickIndex     = 0;

// Twee regels onder aan de ingangenlijst die geen ingang zijn maar een handeling.
// Ze horen daar omdat je ze op hetzelfde moment nodig hebt: de plaat is klaar,
// je draait één keer door en zet het geheel uit.
static const char *EXTRA[] = { "Turn Off", "Turn Off + Amp" };
static const int   EXTRA_N = 2;

static int pickCount() { return settings.inputCount + EXTRA_N; }

// Staat de receiver op je favoriete ingang — de platenspeler? Dat bepaalt of de
// Pi mag meeluisteren; op de Apple TV valt er niets te herkennen want die weet
// het zelf. Wát er getoond wordt bepaalt de Pi, niet dit.
static bool onTurntable() {
  return settings.favouriteInput >= 0 &&
         settings.favouriteInput < settings.inputCount &&
         strcmp(avrState.input, settings.inputs[settings.favouriteInput].code) == 0;
}

static const char *pickName(int i) {
  const int n = pickCount();
  if (n <= 0) return "";
  const int k = ((i % n) + n) % n;
  return (k < settings.inputCount) ? settings.inputs[k].label : EXTRA[k - settings.inputCount];
}

static void queueCommand(const char *cmd, uint32_t delayMs) {
  strlcpy(pendingCmd, cmd, sizeof(pendingCmd));
  pendingAt = millis() + delayMs;
}

static void refreshUi();          // staat verderop; hier alvast bekend maken
static void pickAlbum();

// Voor web.cpp: de volgorde is die van enum class Screen in ui.h.
const char *uiScreenName() {
  static const char *NAMES[] = {"volume", "inputs", "browse",
                                "pairing", "off", "setup", "noavr"};
  const uint8_t i = (uint8_t)ui.screen;
  return i < (sizeof(NAMES) / sizeof(NAMES[0])) ? NAMES[i] : "?";
}

// Alles uit: scherm zwart, en desgevraagd de versterker mee. De Pi blijft
// draaien — hij voedt dit paneel via USB, dus hem afsluiten zou betekenen dat
// je hem daarna alleen met een stekker weer aan krijgt.
static void powerDown(bool alsoAmplifier) {
  if (alsoAmplifier) avrSend("ZMOFF");
  ui.screen = Screen::Off;
  boardBacklight(0);
  refreshUi();
}

// Meelopen met de versterker.
//
// Zet je het geheel uit met de afstandsbediening, of doet je Apple TV dat via
// HDMI, dan hoort dit schermpje niet als enige te blijven branden op een kast
// die verder donker is. Andersom net zo: gaat de zone aan, dan wil je meteen
// je volume zien zonder eerst het glas aan te raken.
//
// Alleen met een levende verbinding én een antwoord van de receiver. Zonder die
// twee voorwaarden zou een wegvallend netwerk het scherm zwart maken terwijl er
// niets aan de hand is: `powered` staat dan nog op zijn laatst bekende waarde,
// en vlak na verbinden staat hij op de beginwaarde false zonder dat er ooit een
// ZM- of PW-antwoord is geweest. haveVolume is het bewijs dat er werkelijk
// gepraat is.
//
// Ook de eerste meting telt mee, en dat is met opzet: valt de stroom 's nachts
// even weg, dan start dit paneel opnieuw op naast een installatie die uit staat,
// en dan hoort het niet de rest van de nacht te blijven branden.
static int8_t previousPower = -1;          // -1 = nog niets gezien

static void followAmplifier() {
  if (!avrState.connected || !avrState.haveVolume) { previousPower = -1; return; }

  const int8_t now = avrState.powered ? 1 : 0;
  if (now == previousPower) return;
  const bool first = previousPower < 0;
  previousPower = now;

  if (!settings.offWithAmp) return;
  // Bij de allereerste meting alleen dóven, nooit wekken: anders licht het
  // scherm op omdat het paneel opnieuw opstartte, niet omdat jij iets deed.
  if (now == 0)       powerDown(false);      // versterker uit: scherm mee
  else if (!first)  screenWake();     // en weer aan zodra hij aangaat
}

static void sendInput(const char *code) {
  char cmd[24];
  snprintf(cmd, sizeof(cmd), "SI%s", code);
  if (!avrState.powered) {
    avrSend("ZMON");
    queueCommand(cmd, CMD_MIN_INTERVAL_MS * 2);
  } else {
    avrSend(cmd);
  }
}

// ---------------------------------------------------------------------------
// Schermtoestand bijwerken
// ---------------------------------------------------------------------------
static void refreshUi() {
  ui.volumeDb   = avrState.volHalfSteps / 2.0f - 80.0f;
  ui.haveVolume = avrState.haveVolume;
  ui.muted      = avrState.muted;
  ui.powered    = avrState.powered;
  ui.turning    = millis() < turningUntil;
  strlcpy(ui.inputLabel, avrState.inputLabel, sizeof(ui.inputLabel));
  // Tonen wat de Pi meldt, wat de bron ook is. Hij stuurt de platenspeler door
  // de microfoon en alles daarbuiten langs de Apple TV; speelt die niets, dan
  // komt er niets — precies het gedrag dat we bij de Xbox willen, zonder dat
  // dit paneel daar iets van hoeft te weten.
  brainWantsToListen = onTurntable();
  // Het brein heeft iets nieuws gemeld: dan vervalt je eigen keuze.
  if (userPicked && brainState.revision != pickedAtRevision) userPicked = false;

  if (userPicked) {
    strlcpy(ui.nowArtist, pickedArtist, sizeof(ui.nowArtist));
    strlcpy(ui.nowTitle,  pickedTitle,   sizeof(ui.nowTitle));
  } else {
    strlcpy(ui.nowArtist, brainState.artist, sizeof(ui.nowArtist));
    strlcpy(ui.nowTitle,  brainState.album[0] ? brainState.album : brainState.title,
            sizeof(ui.nowTitle));
  }
  ui.shelfLetter = (millis() < letterUntil) ? shelfLetterAt(shelfIndex()) : 0;
  ui.shelfLinkable = brainState.canLink;
  ui.justLinked    = millis() < linkedUntil;
  ui.haveArtwork   = brainState.haveArtwork;
  ui.artworkIsLogo = brainState.artworkIsLogo;
  strlcpy(ui.sourceApp, brainState.app, sizeof(ui.sourceApp));
  ui.pairing     = brainState.linkable;
  ui.piHot       = brainState.hot;
  ui.listening   = brainState.listening || millis() < ownListenUntil;
  ui.rssi = netApMode ? 0 : WiFi.RSSI();
  strlcpy(ui.ip, netApMode ? WiFi.softAPIP().toString().c_str()
                           : WiFi.localIP().toString().c_str(), sizeof(ui.ip));

  if (ui.screen == Screen::Off)       { /* blijft uit tot je hem aanraakt */ }
  else if (netApMode)                 ui.screen = Screen::Setup;
  else if (!avrState.connected)       ui.screen = Screen::NoAvr;
  else if (ui.screen == Screen::Setup || ui.screen == Screen::NoAvr)
                                      ui.screen = Screen::Volume;

  if (ui.screen == Screen::Inputs) {
    ui.pickCount = pickCount();
    ui.pickIndex = pickIndex;
    strlcpy(ui.pickLabel, pickName(pickIndex), sizeof(ui.pickLabel));
    strlcpy(ui.pickPrev, pickCount() > 1 ? pickName(pickIndex - 1) : "", sizeof(ui.pickPrev));
    strlcpy(ui.pickNext, pickCount() > 1 ? pickName(pickIndex + 1) : "", sizeof(ui.pickNext));
  }
  uiDirty = true;
}

static void enterInputs() {
  if (settings.inputCount == 0) return;
  const int found = settingsFindInput(avrState.input);
  pickIndex = (found >= 0) ? found : 0;
  ui.screen = Screen::Inputs;
  idleReturnAt = millis() + IDLE_RETURN_MS;
  refreshUi();
}

static void leaveToVolume() {
  ui.screen = Screen::Volume;
  refreshUi();
}

// De platenkast in. De lijst wordt bij de eerste keer opgehaald en daarna
// bewaard: 549 namen zijn 25 kB en veranderen hooguit als je iets nieuws koopt.
static void enterBrowse() {
  if (settings.brainHost[0] == '\0') return;      // zonder Pi geen kast
  if (!shelfLoaded()) shelfLoad(settings.brainHost, BRAIN_PORT);

  // Beginnen bij de plaat die nu draait, als die in de kast staat. Anders sta je
  // elke keer weer bij de A terwijl je net naar iets zat te luisteren, en dat is
  // precies het album waarvan je wil weten wat ernaast staat.
  if (shelfLoaded() && brainState.onShelf && brainState.album[0]) {
    for (int i = 0; i < shelfCount(); i++) {
      if (strcmp(shelfTitle(i), brainState.album) == 0) { shelfSet(i); break; }
    }
  }
  ui.screen = Screen::Browse;
  letterUntil = 0;
  idleReturnAt = millis() + IDLE_RETURN_MS * 3;
  refreshUi();
}

// Een album aanwijzen.
//
// Twee dingen tegelijk, en welke ervan gebeurt hangt af van wat er speelt.
//
// Draait er iets dat niet herkend werd, dan is dit een koppeling: het brein
// hangt jouw keuze aan die luisterbeurt en legt het bewaarde fragment vast als
// vingerafdruk. Daarmee kent dit apparaat die kant voortaan zelf, zonder
// dienst. Dat is de les die alleen jij kon geven, en dit is het moment waarop
// je hem kunt geven — met de naald er nog in en de hoes in je hand, in plaats
// van 's avonds met je telefoon door een wachtrij.
//
// Speelt er niets bijzonders, dan is het alleen "laat zien": de hoes komt
// schermvullend terug. Opleggen kan dit apparaat niet.
static void pickAlbum() {
  const int i = shelfIndex();
  if (!shelfLoaded() || i < 0) { leaveToVolume(); return; }

  const bool linkable = brainState.canLink;
  if (linkable) brainLink(shelfReleaseId(i));

  strlcpy(pickedArtist, shelfArtist(i), sizeof(pickedArtist));
  strlcpy(pickedTitle,   shelfTitle(i),   sizeof(pickedTitle));
  userPicked   = true;
  pickedAtRevision = brainState.revision;
  // Bij een koppeling gaat de melding een paar tellen in beeld: je hebt net iets
  // vastgelegd, en dan wil je bevestigd zien dat het aankwam.
  linkedUntil  = linkable ? millis() + LINKED_MS : 0;

  if (!artworkLoadAlbum(settings.brainHost, BRAIN_PORT, shelfReleaseId(i))) artworkClear();
  leaveToVolume();
}

// ---------------------------------------------------------------------------
// Gebaren
// ---------------------------------------------------------------------------
static void changeVolume(int steps) {
  static uint32_t lastStepAt = 0;
  const uint32_t now = millis();
  const bool fast = (now - lastStepAt) < settings.accelWindowMs;
  lastStepAt = now;

  if (!avrState.haveVolume) return;

  const int size = settings.halfDbPerClick * (fast ? settings.accelFactor : 1);
  avrSetVolumeHalf(avrPendingVolumeHalf() + steps * size);

  if (avrState.muted) {                       // draaien heft mute op
    avrSend("MUOFF");
    avrState.muted = false;
  }
  turningUntil = now + 1600;                  // dB-getal even tonen
}

static void scrollInputs(int steps) {
  const int n = pickCount();
  if (n == 0) return;
  pickIndex = ((pickIndex + steps) % n + n) % n;

  // Bewust géén automatische bevestiging. Versie 1 had die wel — daar was geen
  // scherm, dus draaien wás de keuze, en een uitstel van 250 ms voorkwam dat de
  // receiver elke tussenliggende ingang aantikte. Hier is er een lijst om naar
  // te kijken en een druk om te bevestigen, en dan is meesturen tijdens het
  // bladeren geen voorzichtigheid meer maar een fout: je komt nooit voorbij de
  // eerste ingang zonder er even in te belanden.
  idleReturnAt = millis() + IDLE_RETURN_MS;
}

// Wat er gebeurt als je in de lijst bevestigt: een ingang kiezen, of een van de
// twee uitzet-regels uitvoeren.
static void confirmInput() {
  if (pickIndex >= settings.inputCount) {
    powerDown(pickIndex == settings.inputCount + 1);   // tweede regel = met versterker
    return;
  }
  if (pickIndex >= 0 && pickIndex < settings.inputCount)
    sendInput(settings.inputs[pickIndex].code);
  leaveToVolume();
}

static void handleKnob() {
  const KnobInput in = knobPoll();

  if (in.steps != 0 || in.event != KnobEvent::None) screenWake();

  if (in.steps != 0) {
    if (ui.screen == Screen::Browse) {
      // In de kast doet de knop iets anders. Ingedrukt draaien springt per
      // letter: met 549 albums is stap voor stap draaien geen doen, en dit is
      // dezelfde sprongindex als de letterring in de webinterface.
      if (in.held) {
        for (int i = 0; i < abs(in.steps); i++) shelfJump(in.steps > 0 ? 1 : -1);
        // De letter waar je landde groot in beeld, zolang je springt en nog
        // even daarna. Veertien pixels langs de rand zijn te weinig om tijdens
        // het draaien te lezen; hierop hoef je niet te zoeken.
        letterUntil = millis() + LETTER_MS;
      } else {
        shelfMove(in.steps);
        letterUntil = 0;               // gewoon bladeren: de letter mag weg
      }
      idleReturnAt = millis() + IDLE_RETURN_MS * 3;
    } else if (in.held) {
      // Indrukken en draaien loopt de ingangen door. Stond wel in de
      // documentatie maar niet in de code — dit is de reden dat je het niet
      // hoefde te zoeken op het scherm.
      if (ui.screen != Screen::Inputs) enterInputs();
      scrollInputs(in.steps);
    } else if (ui.screen == Screen::Inputs) {
      scrollInputs(in.steps);
    } else {
      changeVolume(in.steps);
    }
    refreshUi();
  }

  switch (in.event) {
    case KnobEvent::ShortPress:
      // knob.cpp onderdrukt de korte druk al als je tijdens het indrukken hebt
      // gedraaid, dus hier hoeft alleen het keuzescherm afgehandeld.
      if (ui.screen == Screen::Inputs) {          // bevestigen
        confirmInput();
      } else if (ui.screen == Screen::Browse) {
        pickAlbum();
      } else {
        avrSend(avrState.muted ? "MUOFF" : "MUON");
      }
      break;

    case KnobEvent::DoublePress:
      if (settings.favouriteInput >= 0 && settings.favouriteInput < settings.inputCount)
        sendInput(settings.inputs[settings.favouriteInput].code);
      leaveToVolume();
      break;

    case KnobEvent::LongPress:
      avrSend(avrState.powered ? "ZMOFF" : "ZMON");
      break;

    case KnobEvent::WifiReset:
      Serial.println(F("Wifi-gegevens gewist; opstarten in setup-modus."));
      settingsClearWifi();
      rebootRequested = true;
      break;

    case KnobEvent::None:
      break;
  }
}

static void handleTouch() {
  const Touch tik = uiTakeTouch();
  if (tik != Touch::None) screenWake();
  switch (tik) {
    case Touch::InputLabel: enterInputs();   break;
    case Touch::Confirm:
      if (ui.screen == Screen::Inputs) confirmInput();
      else                             leaveToVolume();
      break;
    case Touch::Listen:
      // Meteen oplichten op je eigen tik, zonder te wachten op bevestiging van
      // de Pi. Die komt een fractie later en neemt het over; blijft hij uit,
      // dan dooft dit vanzelf. Een knop die pas na een ronde reageert voelt
      // stuk, ook al is er niets mis.
      brainAskLookup();
      ownListenUntil = millis() + 4000;
      refreshUi();
      break;
    case Touch::Dismiss:    leaveToVolume(); break;
    case Touch::Artwork:
      enterBrowse();
      break;
    case Touch::Pairing:
      // De QR-code zat eerst achter een tik op de hoes. Nu de platenkast daar
      // zit heeft het stipje zijn eigen aanraakvlak — ruim, want tien pixels
      // raak je niet met een vinger.
      if (brainState.linkable > 0) {
        ui.screen = Screen::Pairing;
        idleReturnAt = millis() + IDLE_RETURN_MS * 3;
        refreshUi();
      }
      break;
    case Touch::None:       break;
  }
}

// ---------------------------------------------------------------------------
// Netwerk
// ---------------------------------------------------------------------------
static void startAccessPoint() {
  netApMode = true;
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID);
  Serial.printf("Setup-accesspoint \"%s\" op %s\n", AP_SSID,
                WiFi.softAPIP().toString().c_str());
  refreshUi();
}

static void connectWifi() {
  if (strlen(settings.wifiSsid) == 0) {
    startAccessPoint();
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                 // anders voelt de knop merkbaar traag
  WiFi.setHostname(MDNS_NAME);
  WiFi.begin(settings.wifiSsid, settings.wifiPass);
  Serial.printf("Verbinden met wifi \"%s\"...\n", settings.wifiSsid);

  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 25000) delay(200);

  if (WiFi.status() != WL_CONNECTED) {
    startAccessPoint();
    return;
  }
  netApMode = false;
  Serial.printf("Wifi verbonden, IP %s\n", WiFi.localIP().toString().c_str());
  refreshUi();
}

static void maintainWifi() {
  static uint32_t downSince = 0;
  if (netApMode) return;

  if (WiFi.status() != WL_CONNECTED) {
    const uint32_t now = millis();
    if (downSince == 0) downSince = now;
    if (now - downSince >= WIFI_RETRY_AFTER_MS) {
      WiFi.disconnect();
      WiFi.begin(settings.wifiSsid, settings.wifiPass);
      downSince = now;
    }
    return;
  }
  downSince = 0;
}

// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println(F("\nMarantzKnob — CrowPanel"));

  settingsLoad();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  pcfBegin();
  knobBegin();
  brainBegin();
  artworkBegin();
  shelfBegin();

  // uiBegin() zet het paneel zelf aan — voeding, resets, ST7701 en de
  // aanraakchip zitten in board.cpp. De seriële weergave doet daar niets van,
  // en juist daarom staat het niet hier.
  uiBegin();

  boardBacklight(settings.brightness);
  screenWake();

  connectWifi();

  // Zonder deze webinterface is er in setup-modus geen enkele manier om je
  // wifi-gegevens in te voeren: het paneel heeft geen toetsenbord en de knop
  // kan geen tekst. Overgenomen uit versie 1, ongewijzigd.
  webBegin();
}

void loop() {
  maintainWifi();
  webLoop();
  avrLoop();
  brainLoop();

  if (pendingCmd[0] && millis() >= pendingAt) {
    avrSend(pendingCmd);
    pendingCmd[0] = '\0';
  }

  handleKnob();
  // De kast haalt zijn hoezen op zodra je even stilhoudt; hij
  // meldt zelf wanneer er iets te tekenen valt.
  if (ui.screen == Screen::Browse &&
      shelfLoop(settings.brainHost, BRAIN_PORT)) refreshUi();
  uiTick();
  handleTouch();
  screenDimLoop();

  // Terugvallen naar het volumescherm als je niets meer doet
  if (ui.screen == Screen::Inputs && idleReturnAt && millis() > idleReturnAt) {
    idleReturnAt = 0;
    leaveToVolume();
  }

  if (avrState.revision != lastRevision) {
    lastRevision = avrState.revision;
    followAmplifier();                  // vóór refreshUi: die leest ui.screen
    refreshUi();
  }
  static uint32_t lastBrain = 0;
  if (brainState.revision != lastBrain) {
    lastBrain = brainState.revision;
    // De hoes hoort bij deze plaat; ophalen zodra er een andere komt. Dat duurt
    // een paar honderd milliseconden, dus precies één keer per plaat.
    if (brainState.haveArtwork) artworkLoad(settings.brainHost, BRAIN_PORT);
    else                     artworkClear();
    refreshUi();
  }

  // Opnieuw proberen als er wel een hoes klaarstaat maar hier niets ligt. Het
  // ophalen hing eerst uitsluitend aan het moment van wijzigen, en ging dat ene
  // moment mis, dan bleef het scherm leeg zolang dezelfde plaat draaide — er
  // verandert dan immers niets meer om op te reageren.
  static uint32_t artworkRetryAt = 0;
  if (brainState.haveArtwork && !artworkImage() && millis() > artworkRetryAt) {
    artworkRetryAt = millis() + 10000;
    if (artworkLoad(settings.brainHost, BRAIN_PORT)) refreshUi();
  }

  // Naald neergezet: de ingang gaat naar je favoriet. Dat is het moment om de
  // Pi te laten luisteren, in plaats van te wachten tot hij het zelf merkt.
  static char previousInput[16] = "";
  if (strcmp(avrState.input, previousInput) != 0) {
    const bool naarFavoriet =
        settings.favouriteInput >= 0 && settings.favouriteInput < settings.inputCount &&
        strcmp(avrState.input, settings.inputs[settings.favouriteInput].code) == 0;
    strlcpy(previousInput, avrState.input, sizeof(previousInput));
    if (naarFavoriet && previousInput[0]) brainAskLookup();

    // Bij het wisselen van ingang wisselt ook de bron. De hoes van de vorige
    // bron meteen weg, want de nieuwe komt pas bij de volgende melding.
    artworkClear();
    refreshUi();
  }
  if (ui.turning && millis() >= turningUntil) refreshUi();
  // Om dezelfde reden als hierboven: het scherm wordt alleen opnieuw getekend
  // als er iets wijzigt, en een tijd die afloopt is zo'n wijziging. Zonder deze
  // regel bleef de grote letter staan tot je weer aan de knop kwam.
  if (ui.shelfLetter && millis() >= letterUntil) refreshUi();
  if (ui.justLinked && millis() >= linkedUntil) refreshUi();
  static bool ownListenOn = false;
  const bool eigenNu = millis() < ownListenUntil;
  if (eigenNu != ownListenOn) { ownListenOn = eigenNu; refreshUi(); }

  static uint32_t lastDraw = 0;
  if (uiDirty && millis() - lastDraw > 40) {
    uiRender(ui);
    uiDirty = false;
    lastDraw = millis();
  }

  if (rebootRequested) {
    delay(300);
    ESP.restart();
  }
}
