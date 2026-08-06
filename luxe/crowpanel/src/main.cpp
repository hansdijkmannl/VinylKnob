// ---------------------------------------------------------------------------
// MarantzKnob — firmware for the Elecrow CrowPanel 2.1" Rotary Display.
//
// Telnet to the receiver, volume on the knob, inputs and the record shelf on
// the screen. The Pi alongside adds recognition and artwork.
//
// Controls:
//   turn                    volume; in a list, the position
//   hold + turn             step through inputs; in the shelf, jump by letter
//   short press             mute, or confirm in a list
//   double press            straight to your favourite input
//   hold (1 s)              amplifier on/off
//   hold (8 s)              clear Wi-Fi, boot into setup mode
//   tap the input name      input list
//   tap the sleeve          the record shelf
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
// rebootRequested is defined in web.cpp; web.h declares it extern.

static UiState ui;
static bool     uiDirty      = true;
static uint32_t lastRevision = 0;
static uint32_t idleReturnAt = 0;
static uint32_t turningUntil = 0;
static uint32_t ownListenUntil = 0;   // our own tap, until the Pi takes over

// The large letter in the shelf: how long it stays up.
static const uint32_t LETTER_MS = 900;
static uint32_t letterUntil = 0;

// How long "linked" stays on screen after you hang an album on an
// plaat hebt gehangen.
static const uint32_t LINKED_MS = 3000;
static uint32_t linkedUntil = 0;

// You pointed at an album yourself. It stands until the brain reports
// something different — put a record on shortly after and that wins. This is
// deliberate: what actually sounds is truth, what you pointed at was a choice.
static bool     userPicked = false;
static uint32_t pickedAtRevision = 0;
static char     pickedArtist[48] = "";
static char     pickedTitle[48]   = "";

// -- schermhelderheid -------------------------------------------------------
// Naast de bank is vol licht 's avonds hinderlijk. Elke aanraking of klik zet
// brings it straight back; dimming happens on its own after a while.
static uint32_t lastTouchAt = 0;
static bool     dimmed           = false;

static void screenWake() {
  lastTouchAt = millis();

  // If it was off, any touch or press is the on switch. That is the whole
  // answer to "can I turn it back on with the knob": yes, and with the side
  // effect that you land straight back on the volume.
  if (ui.screen == Screen::Off) {
    ui.screen = Screen::Volume;
    uiDirty = true;
  }
  if (dimmed) dimmed = false;
  boardBacklight(settings.brightness);
}

