# Parts list

A round touchscreen with a rotary ring for a Denon or Marantz receiver: a
ready-made CrowPanel for the controls, with a Raspberry Pi beside it as the
brain. The reasoning behind that split is in [PLAN.md](PLAN.md).

Prices are indicative (2026, EU). The CrowPanel comes from Elecrow directly, or
via Amazon or Tindie; the rest from any of the usual suppliers.

> **Before you order.** Whether the recognition half works at all depends on your
> receiver serving its analog inputs over HTTP, and there is no list of which
> models do. It is one command with the receiver switched on and costs nothing —
> [step −1 of the build guide](BUILD.md). Everything else on this list works
> either way.

## What to buy

| # | Qty | Part | What to look for | ~Price |
|---|---|---|---|---|
| 1 | 1 | **Elecrow CrowPanel 2.1" ESP32 Rotary Display** | ESP32-S3R8, 8 MB PSRAM, 16 MB flash, round 480×480 IPS, capacitive touch, built-in encoder. Aluminium and acrylic, 79×79×30 mm | €53 |
| 2 | 1 | **Raspberry Pi 5**, 1 GB | see [Which Pi](#which-pi) | €50 |
| 3 | 1 | microSD card | 32 GB, **A1** — not A2, see [The SD card](#the-sd-card) | €25 |
| 4 | 1 | Power supply | the **official 27 W USB-C PD** adapter, not a generic one — see [Power](#power) | €13 |
| 5 | 1 | Heatsink or cooling case for the Pi 5 | passive is enough here | €5-10 |
| 6 | ~300 g | Ballast | steel washers, M8 nuts or lead shot — see [Ballast](#ballast-and-feet) | €0-4 |
| 7 | 4 | Non-slip feet, ~12 mm | **do not skip these** | €1 |
| 8 | 4 | M3 heat-set inserts + M3×10 screws | for the base plate | €0.60 |
| 9 | — | Filament | PETG, or ASA for a matte finish | — |

**Around €140 all in**, of which the panel is a third. There is not one
mechanical precision part in it, and no microphone — see
[How it listens](#how-it-listens-no-microphone).

The enclosure is printed yourself: a plinth for the panel to stand on, with the
Pi inside. No files here yet — the shape is still changing too fast to publish.
What it has to do is below, under [Ballast and feet](#ballast-and-feet) — and how
to get power into it without losing the USB current the panel needs is under
[Power](#power), because the obvious way costs you exactly that.

> **The cable comes with the panel** and is not something to source. It is
> plain USB-A at the Pi end; at the panel end it is a 4-pin JST MX1.25 into
> `USB-5V-IN`, because the CrowPanel has no USB-C. One cable, power and data
> both.

---

## How it listens: no microphone

This build used to hang on a USB microphone, and that was the weak spot of the
whole thing: a room microphone hears the record at 10 to 20 dB above its own
noise, and it hears everything else in the room as well.

It turns out not to be necessary. Denon and Marantz receivers digitise their
analog inputs and serve each one as a plain HTTP stream — the machinery behind
sharing an input with HEOS speakers — so the Pi can read the turntable straight
off the phono stage:

```
http://<receiver>:8015/analoginput/analog/analog/0/phono
```

Raw 16-bit stereo PCM at 44.1 kHz, realtime, one client at a time. Measured on
an SR7015, both in the same minute with the same record:

| | line feed | microphone in the room |
|---|---|---|
| signal | −36.7 dBFS | −42.0 dBFS |
| its own noise floor | −80 dBFS | −54.7 dBFS |
| **room above the floor** | **43 dB** | **13 dB** |

The fingerprinter in `../recognizer/` is validated faultless down to 20 dB. The
microphone sat below that; the line feed sits far above it. And it hears no
conversation, no doors and no traffic.

`../pi/line.sh` asks your receiver which inputs it offers and measures each one,
so you can see which carries the turntable. Two things to know:

- **Only the analog inputs are digitised.** Anything arriving over HDMI stays
  silent on these streams — but a turntable is analog by definition, which is
  the case that matters here.
- **One client at a time**, like the telnet port. The ears own it.

This is an undocumented manufacturer endpoint, so it could disappear in a
firmware update. If your receiver does not offer it, the knob, the screen and
the shelf all work exactly as before; only recognition needs it.

## Power

The panel runs off the Pi, which is tidier than two separate adapters — but it
depends on which supply you choose.

A Pi 5 limits its USB ports to **600 mA in total** by default. The CrowPanel is
specified at 5 V and 1 A, and measured asks for 500 mA (see below) — either way
that is the whole budget for one device. The limit rises automatically
to **1.6 A** once the Pi has negotiated 5 V at 5 A over USB-PD — in practice,
Raspberry Pi's own 27 W adapter.

So: **buy the official adapter**, not a generic 5 V/3 A charger.

```
27 W USB-C PD  --->  Pi 5  --USB-A to JST MX1.25-->  CrowPanel
```

One plug in the wall, one cable to the screen.

That cable carries **data too**. Elecrow's schematic shows `USB-5V-IN` is a real
USB connection: D− and D+ run through R43/R44 straight to `GPIO19/USB_D−` and
`GPIO20/USB_D+` on the ESP32-S3, with no CH340 or CP2102 in between. It is the
chip's own native USB, which is what makes `flash-via-pi.sh` possible.

Which the running machine confirms, so this is not read off a schematic and hoped
for. `lsusb` on the Pi:

```
Bus 003 Device 002: ID 303a:1001 Espressif USB JTAG/serial debug unit
  max 500mA · 12 Mbps
```

Espressif's own vendor id, the S3's native peripheral, no bridge chip anywhere,
and the port appears as `/dev/ttyACM0`. Note the **500 mA**: that is the panel's
own request, and the un-negotiated budget is 600 mA for every port together. It
fits, but with nothing to spare — plug anything else into the Pi and the official
adapter stops being a recommendation.

If you cannot get the official adapter, `usb_max_current_enable=1` in
`config.txt` raises the limit anyway — but then your supply really does have to
deliver 1.6 A, or it will collapse under load.

### Do not feed it 5 V through the GPIO header

It is a tempting shortcut when you are building an enclosure: one USB socket in the
back panel, `+` and `−` to pins 2 and 6, done. It costs you three things, and the
first one is measurable on the running machine.

**The current limit comes from the negotiation, not from the volts.** On the Pi
here, `usb_max_current_enable` reads 1 — and it is not in `config.txt`, so the
firmware set it after agreeing 5 V at 5 A with the official adapter. That handshake
happens on the USB-C **CC** lines. Bypass the socket and there is no handshake, so
every USB port together falls back to 600 mA, and the panel asks for 500 of them.
It fits, with a hundred milliamps left for the rest of your life.

**A USB-C socket wired with only `+` and `−` gets nothing.** A USB-C source does
not energise VBUS until it sees a valid pull-down — 5.1 kΩ to ground on CC1 and CC2
— so a PD adapter into such a socket delivers zero volts. An old USB-A charger
would work, because those put 5 V on the line unconditionally, which is a fine
description of what you would be building.

**And the header bypasses the input protection.** No polyfuse, no reverse-polarity
or over-voltage protection on that path; you are on the 5 V rail directly.

So: bring the Pi's own USB-C socket out to the back panel instead — a short
panel-mount extension that carries *all* the pins. The negotiation survives, the
protection survives, and the enclosure still gets one tidy socket. If you insist on
the header, put `usb_max_current_enable=1` in `/boot/firmware/config.txt` and use a
supply that genuinely delivers, because the Pi will then assume it may take 1.6 A
on USB on top of its own peak.

---

## One that is known to work

Written down because "it should work" and "it does work" are different claims, and
this is the second one:

| | |
|---|---|
| Raspberry Pi 5, **1 GB** | Raspberry Pi OS Lite 64-bit |
| **32 GB** microSD | A1, high-endurance |
| **Elecrow CrowPanel 2.1"** ESP32 Rotary Display | ESP32-S3R8 |
| one **USB-A to JST MX1.25** cable | the one in the panel's box, into `USB-5V-IN` |
| **Marantz SR7015** | Network Control on Always On, turntable on `PHONO` |

Nothing else: no microphone, no separate supply for the panel, no hub, no level
shifters, no soldering. If you build a different combination that works, say which
— particularly the receiver, since that is the part with no published list.

---

## Which Pi

**A Pi 5 with 1 GB** is what this was built on, and it is a good fit:

- **1 GB is double a Zero's.** After the OS and Python you have ~650 MB for the
  fingerprint index, against ~150 MB on a Zero.
- **Quad-core Cortex-A76 at 2.4 GHz** against the Zero's A53 at 1 GHz. Matching
  that would be slow on a Zero is quick here.
- **Dual-band Wi-Fi.** The panel is still 2.4 GHz only.

You pay in size (85×56 mm, wider than the panel's 79), in idle draw (~3 W
against ~0.7), and in price.

<details>
<summary>Why a Zero 2 W also works, and why not a Pi 4</summary>

A Zero 2 W is smaller, cheaper and needs no cooling. Its 512 MB
is enough: OS Lite 80-120 MB, Python with numpy 60-80 MB, sleeves in memory
20-40 MB, the index 40-75 MB, and shazamio briefly 50-100 MB while it computes.
About 350 MB together.

A Pi 4 was considered for RAM for the fingerprint index, but that argument does
not hold: only the records that Shazam *misses* end up in that database, which
is a handful to a few dozen sides, not a whole shelf. And a Pi 4's two HDMI
ports, four USB ports and ethernet jack are dead weight here.

**If the database ever does get large**, you do not need a bigger Pi. Search in
two stages: keep a **coarse index** in memory — say one hash in 32, about 40 MB
for eight hundred sides — which is too coarse to decide with but ample to
produce ten candidates. Then read the full hashes of only those candidates from
the card. That works because stage two is a contiguous read per side, which SD
cards are good at. Keeping the whole index on disk and seeking randomly through
it would be the version that falls over.
</details>

---

## The SD card

**A1, not A2.** Counter-intuitive, and a Pi peculiarity.

A1 and A2 are random-access speed classes: A1 promises 1500 read IOPS, A2
promises 4000. But **A2 achieves that with command queuing, and the Raspberry
Pi's SD controller does not support it.** An A2 card falls back to ordinary
behaviour and performs the same as — sometimes worse than — an A1 card, while
costing more. If you already own an A2, use it; it is not worse, just a waste.

What does matter:

- **Brand over class.** SanDisk, Samsung or Kingston from a reliable seller.
  Counterfeit cards are a plague and they fail exactly in devices that run
  continuously.
- **"High Endurance"** (meant for dashcams) is more useful here than fast.
- **32 GB is plenty.** Bigger helps nothing.
- **Reducing writes beats any speed class.** Logs to tmpfs, swap off. The
  installer does both.

---

## Ballast and feet

The panel weighs 80 grams. That is light for something you are going to turn:
without help it slides across the table. So the printed plinth is not a box but
a **weight** — design a cavity for ~300 g of nuts or washers, and put four
non-slip feet under it.

That also fixes the weakest point of this approach. The built-in encoder is
small and light, and a heavy base underneath makes a noticeable difference to
how the whole thing feels.
