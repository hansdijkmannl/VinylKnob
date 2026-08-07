// ---------------------------------------------------------------------------
// VinylKnob — firmware for the Elecrow CrowPanel 2.1" Rotary Display.
//
// Telnet to the receiver, volume on the knob, inputs and the record shelf on
// the screen. The Pi alongside adds recognition and artwork.
//
// Controls:
//   turn                    volume; in a list, the position
//   hold + turn             step through inputs; in the shelf, jump by letter
//   short press             mute, or confirm in a list; on a screen with
//                           nothing to mute, the settings
//   double press            straight to your favourite input
//   hold (1 s)              back, one level; on the volume screen, where there
//                           is nowhere to go back to, the amplifier on/off
//   hold (8 s)              clear Wi-Fi, boot into setup mode
//   tap the input name      input list — and at the bottom of it, the settings:
//                           a QR to the web interface, the addresses, the
//                           brightness
//   tap the sleeve          the record shelf; on the Apple TV input, its apps
// ---------------------------------------------------------------------------

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>

#include "brain.h"
#include "config.h"
#include "board.h"
#include "artwork.h"
#include "shelf.h"
#include "apps.h"
#include "knob.h"
#include "marantz.h"
#include "pcf.h"
#include "settings.h"
#include "ui.h"
#include "web.h"

bool netApMode = false;                // web.cpp reads this
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

// How long "linked" stays on screen after you hang an album on an unknown
// record.
static const uint32_t LINKED_MS = 3000;
static uint32_t linkedUntil = 0;

// You pointed at an album yourself. It stands until the brain reports
// something different — put a record on shortly after and that wins. This is
// deliberate: what actually sounds is truth, what you pointed at was a choice.
static bool     userPicked = false;
static uint32_t pickedAtRevision = 0;
static char     pickedArtist[48] = "";
static char     pickedTitle[48]   = "";

// -- screen brightness ------------------------------------------------------
// Next to the sofa, full brightness is a nuisance in the evening. Any touch or
// click brings it straight back; dimming happens on its own after a while.
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
  static int16_t appliedAngle = INT16_MIN;
  if (appliedAngle != settings.screenAngle) {
    appliedAngle = settings.screenAngle;
    uiSetAngle(settings.screenAngle);
    uiDirty = true;
  }
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

// Three entries at the bottom of the input list that are not inputs but
// actions. They belong there because that is when you want them: the record is
// over, you turn one step further and switch the whole thing off — or you go
// looking for the address, which is the other thing you only ever want while
// standing in front of it.
static const char *EXTRA[] = { "Turn Off", "Turn Off + Amp", "Settings" };
static const int   EXTRA_N = 3;

static int pickCount() { return settings.inputCount + EXTRA_N; }

// Is the receiver on your favourite input — the turntable? That decides whether
// the Pi may listen in; on the Apple TV there is nothing to recognise because it
// knows itself. *What* gets shown is the Pi's decision, not this one.
static bool onTurntable() {
  return settings.favouriteInput >= 0 &&
         settings.favouriteInput < settings.inputCount &&
         strcmp(avrState.input, settings.inputs[settings.favouriteInput].code) == 0;
}

