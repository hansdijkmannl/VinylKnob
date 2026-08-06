# Interface mockup

A working sketch of how the CrowPanel will look and feel. Not code for the
device — this exists to judge the controls before a line of LVGL gets written.

```bash
open v2/mockup/index.html
```

Scroll your mouse wheel over the round screen to turn the knob, click on it for
a short press. The buttons underneath do the same.

## The control model

With rotation, press *and* touch, nothing has to be modal. That is the heart of
this design: **turning is always volume**, on every screen, without exception.

| The knob | |
|---|---|
| turn | volume — always, never anything else |
| short press | mute on/off |
| double press | straight to the turntable |
| hold | amplifier on/off |

| The screen | |
|---|---|
| tap the input name | input list; turning steps through it |
| tap the sleeve | browse the record shelf |
| tap to confirm | or do nothing: after a few seconds it falls back |

Everything you want to do without looking is on the knob. Everything you look at
the screen for anyway is on the screen.

## What the design is trying to do

**The sleeve is the picture, not a number.** The volume figure appears only
while you turn and disappears again after a second and a half. Otherwise there
is a number permanently sitting over your record label.

**The arc lies on the rim**, exactly where your fingers take hold of the knob
ring. That makes the arc the position indicator, and you need no absolute
potentiometer to see how loud it is.

**The sleeve is cropped round**, with a spindle hole in the middle. On a round
screen that reads as intent rather than as a crop.

**The accent colour comes from the sleeve.** In the mockup that colour is in the
fake data; in reality you take the dominant colour from the image. It costs
little computation and the device looks different for every record.

**Falling back instead of confirming.** Every choice screen returns to the
volume on its own. There is no "cancel" anywhere.

## What is wrong with the mockup

- The sleeves are generated colour gradients, not real album artwork.
- The QR code is fake; only the proportions are right.
- The bezel is a drawing. How that knob really turns is still the one thing you
  cannot judge on a screen — for that the board has to be ordered.
