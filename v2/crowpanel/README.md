# CrowPanel firmware

Everything the knob does by itself: telnet to the receiver, volume on the
encoder, inputs and the record shelf on the screen. For the **Elecrow CrowPanel
2.1" ESP32 Rotary Display** (ESP32-S3R8, 8 MB PSRAM, 16 MB flash).

```bash
pio run                  # build
pio run -t upload        # flash over USB
pio device monitor       # watch it boot
```

Currently 21.6% of flash and 31.6% of RAM, with about 1.8 MB of the 8 MB PSRAM
in use — two full-screen draw buffers, the sleeve, and the shelf's thumbnails.

## Flashing while it is mounted

Once the panel sits in the enclosure the USB connector is awkward to reach, but
it is already wired to the Pi. `flash-via-pi.sh` builds here, copies the four
binaries across, and runs esptool on the Pi:

```bash
export KNOB_PI=pi@knob.local
./flash-via-pi.sh
```

This works because the ESP32-S3 has native USB: esptool puts the chip into its
bootloader over that same connection, so the BOOT button is only needed if the
firmware already on the board has broken the USB stack.

## First boot

With no Wi-Fi stored the panel starts its own access point, **MarantzKnob-setup**.
Connect to it, open <http://192.168.4.1>, and fill in your network, your
receiver's address, and the list of inputs you actually use. It restarts onto
your network.

After that the same page lives at the panel's own address, and also inside the
Pi's web interface under the **Panel** tab — same settings, nicer surroundings.

Holding the knob for eight seconds clears the Wi-Fi and brings the access point
back. That is the way out if your router changes.

## Controls

| Gesture | Effect |
|---|---|
| turn | volume; in a list, the position |
| hold + turn | step through inputs |
| short press | mute, or confirm in a list |
| double press | jump to the favourite input |
| hold 1 s | amplifier on or off |
| hold 8 s | clear Wi-Fi, boot into setup mode |
| tap the input name | input list |
| tap the sleeve | the record shelf |
| tap the note | ask the Pi to listen now |

In the shelf, turning browses and **hold + turn jumps by letter** — with several
hundred albums, one at a time is no way to travel.

Two behaviours inherited from version 1: an input is only sent 250 ms after your
last step, so the receiver does not actually switch through every input on the
way; and turning while the button is held suppresses mute and power, so you
cannot switch the amplifier off by lingering.

## The files

| | |
|---|---|
| `config.h` | every pin on the board, and the build-time defaults |
| `marantz.{h,cpp}` | the telnet protocol, taken unchanged from version 1 |
| `settings.{h,cpp}` | settings in NVS, plus JSON for the web interface |
| `knob.{h,cpp}` | quadrature decoding and every gesture of the push button |
| `board.{h,cpp}` | display and touch bring-up, backlight |
| `pcf.{h,cpp}` | the PCF8574 port expander at 0x21 |
| `hoes.{h,cpp}` | the sleeve of what is playing, and its dominant colour |
| `kast.{h,cpp}` | the record shelf: the list, the thumbnails, the browsing |
| `brain.{h,cpp}` | asking the Pi what is playing |
| `web.{h,cpp}` | the panel's own settings page |
| `ui.h` | what a screen must be able to do |
| `ui_lvgl.cpp` | the real thing: five layers, LVGL |
| `ui_serial.cpp` | the same interface, printed to the serial monitor |
| `font_kastletter.c` | Montserrat at 130 px, A–Z only, generated |

## Testing without a screen

`ui.h` has two implementations. The reason is not tidiness: when this was
written the panel had not arrived, and the display was the only part that could
not be built without hardware on the desk. `ui_serial.cpp` prints the whole
interface to the serial monitor, so the entire control logic can be run and
tested with no display at all.

It still works, and it is still the fastest way to debug a gesture. Swap it in
via `build_src_filter` in `platformio.ini` and you get:

```
=== VOLUME ===
[turning] -38.5 dB   Turntable
[   idle] -38.5 dB   Turntable
```

Touches are simulated with single letters: `i` taps the input name, `a` the
sleeve, `c` confirms, `x` dismisses.

## Notes for anyone porting this

The ST7701 panel needs a long, panel-specific initialisation sequence, and the
touch controller is not in Elecrow's documentation. Neither is guessable — both
came out of their own example code:

<https://github.com/Elecrow-RD/CrowPanel-2.1inch-HMI-ESP32-Rotary-Display-480-480-IPS-Round-Touch-Knob-Screen>

Two things cost real time and are worth knowing:

- **`board_upload.flash_size` is what matters**, not `board_build.flash_size`.
  The latter does nothing, and getting it wrong gives you a boot loop with no
  useful message.
- **Arduino_GFX 1.3.1 is pinned** on purpose. Version 1.3.5 renamed the class
  this driver uses, and register 0x36's BGR bit differs between them.