// Is the receiver on the input the Apple TV hangs off? That decides three
// things: whether tapping the screen opens the launcher or the record shelf,
// whether choosing that input should also wake the Apple TV, and whether
// switching everything off should put it back to sleep.
static bool onAppleTv() {
  return settings.appleTvInput >= 0 &&
         settings.appleTvInput < settings.inputCount &&
         strcmp(avrState.input, settings.inputs[settings.appleTvInput].code) == 0;
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

static void refreshUi();          // defined further down; declared here
static void pickAlbum();
static void forgetTheQuestion();
static void enterSettings(uint8_t page);
static void leaveToVolume();
static void goBack();
static void enterAppleTv();

// For web.cpp: the order is that of enum class Screen in ui.h.
const char *uiScreenName() {
  static const char *NAMES[] = {"volume", "inputs", "browse", "pairing",
                                "settings", "appletv", "off", "setup", "noavr"};
  const uint8_t i = (uint8_t)ui.screen;
  return i < (sizeof(NAMES) / sizeof(NAMES[0])) ? NAMES[i] : "?";
}

// Everything off: screen black, and the amplifier with it if asked. The Pi
// keeps running — it powers this panel over USB, so shutting it down would mean
// only a plug could bring it back.
static void powerDown(bool alsoAmplifier) {
  // With the amplifier goes the Apple TV. Leaving it awake all night is the
  // thing you forget, and it is the one device here that cannot be seen to be
  // on — no light, no fan, nothing but a bill.
  if (alsoAmplifier) {
    avrSend("ZMOFF");
    if (settings.appleTvInput >= 0) atvPower(false);
  }
  ui.screen = Screen::Off;
  boardBacklight(0);
  // Switching off ends the evening, so it ends the record with it. Come back to
  // this screen tomorrow and it is a volume knob again — not the sleeve of
  // whatever you finished with, which looks like something is playing. What you
  // pointed at by hand goes too: that was a statement about a record that is no
  // longer on. If the amplifier was left running the Pi says so within a few
  // seconds and it all comes straight back, which is what should happen.
  artworkClear();
  userPicked = false;
  forgetTheQuestion();
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
  // Show whatever the Pi reports, whatever the source. It listens in on the
  // receiver's own phono stream for the turntable and asks the Apple TV for
  // everything else; if neither is playing, nothing comes — exactly the
  // behaviour we want, without this panel needing to know anything about it.
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
  ui.shelfNarrowed = shelfNarrowed();
  ui.choiceCount   = userPicked ? 0 : brainState.choiceCount;
  ui.justLinked    = millis() < linkedUntil;
  ui.haveArtwork   = brainState.haveArtwork;
  ui.artworkIsLogo = brainState.artworkIsLogo;
  strlcpy(ui.sourceApp, brainState.app, sizeof(ui.sourceApp));
  ui.pairing     = brainState.linkable;
  ui.piHot       = brainState.hot;
  ui.listening   = brainState.listening || millis() < ownListenUntil;
  ui.rssi = netApMode ? 0 : WiFi.RSSI();
  ui.brightness = settings.brightness;
  ui.brainUp    = brainState.reachable;
  strlcpy(ui.brainHost, settings.brainHost, sizeof(ui.brainHost));
  strlcpy(ui.wifiSsid,  settings.wifiSsid,  sizeof(ui.wifiSsid));
  ui.atvOn = onAppleTv();
  strlcpy(ui.ip, netApMode ? WiFi.softAPIP().toString().c_str()
                           : WiFi.localIP().toString().c_str(), sizeof(ui.ip));

  // The settings screen is exempt from all of this on purpose: no Wi-Fi and no
  // receiver are precisely the two moments you go looking for an address, and
  // being thrown back to a screen that says "no receiver" while you are reading
  // that receiver's address would be its own small joke.
  if (ui.screen == Screen::Off)       { /* stays off until you touch it */ }
  else if (ui.screen == Screen::Settings) { /* stays until you leave it */ }
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

// Up one level, whatever "up" happens to mean here.
//
// Deliberately not a stack. There are seven screens and you reach almost all of
// them from the volume, so a history would be a data structure recording a fact
// already known. The one place with a level inside it is the brightness, where
// back gives the knob its ordinary meaning again rather than leaving the screen
// — you would otherwise have to press twice to undo one press.
static void goBack() {
  // On the Apple TV, back belongs to the Apple TV: you are looking at its menu,
  // not at this. Only from the launcher — the one screen here that is genuinely
  // ours — does it leave.
  if (ui.screen == Screen::AppleTV) {
    if (ui.atvRemote) atvKey("menu");
    else              leaveToVolume();
    return;
  }
  if (ui.screen == Screen::Settings && ui.settingsAdjust) {
    ui.settingsAdjust = false;
    settingsSave();
    idleReturnAt = millis() + IDLE_RETURN_MS * 5;
    refreshUi();
    return;
  }
  leaveToVolume();
}

// Into the Apple TV's apps.
//
// The launcher is the one thing this does better than the remote already on the
// sofa: one turn and one press and you are in the app, rather than walking a
// grid with a direction pad. Everything after that you do while looking at the
// television, so the panel stops drawing and starts sending.
static void enterAppleTv() {
  if (settings.brainHost[0] == '\0') return;      // no Pi, no Apple TV
  ui.screen    = Screen::AppleTV;
  ui.atvRemote = false;
  // Waking is free when it is already awake, and the list cannot be fetched
  // from a device that is asleep — so this order, and not the other one.
  atvPower(true);
  if (!appsLoaded()) appsLoad(settings.brainHost, BRAIN_PORT);
  idleReturnAt = millis() + IDLE_RETURN_MS * 5;
  refreshUi();
}

// Where to reach it, what it is talking to, and how bright it is.
//
// Reached from the bottom of the input list, and by itself the moment Wi-Fi
// comes up — because the address is what you need at exactly the moment you
// cannot look it up. Generous timeout: reading a QR code with a phone takes
// longer than glancing at a volume.
static void enterSettings(uint8_t page) {
  ui.screen = Screen::Settings;
  ui.settingsPage = page < SETTINGS_PAGES ? page : 0;
  ui.settingsAdjust = false;
  idleReturnAt = millis() + IDLE_RETURN_MS * 5;
  refreshUi();
}

static void turnSettings(int steps) {
  idleReturnAt = millis() + IDLE_RETURN_MS * 5;
  if (ui.settingsAdjust) {
    // The knob belongs to the brightness now. Ten per cent a click, and never
    // all the way to nought: a screen you cannot see is a screen you cannot
    // use to turn it back up.
    int level = (int)settings.brightness + steps * 10;
    if (level < 10)  level = 10;
    if (level > 100) level = 100;
    settings.brightness = (uint8_t)level;
    boardBacklight(settings.brightness);
    refreshUi();
    return;
  }
  const int n = SETTINGS_PAGES;
  ui.settingsPage = (uint8_t)((((int)ui.settingsPage + steps) % n + n) % n);
  refreshUi();
}

static void pressSettings() {
  if (ui.settingsPage == SETTINGS_BRIGHT && !ui.settingsAdjust) {
    ui.settingsAdjust = true;               // the knob changes it from here
    idleReturnAt = millis() + IDLE_RETURN_MS * 5;
    refreshUi();
    return;
  }
  if (ui.settingsAdjust) {
    ui.settingsAdjust = false;
    settingsSave();                          // brightness is worth keeping
    idleReturnAt = millis() + IDLE_RETURN_MS * 5;
    refreshUi();
    return;
  }
  leaveToVolume();
}

static void leaveToVolume() {
  // Widen the shelf again on the way out, or the next tap on the sleeve gives
  // you the same three records with no idea why.
  shelfNarrow(nullptr, 0);
  ui.screen = Screen::Volume;
  refreshUi();
}

// Into the shelf. The list is fetched the first time and kept: hundreds of
// names are 25 kB and only change when you buy something.
static void enterBrowse() {
  if (settings.brainHost[0] == '\0') return;      // no Pi, no shelf
  if (!shelfLoaded()) shelfLoad(settings.brainHost, BRAIN_PORT);

  // A track that is on more than one of your records narrows the shelf to those
  // few. The Pi worked out which they are from the tracklists; it will not
  // choose between them and neither will this, so you point at the one that is
  // spinning. Everything else about browsing stays the same — same three
  // sleeves, same knob, shorter list.
  if (brainState.choiceCount > 1) {
    shelfNarrow(brainState.choices, brainState.choiceCount);
  } else {
    shelfNarrow(nullptr, 0);
    // Start at the record playing now, if it is on the shelf. Otherwise you
    // land at the A every time while you were just listening to something —
    // and that is precisely the album you want to see the neighbours of.
    if (shelfLoaded() && brainState.onShelf && brainState.album[0]) {
      for (int i = 0; i < shelfCount(); i++) {
        if (strcmp(shelfTitle(i), brainState.album) == 0) { shelfSet(i); break; }
      }
    }
  }
  ui.screen = Screen::Browse;
  letterUntil = 0;
  idleReturnAt = millis() + IDLE_RETURN_MS * 3;
  refreshUi();
}

// Pointing at an app: start it, and hand the knob to the television.
static void pickApp() {
  const int i = appsIndex();
  if (!appsLoaded() || i < 0) { leaveToVolume(); return; }
  atvLaunch(appsId(i));
  // From here we are blind — nothing reports back what is focused over there —
  // so the panel stops showing a list it can no longer keep in step with.
  ui.atvRemote = true;
  idleReturnAt = millis() + IDLE_RETURN_MS * 5;
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
// Gestures
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
  turningUntil = now + 1600;                  // show the dB figure for a moment
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
    const int extra = pickIndex - settings.inputCount;
    if (extra == 2) enterSettings(SETTINGS_WEB);
    else            powerDown(extra == 1);      // second entry = with the amp
    return;
  }
  if (pickIndex >= 0 && pickIndex < settings.inputCount)
    sendInput(settings.inputs[pickIndex].code);

  // Choosing the Apple TV wakes it as well. Two things you always did together
  // — the receiver's input here, the remote in your other hand there — and no
  // reason for them to stay two. The launcher follows, because after switching
  // to it the next thing you want is an app.
  if (pickIndex == settings.appleTvInput && settings.appleTvInput >= 0) {
    enterAppleTv();
    return;
  }
  leaveToVolume();
}

static void handleKnob() {
  const KnobInput in = knobPoll();

  if (in.steps != 0 || in.event != KnobEvent::None) screenWake();

  if (in.steps != 0) {
    if (ui.screen == Screen::Settings) {
      turnSettings(in.steps);
    } else if (ui.screen == Screen::AppleTV) {
      // In the launcher the list is ours, so it moves here and instantly. In an
      // app it is not ours to move, so each click goes over as a key press —
      // about twenty milliseconds, which is why this needs no smoothing.
      if (ui.atvRemote) {
        for (int i = 0; i < abs(in.steps); i++) atvKey(in.steps > 0 ? "right" : "left");
      } else {
        appsMove(in.steps);
      }
      idleReturnAt = millis() + IDLE_RETURN_MS * 5;
    } else if (ui.screen == Screen::Browse) {
      // On the shelf the knob does something else. Turning while held jumps by
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
        letterUntil = 0;               // plain browsing: the letter can go
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
      if (ui.screen == Screen::Inputs) {          // confirm
        confirmInput();
      } else if (ui.screen == Screen::Settings) {
        pressSettings();
      } else if (ui.screen == Screen::AppleTV) {
        // Select in the launcher, select in an app, and pause once something is
        // playing — three names for one gesture, and never two at once, because
        // the screen you are looking at settles which it is.
        if (!ui.atvRemote)          pickApp();
        else if (brainState.playing) atvKey("playpause");
        else                         atvKey("select");
      } else if (ui.screen == Screen::Browse) {
        pickAlbum();
      } else if (onAppleTv() && brainState.playing) {
        // Watching, not listening: a press should stop the picture too, and
        // muting a film is not what anyone means by it.
        atvKey("playpause");
      } else if (ui.screen == Screen::Setup || ui.screen == Screen::NoAvr) {
        // Nothing to mute and no list to open, so the press is free — and this
        // is where the address is, which is what you are standing there for.
        enterSettings(SETTINGS_WEB);
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
      // One way back, the same one everywhere. CarPlay makes this a rule for
      // exactly this hardware — a knob, a small screen, and someone who is only
      // half looking at it — and until now every screen had its own answer: a
      // BACK button in the shelf, a CLOSE page in the settings, a press
      // elsewhere, a tap on the glass somewhere else again.
      //
      // On the home screen there is nowhere to go back to, so there the gesture
      // keeps the job it has always had. That is not a second meaning smuggled
      // in: it is the one screen where the first meaning has nothing to do.
      if (ui.screen == Screen::Volume || ui.screen == Screen::Off ||
          ui.screen == Screen::Setup  || ui.screen == Screen::NoAvr)
        avrSend(avrState.powered ? "ZMOFF" : "ZMON");
      else
        goBack();
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
      // The same gesture on the same spot, pointed at whatever the receiver is
      // playing. A record gives you the shelf; the Apple TV gives you its apps.
      if (onAppleTv()) enterAppleTv();
      else             enterBrowse();
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
// Network
// ---------------------------------------------------------------------------
//
// Falling back to the access point must not be a one-way door.
//
// It was. Twenty-five seconds at boot, and if the network was not there in that
// time the panel put up its own access point and stayed there — asking you to
// set up Wi-Fi it already knew, with a reboot as the only way out. Half an hour
// off the mains was enough to trigger it: a router coming back from a power cut
// takes minutes to hand out addresses again, and this is up in three seconds.
//
// So with credentials stored it runs both at once. The access point is how you
// fix a wrong password; the station is how it gets itself back without you.
static void startAccessPoint() {
  const bool haveCredentials = settings.wifiSsid[0] != '\0';
  netApMode = true;
  WiFi.mode(haveCredentials ? WIFI_AP_STA : WIFI_AP);
  WiFi.softAP(AP_SSID);
  if (haveCredentials) {
    WiFi.setHostname(MDNS_NAME);
    WiFi.begin(settings.wifiSsid, settings.wifiPass);
    Serial.printf("Setup access point \"%s\" at %s, still trying \"%s\"\n",
                  AP_SSID, WiFi.softAPIP().toString().c_str(), settings.wifiSsid);
  } else {
    Serial.printf("Setup access point \"%s\" at %s\n", AP_SSID,
                  WiFi.softAPIP().toString().c_str());
  }
  refreshUi();
}

static void connectWifi() {
  if (strlen(settings.wifiSsid) == 0) {
    startAccessPoint();
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                 // or the knob feels noticeably sluggish
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
  Serial.printf("Wi-Fi connected, IP %s\n", WiFi.localIP().toString().c_str());
  refreshUi();
}

static void maintainWifi() {
  static uint32_t downSince = 0;
  static uint32_t apRetryAt = 0;

  if (netApMode) {
    if (settings.wifiSsid[0] == '\0') return;     // nothing to go back to
    if (WiFi.status() == WL_CONNECTED) {
      // The network came back. Drop the access point and carry on as though
      // this had worked at boot — including showing where to reach it, which
      // is the one thing you want to know the moment it comes online.
      netApMode = false;
      WiFi.softAPdisconnect(true);
      WiFi.mode(WIFI_STA);
      WiFi.setSleep(false);
      Serial.printf("Wi-Fi is back, IP %s\n", WiFi.localIP().toString().c_str());
      // Show where to reach it, which is the one thing you want the moment it
      // comes online and cannot look up anywhere else. Unless it is switched
      // off — coming back from a network outage is no reason to light the room.
      if (ui.screen == Screen::Off) refreshUi();
      else                          enterSettings(SETTINGS_WEB);
      return;
    }
    if (millis() >= apRetryAt) {
      apRetryAt = millis() + WIFI_RETRY_AFTER_MS;
      // Credentials usually arrive *after* the access point is up — that is the
      // whole point of it — and a radio in plain AP mode cannot go looking for
      // a network. Put it in both modes before asking.
      if (WiFi.getMode() != WIFI_AP_STA) {
        WiFi.mode(WIFI_AP_STA);
        WiFi.setHostname(MDNS_NAME);
      }
      WiFi.begin(settings.wifiSsid, settings.wifiPass);
    }
    return;
  }

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
  Serial.println(F("\nVinylKnob — CrowPanel"));

  settingsLoad();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  pcfBegin();
  knobBegin();
  brainBegin();
  artworkBegin();
  shelfBegin();
  appsBegin();

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

// The song is on more than one of your records: show that, without being asked.
//
// A question you have to go looking for is a question that never gets answered.
// The first version put a line on the volume screen and left the shelf a tap
// away, and the tap is exactly the step nobody takes — you glance at the screen,
// see a name, and carry on. So the shelf opens on those two or three sleeves by
// itself. One turn and one press, and the record has learnt this side.
//
// Only from the volume screen: it may not take the display away from you while
// you are choosing an input or setting up Wi-Fi, and it may not light up a dark
// room. Only once per question, remembered by which records were offered — else
// it would reopen every four seconds for the rest of the side, including after
// you had deliberately walked away from it. enterBrowse() gives the screen a
// timeout of its own, so an unanswered question fades back to the volume rather
// than sitting there all evening.
static uint16_t askedChoices[SHELF_FILTER_MAX];
static uint8_t  askedCount = 0;

// Forget that a question was ever asked, so the same one may be asked again.
static void forgetTheQuestion() { askedCount = 0; }

static void askIfNeeded() {
  if (brainState.choiceCount < 2) {
    // The question has been withdrawn — answered, or the side is over. Forget
    // it, so putting the same record on tomorrow asks again.
    askedCount = 0;
    return;
  }
  if (ui.screen != Screen::Volume) return;
  if (brainState.choiceCount == askedCount &&
      memcmp(askedChoices, brainState.choices,
             (size_t)askedCount * sizeof(uint16_t)) == 0) return;

  askedCount = brainState.choiceCount;
  memcpy(askedChoices, brainState.choices, (size_t)askedCount * sizeof(uint16_t));
  enterBrowse();
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
  if (ui.screen == Screen::AppleTV && !ui.atvRemote) {
    // The list may not have arrived yet — the Apple TV was asleep when we asked
    // and cannot answer then. Keep asking while you are looking at it.
    static uint32_t retryAt = 0;
    if (!appsLoaded() && millis() > retryAt) {
      retryAt = millis() + 2000;
      if (appsLoad(settings.brainHost, BRAIN_PORT)) refreshUi();
    }
    if (appsLoop(settings.brainHost, BRAIN_PORT)) refreshUi();
  }
  uiTick();
  handleTouch();
  screenDimLoop();

  // Fall back to the volume screen when you stop doing anything
  if ((ui.screen == Screen::Inputs || ui.screen == Screen::Settings ||
       ui.screen == Screen::AppleTV) &&
      idleReturnAt && millis() > idleReturnAt) {
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

  askIfNeeded();

  // Something started: the panel stops being a remote and goes back to being a
  // volume knob, on the screen that already shows what is playing. That is the
  // whole reason this is not a second remote control — it gets out of the way
  // the moment there is nothing left to choose.
  if (ui.screen == Screen::AppleTV && brainState.playing) leaveToVolume();

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