static void screenDimLoop() {
  if (ui.screen == Screen::Off) return;      // off is off

  // Apply the setting while you are dragging the slider. Otherwise "live"
  // would only be true on paper.
  static uint8_t appliedBrightness = 0;
  if (!dimmed && appliedBrightness != settings.brightness) {
    appliedBrightness = settings.brightness;
    boardBacklight(appliedBrightness);
  }
  // Same for flipping the orientation in the web interface.
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

// One queue slot, so an input choice after a ZMON goes out at a decent
// distance from the previous command without blocking the loop.
static char     pendingCmd[24] = "";
static uint32_t pendingAt      = 0;

// The candidate input, not yet sent.
static int      pickIndex     = 0;

// Two entries at the bottom of the input list that are not inputs but actions.
// They belong there because that is when you want them: the record is over, you
// turn one step further and switch the whole thing off.
static const char *EXTRA[] = { "Turn Off", "Turn Off + Amp" };
static const int   EXTRA_N = 2;

static int pickCount() { return settings.inputCount + EXTRA_N; }

// Is the receiver on your favourite input — the turntable? That decides whether
// the Pi may listen in; on the Apple TV there is nothing to recognise because it
// knows itself. *What* gets shown is the Pi's decision, not this one.
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

// For web.cpp: the order is that of enum class Screen in ui.h.
const char *uiScreenName() {
  static const char *NAMES[] = {"volume", "inputs", "browse",
                                "pairing", "off", "setup", "noavr"};
  const uint8_t i = (uint8_t)ui.screen;
  return i < (sizeof(NAMES) / sizeof(NAMES[0])) ? NAMES[i] : "?";
}

// Everything off: screen black, and the amplifier with it if asked. The Pi
// keeps running — it powers this panel over USB, so shutting it down would mean
// only a plug could bring it back.
static void powerDown(bool alsoAmplifier) {
  if (alsoAmplifier) avrSend("ZMOFF");
  ui.screen = Screen::Off;
  boardBacklight(0);
  refreshUi();
}

// Following the amplifier.
//
// Switch the system off with the remote, or let your Apple TV do it over HDMI,
// and this screen should not be the only thing still lit on an otherwise dark
// rack. The other way round too: when the zone comes on you want your volume
// without touching the glass first.
//
// Only with a live connection *and* an answer from the receiver. Without both,
// a dropped network would black the screen while nothing is wrong: `powered`
// then still holds its last known value, and just after connecting it sits at
// its initial false without any ZM or PW reply ever having arrived. haveVolume
// is the proof that a conversation actually happened.
//
// The first reading counts too, and that is deliberate: if the power blinks at
// night this panel restarts beside a system that is off, and it should not stay
// lit for the rest of the night.
static int8_t previousPower = -1;          // -1 = nothing seen yet

static void followAmplifier() {
  if (!avrState.connected || !avrState.haveVolume) { previousPower = -1; return; }

  const int8_t now = avrState.powered ? 1 : 0;
  if (now == previousPower) return;
  const bool first = previousPower < 0;
  previousPower = now;

  if (!settings.offWithAmp) return;
  // On that very first reading, only darken and never wake: otherwise the
  // screen lights up because the panel restarted, not because you did anything.
  if (now == 0)       powerDown(false);      // amplifier off: screen follows
  else if (!first)    screenWake();          // and back on when it returns
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
  // Show whatever the Pi reports, whatever the source. It routes the turntable
  // through the microphone and everything else through the Apple TV; if that is
  // playing nothing, nothing comes — exactly the behaviour we want, without this
  // panel needing to know anything about it.
  brainWantsToListen = onTurntable();
  // The brain reported something new, so your own choice lapses.
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

  if (ui.screen == Screen::Off)       { /* stays off until you touch it */ }
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

// Into the shelf. The list is fetched the first time and kept: hundreds of
// names are 25 kB and only change when you buy something.
static void enterBrowse() {
  if (settings.brainHost[0] == '\0') return;      // no Pi, no shelf
  if (!shelfLoaded()) shelfLoad(settings.brainHost, BRAIN_PORT);

  // Start at the record playing now, if it is on the shelf. Otherwise you land
  // at the A every time while you were just listening to something — and that
  // is precisely the album you want to see the neighbours of.
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

// Pointing at an album.
//
// Two things at once, and which one happens depends on what is playing.
//
// If something unrecognised is on, this is a link: the brain hangs your choice
// on that listen and records the saved clip as fingerprints. From then on this
// device knows that side by itself, with no service involved. That is the
// lesson only you could give, and this is the moment to give it — needle still
// down, sleeve in your hand, instead of working through a queue on your phone
// in the evening.
//
// If nothing special is playing this is only "show me": the sleeve comes back
// full-screen. Putting a record on is not something this device can do.
static void pickAlbum() {
  const int i = shelfIndex();
  if (!shelfLoaded() || i < 0) { leaveToVolume(); return; }

  const bool linkable = brainState.canLink;
  if (linkable) brainLink(shelfReleaseId(i));

  strlcpy(pickedArtist, shelfArtist(i), sizeof(pickedArtist));
  strlcpy(pickedTitle,   shelfTitle(i),   sizeof(pickedTitle));
  userPicked   = true;
  pickedAtRevision = brainState.revision;
  // On a link the confirmation stays up for a few seconds: you have just
  // recorded something permanent and want to see that it landed.
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

  if (avrState.muted) {                       // turning cancels mute
    avrSend("MUOFF");
    avrState.muted = false;
  }
  turningUntil = now + 1600;                  // dB-getal even tonen
}

static void scrollInputs(int steps) {
  const int n = pickCount();
  if (n == 0) return;
  pickIndex = ((pickIndex + steps) % n + n) % n;

  // Deliberately no auto-commit. Version 1 had one — there was no screen there,
  // so turning *was* the choice, and a 250 ms delay stopped the receiver from
  // touching every input on the way. Here there is a list to look at and a press
  // to confirm, and sending while you browse is no longer caution but a bug:
  // you could never get past the first input without landing on it.
  idleReturnAt = millis() + IDLE_RETURN_MS;
}

// What confirming in the list does: pick an input, or one of the
// twee uitzet-regels uitvoeren.
static void confirmInput() {
  if (pickIndex >= settings.inputCount) {
    powerDown(pickIndex == settings.inputCount + 1);   // second entry = with the amp
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
      // letter: with hundreds of albums, one at a time is no way to travel, and
      // this is the same jump index as the letter ring in the web interface.
      if (in.held) {
        for (int i = 0; i < abs(in.steps); i++) shelfJump(in.steps > 0 ? 1 : -1);
        // The letter you landed on, large on screen, while you jump and for a
        // moment after. Fourteen pixels along the rim is too little to read
        // mid-turn; this you do not have to hunt for.
        letterUntil = millis() + LETTER_MS;
      } else {
        shelfMove(in.steps);
        letterUntil = 0;               // gewoon bladeren: de letter mag weg
      }
      idleReturnAt = millis() + IDLE_RETURN_MS * 3;
    } else if (in.held) {
      // Holding and turning steps through the inputs. It was in the
      // documentation but not in the code — which is why you could not find it
      // on the screen.
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
      // knob.cpp already suppresses the short press if you turned while
      // holding, so only the list needs handling here.
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
      Serial.println(F("Wi-Fi credentials cleared; booting into setup mode."));
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
      // Light up on your own tap, without waiting for the Pi to confirm. That
      // comes a fraction later and takes over; if it never does, this fades by
      // itself. A button that only responds after a round trip feels broken,
      // even when nothing is wrong.
      brainAskLookup();
      ownListenUntil = millis() + 4000;
      refreshUi();
      break;
    case Touch::Dismiss:    leaveToVolume(); break;
    case Touch::Artwork:
      enterBrowse();
      break;
    case Touch::Pairing:
      // The QR code used to be behind a tap on the sleeve. Now that the shelf
      // is there, the dot has its own touch area — a generous one, because you
      // do not hit ten pixels with a finger.
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
  Serial.printf("Setup access point \"%s\" at %s\n", AP_SSID,
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
  Serial.printf("Connecting to Wi-Fi \"%s\"...\n", settings.wifiSsid);

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

  // uiBegin() brings the panel up itself — power, resets, the ST7701 and the
  // touch chip all live in board.cpp. The serial implementation does none of
  // that, which is exactly why it is not here.
  uiBegin();

  boardBacklight(settings.brightness);
  screenWake();

  connectWifi();

  // Without this web interface there is no way at all to enter Wi-Fi
  // credentials in setup mode: the panel has no keyboard and the knob cannot
  // type. Taken unchanged from version 1.
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
  // The shelf fetches its sleeves once you hold still; it says for itself when
  // there is something to draw.
  if (ui.screen == Screen::Browse &&
      shelfLoop(settings.brainHost, BRAIN_PORT)) refreshUi();
  uiTick();
  handleTouch();
  screenDimLoop();

  // Fall back to the volume screen when you stop doing anything
  if (ui.screen == Screen::Inputs && idleReturnAt && millis() > idleReturnAt) {
    idleReturnAt = 0;
    leaveToVolume();
  }

  if (avrState.revision != lastRevision) {
    lastRevision = avrState.revision;
    followAmplifier();                  // before refreshUi, which reads ui.screen
    refreshUi();
  }
  static uint32_t lastBrain = 0;
  if (brainState.revision != lastBrain) {
    lastBrain = brainState.revision;
    // The sleeve belongs to this record; fetch it when a different one comes.
    // It takes a few hundred milliseconds, so exactly once per record.
    if (brainState.haveArtwork) artworkLoad(settings.brainHost, BRAIN_PORT);
    else                     artworkClear();
    refreshUi();
  }

  // Try again when a sleeve is waiting but nothing is here. Fetching used to
  // hang solely on the moment of change, and if that one moment failed the
  // screen stayed empty for as long as the same record played — because nothing
  // changes any more to react to.
  static uint32_t artworkRetryAt = 0;
  if (brainState.haveArtwork && !artworkImage() && millis() > artworkRetryAt) {
    artworkRetryAt = millis() + 10000;
    if (artworkLoad(settings.brainHost, BRAIN_PORT)) refreshUi();
  }

  // Needle down: the input switches to your favourite. That is the moment to
  // have the Pi listen, rather than waiting for it to notice by itself.
  static char previousInput[16] = "";
  if (strcmp(avrState.input, previousInput) != 0) {
    const bool naarFavoriet =
        settings.favouriteInput >= 0 && settings.favouriteInput < settings.inputCount &&
        strcmp(avrState.input, settings.inputs[settings.favouriteInput].code) == 0;
    strlcpy(previousInput, avrState.input, sizeof(previousInput));
    if (naarFavoriet && previousInput[0]) brainAskLookup();

    // Changing input changes the source. Drop the previous source's sleeve at
    // once, because the new one only arrives with the next report.
    artworkClear();
    refreshUi();
  }
  if (ui.turning && millis() >= turningUntil) refreshUi();
  // For the same reason as above: the screen is only redrawn when something
  // changes, and a timer running out is such a change. Without this line the
  // large letter stayed up until you touched the knob again.
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
