# MarantzKnob

A physical volume knob for a Denon or Marantz receiver that also tells you which
record is playing.

Turn it and the volume follows. Put a record on and the sleeve appears on the
screen — heard by a microphone, matched against your own Discogs collection.
Wasn't recognised? Browse your shelf on the knob itself and point at the album.
It links the two and remembers, so next time it knows without asking anyone.

<img src="3D%20Print/AVR_Knob_preview.svg" alt="" width="360">

## What it does

| Gesture | Effect |
|---|---|
| Turn | volume; turning faster takes bigger steps |
| Hold + turn | step through inputs |
| Short press | mute |
| Double press | jump to your favourite input |
| Hold 1 s | amplifier on or off |
| Tap the sleeve | browse your record shelf |
| Tap the note | listen now |

While a record plays the sleeve fills the screen, with the volume as an arc
around the rim in the sleeve's own dominant colour. The screen goes dark when
the amplifier does and comes back when it returns.

There is a web interface at the Pi's address — one page, five tabs: what's
playing (a live copy of the panel's screen), the queue of unrecognised records,
your collection, the panel's settings, and the system.

## Two versions

**`luxe/` is the one described above**, and the one that gets the work: a round
480×480 touchscreen with a rotary ring, plus a Raspberry Pi that listens.

**`src/` is version 1**: a bare ESP32 with a rotary encoder. No screen, no
recognition — volume, inputs, mute. It still works and is a fine afternoon
project if the knob is all you want. See [docs/version-1.md](docs/version-1.md).

## What you need

Around €150. The full list with the reasoning behind each part is in
[luxe/BOM.md](luxe/BOM.md).

| Part | What to look for |
|---|---|
| **Elecrow CrowPanel 2.1" ESP32 Rotary Display** | ESP32-S3, 8 MB PSRAM, round 480×480 IPS, capacitive touch, built-in encoder |
| **Raspberry Pi 5** | 1 GB is enough; it listens, recognises and holds your collection |
| microSD card | 32 GB, A1, high-endurance |
| Power supply | the official 27 W USB-C one for a Pi 5, not a generic charger |
| A USB microphone | see the warning below |
| USB-A to JST MX1.25, 4-pin | Pi to panel. **The CrowPanel has no USB-C** — power and data share this connector. Usually in the box |

And a **Denon or Marantz receiver with network control**. Any model speaking the
telnet protocol on port 23 should do; in the receiver's menu set *Network →
Network Control* to **Always On**, or the port disappears in standby.

> **The microphone is the weak spot.** A cheap USB lavalier works with the
> volume up but struggles at conversational levels from across the room. If you
> want reliable recognition from the sofa, budget for a decent capsule — an
> EM272 on a CM108 dongle is the usual answer — rather than the €8 one.

## Getting it running

1. **Print the enclosure** — `3D Print/`. It is not finished; see
   [Known rough edges](#known-rough-edges).
2. **Flash the panel** — see [luxe/crowpanel/README.md](luxe/crowpanel/README.md).
   Needs PlatformIO. It boots into its own access point called
   `MarantzKnob-setup`; connect to it, fill in your network and your receiver's
   address, save.
3. **Set up the Pi** — `luxe/pi/installeer.sh` does the lot: packages,
   virtualenv, both services, the microphone. It prints the address to open when
   it is done.
4. **Add your collection** — open the web interface, Collection tab, enter your
   Discogs username and a personal access token (Discogs → Settings →
   Developers), press Sync. After that it re-syncs itself daily.

Step by step, with photos: [luxe/OPBOUW.md](luxe/OPBOUW.md).

## How it fits together

Three parts, each doing what it is good at:

```
   ┌─────────────┐   telnet :23   ┌──────────────┐
   │  CrowPanel  │───────────────▶│   receiver   │
   │  ESP32-S3   │                └──────────────┘
   └──────┬──────┘
          │ HTTP :8791    ┌───────────────┐
          ├──────────────▶│ ears          │  microphone, Apple TV,
          │               │ luister.py    │  web interface
   USB    │               └───────┬───────┘
   power  │                       │ HTTP :8790
          │               ┌───────▼───────┐
   ┌──────┴──────┐        │ brain         │  recognition, Discogs,
   │ Raspberry Pi│        │ server.py     │  fingerprints, database
   └─────────────┘        └───────────────┘
```

The receiver accepts exactly **one** telnet session, and the panel owns it. So
the Pi never talks to the amplifier directly — it asks the panel. The panel in
turn never does recognition — it asks the Pi. Neither guesses about the other's
job.

Your browser only ever sees one address: `/api/*` is passed through to the brain
and `/paneel/*` to the panel, so three services look like one page.

The design decisions, and why they went the way they did, are in
[luxe/PLAN.md](luxe/PLAN.md).

## Recognition, honestly

Records are identified three ways, cheapest first:

1. **Your own fingerprint database.** Costs nothing, needs no network, and grows
   every time you play something. This is the one that matters.
2. **Shazam**, via [shazamio](https://github.com/shazamio/ShazamIO).
3. **AudD**, if you supply a key. Optional and paid.

> **Read this before you run it.** `shazamio` is an unofficial client. A handful
> of lookups an evening is one thing; a hundred installations doing it
> constantly is another, and nobody agreed to provide that service. The listener
> is deliberately frugal — it only listens when sound follows silence on the
> turntable input, gives up after three failed attempts, and stays quiet while
> the amplifier is off — but if you intend to run this at any scale, use AudD
> with your own key, or lean on the local database and link the rest by hand.

Linking by hand is not a chore here. It happens on the knob, while the record is
still spinning, and every link teaches the local database one more side.

## Known rough edges

- **The enclosure is not finished.** Nine STL revisions, no lid yet, and the
  microphone channel still needs to become a proper pocket. Treat `3D Print/` as
  work in progress.
- **The web interface has no password** and listens on your whole network. That
  is a deliberate trade-off for a device on your own LAN — there is nothing in
  it more sensitive than your record collection — but do not forward it through
  your router.
- **Tested against one receiver**, an SR7015. The protocol is shared across the
  Denon and Marantz range, and the code reads the volume ceiling from the device
  instead of hardcoding it, but nobody has confirmed another model yet. If you
  try one, please say so.
- **Browsing the shelf shows albums; it cannot play them.** This is a knob for a
  turntable. Picking an album puts its sleeve on the screen, and then you get up.

## Repository layout

| | |
|---|---|
| `luxe/crowpanel/` | ESP32 firmware — display, encoder, telnet to the receiver |
| `luxe/pi/` | the ears: microphone, Apple TV, web interface, installer |
| `luxe/brein/` | the brain: recognition, Discogs, fingerprints, database |
| `luxe/recognizer/` | standalone fingerprinting prototype, with its own notes |
| `luxe/mockup/` | the interface sketch the design came from |
| `src/` | version 1 firmware |
| `3D Print/` | enclosure |
| `tools/` | `avr.sh` — poke the receiver's telnet port by hand |

## Licence

MIT — see [LICENSE](LICENSE). Do what you like with it; if you build one, I'd
enjoy hearing about it.
