# Parts list

A round touchscreen with a rotary ring for a Denon or Marantz receiver: a
ready-made CrowPanel for the controls, with a Raspberry Pi beside it as the
brain. The reasoning behind that split is in [PLAN.md](PLAN.md).

Prices are indicative (2026, EU). The CrowPanel comes from Elecrow directly, or
via Amazon or Tindie; the rest from any of the usual suppliers.

## What to buy

| # | Qty | Part | What to look for | ~Price |
|---|---|---|---|---|
| 1 | 1 | **Elecrow CrowPanel 2.1" ESP32 Rotary Display** | ESP32-S3R8, 8 MB PSRAM, 16 MB flash, round 480×480 IPS, capacitive touch, built-in encoder. Aluminium and acrylic, 79×79×30 mm | €53 |
| 2 | 1 | **Raspberry Pi 5**, 1 GB | see [Which Pi](#which-pi) | €50 |
| 3 | 1 | microSD card | 32 GB, **A1** — not A2, see [The SD card](#the-sd-card) | €25 |
| 4 | 1 | **USB microphone** | see [The microphone](#the-microphone) — this is the part to spend on | €8-40 |
| 5 | 1 | Power supply | the **official 27 W USB-C PD** adapter, not a generic one — see [Power](#power) | €13 |
| 6 | 1 | USB-A to JST MX1.25, 4-pin | Pi to panel. Usually supplied with the panel — check the box, it is hard to find separately | €4 |
| 7 | 1 | Heatsink or cooling case for the Pi 5 | passive is enough here | €5-10 |
| 8 | ~300 g | Ballast | steel washers, M8 nuts or lead shot — see [Ballast](#ballast-and-feet) | €0-4 |
| 9 | 4 | Non-slip feet, ~12 mm | **do not skip these** | €1 |
| 10 | 4 | M3 heat-set inserts + M3×10 screws | for the base plate | €0.60 |
| 11 | — | Filament | PETG, or ASA for a matte finish | — |

**Around €150 all in**, of which the panel is a third. There is not one
mechanical precision part in it.

The enclosure is printed yourself: a plinth for the panel to stand on, with the
Pi and the microphone inside. Files in `3D Print/`.

> **The CrowPanel has no USB-C.** Power and data both run over the `USB-5V-IN`
> connector, a 4-pin JST MX1.25 (`GND · D+ · D− · VCC`).

---

## The microphone

**This is the weak spot of the whole build, and the place to spend money.**

The €8 USB lavalier works when the volume is up, but recognising music at
conversational levels from across the room is marginal — measured at around
−45 dB from a sofa, right at the threshold. If you want it to work without
thinking about it, get a proper capsule: an **EM272** on a **CM108 dongle** is
the usual answer among people who record ambient sound.

What matters is not the price but the chip. Look for **C-Media CM108, CM108B or
CM119**. Those have no automatic gain control or noise gate in hardware. What
they do have is an ALSA switch called "Auto Gain Control" that you simply turn
off. That is exactly the difference from a ready-made USB conference microphone,
where the processing lives in firmware and cannot be disabled.

| Option | What | ~Price |
|---|---|---|
| **A. EM272 capsule + CM108 dongle** | The good one. Low self-noise, genuinely omnidirectional. | €35-40 |
| B. USB lavalier | One part: the same kind of chip in the plug, with an electret on a lead. Right architecture, cheap capsule. | €8-10 |
| C. dongle + 3.5 mm lavalier | Same result as B, two parts. | €10 |
| D. USB audio interface | Behringer UMC22 or similar. Clean converters, but bulky and expensive. Only worth it if you might tap the phono line one day. | €35 |

Omnidirectional is right here: you want the room, not a narrow beam on one
point. And the frequency colouring of a cheap capsule largely cancels out —
reference and query go through the same microphone.

**Stay away from** USB conference microphones (Anker PowerConf, eMeet, Jabra),
the ReSpeaker USB Mic Array, and anything with "AI noise cancelling" on the box.
Those do beamforming and noise suppression in firmware, and it cannot be turned
off. Also avoid *wireless* lavalier sets: compression and gain control live in
the wireless path.

### What to check when ordering

1. **A separate microphone input.** The right kind has **two** 3.5 mm jacks:
   green out, pink in. Dongles with only an output are useless. A single
   combined TRRS jack works, but then your microphone needs a TRRS plug too, or
   the capsule lands on the wrong ring.
2. **Class-compliant, no driver.** Everything in this price range is, but a
   bundled CD or download is a warning sign.
3. **No "noise cancelling" or "AI" in the description.**

"7.1 virtual surround" on the box is fine — that is a software trick for the
output and does not touch the input.

### The real check takes five minutes

`v2/pi/microphone.sh` does all of this for you. By hand:

```bash
arecord -l                                    # which card is it
amixer -c 1 controls                          # which controls exist
amixer -c 1 sset 'Auto Gain Control' off      # this one off
amixer -c 1 sset 'Mic' 80%
arecord -D plughw:1,0 -f S16_LE -r 44100 -c 1 -d 10 test.wav
```

A plain `Mic` control and an `Auto Gain Control` switch means it is the right
kind of chip. A device with no controls at all means the firmware is doing
something you cannot stop — send it back.

You will read on forums that levels are low with AGC off. That is not a problem
here: fingerprinting uses a **relative** threshold, subtracting the local noise
floor and looking at how far a peak rises above it. Quiet but clean is fine.
What ruins recognition is a pumping AGC and filtered-away noise, not low gain.

### On a Pi 5, it has to be USB

**The INMP441 on I2S does not work on a Pi 5.** Not a caveat but a known,
unresolved problem: the RP1 chip has a different I2S arrangement with separate
master and slave clock blocks, and the usual `googlevoicehat-soundcard` overlay
gives you silence or errors. It is open as an issue at Raspberry Pi themselves.
The exact same wiring works fine on a Pi 3 or a Zero 2 W.

<details>
<summary>INMP441 wiring, for a Zero 2 W or Pi 3/4</summary>

```
INMP441        Pi
-------        ----------
VDD  --------- 3V3    (pin 1)
GND  --------- GND    (pin 6)
SCK  --------- GPIO18 (pin 12, PCM_CLK)
WS   --------- GPIO19 (pin 35, PCM_FS)
SD   --------- GPIO20 (pin 38, PCM_DIN)
L/R  --------- GND    (selects the left channel)
```

In `/boot/firmware/config.txt`: `dtparam=i2s=on` with the
`googlevoicehat-soundcard` overlay. Two things on the first recording: the Pi
records in stereo with one silent channel (take the left), and in a 32-bit
format where the real data sits in the upper bits.
</details>

---

## Power

The panel runs off the Pi, which is tidier than two separate adapters — but it
depends on which supply you choose.

A Pi 5 limits its USB ports to **600 mA in total** by default. That is too
little for the CrowPanel, which wants 5 V at 1 A. The limit rises automatically
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

If you cannot get the official adapter, `usb_max_current_enable=1` in
`config.txt` raises the limit anyway — but then your supply really does have to
deliver 1.6 A, or it will collapse under load.

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

A Zero 2 W is smaller, cheaper and needs no cooling — and on a Zero the INMP441
works over I2S, so the microphone is six wires instead of a dongle. Its 512 MB
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

## The acoustic opening

The microphone sits in the plinth, so there needs to be a hole in the wall with
the capsule just behind it — placed, not glued in tight. Aim it into the room,
not downwards.

---

See [../BOM.md](../BOM.md) for version 1's parts, which still works on its own.
