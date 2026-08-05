# CrowPanel-firmware — fase 2

De bediening: telnet naar de SR7015, volume met de knop, ingang via het scherm.
Voor het **Elecrow CrowPanel 2.1" ESP32 Rotary Display** (ESP32-S3R8).

```bash
pio run                  # bouwen
pio run -t upload        # flashen over USB-C
pio device monitor
```

Bouwt schoon: 11% flash, 14% RAM. Er is nog geen hardware getest — dit is
geschreven vóór het paneel binnen was.

## Wat af is

| | |
|---|---|
| `marantz.{h,cpp}` | het protocol, ongewijzigd overgenomen uit versie 1 |
| `settings.{h,cpp}` | instellingen in NVS, idem |
| `knob.{h,cpp}` | quadratuur plus alle gebaren van de drukknop |
| `main.cpp` | wifi, de schermtoestanden, en wat elk gebaar doet |
| `pcf.{h,cpp}` | de PCF8574 op 0x21 |
| `config.h` | alle pinnen van het bord |

## Wat er nog niet in zit, en waarom

**De displaydriver.** Het ST7701-paneel heeft een lange, paneelspecifieke
initialisatiereeks, en de aanraakchip staat niet in de documentatie van Elecrow.
Die twee dingen zijn niet te raden — ze horen uit hun eigen voorbeeldcode te
komen:

<https://github.com/Elecrow-RD/CrowPanel-2.1inch-HMI-ESP32-Rotary-Display-480-480-IPS-Round-Touch-Knob-Screen>

Daarom is het scherm hier een **interface** (`ui.h`) met twee implementaties.
`ui_serial.cpp` schrijft naar de seriële monitor en is nu actief; daarmee draait
en test je de hele bediening zonder paneel. `ui_lvgl.cpp` tekent het straks echt
volgens [../mockup/](../mockup/) — omwisselen doe je in `build_src_filter` in
`platformio.ini`.

Die scheiding is niet uit netheid maar omdat het displaygedeelte het enige is
dat pas met hardware op tafel te schrijven valt. De rest is nu al af.

## Zonder scherm testen

Flash het, open de monitor, en draai aan de knop. Je ziet regels als:

```
=== VOLUME ===
[draait] -38.5 dB   Platenspeler
[  rust] -38.5 dB   Platenspeler
```

Aanrakingen boots je na met een letter in de monitor: `i` = tik op de
ingangsnaam, `a` = tik op de hoes, `c` = bevestigen, `x` = wegklikken.

## Bediening

| Gebaar | Effect |
|---|---|
| draaien | volume; in de ingangenlijst de positie |
| kort drukken | mute aan/uit, of bevestigen in een keuzescherm |
| dubbel drukken | direct naar de favoriete ingang |
| vasthouden (1 s) | versterker aan/uit |
| vasthouden (8 s) | wifi wissen, opstarten in setup-modus |
| tik op de ingangsnaam | ingangenlijst |

Twee dingen die uit versie 1 meekomen en hier net zo goed gelden: een ingang
wordt pas 250 ms na je laatste stap verstuurd, zodat de receiver niet alle
tussenliggende ingangen aantikt. En zodra je tijdens het indrukken draait,
worden mute en aan/uit onderdrukt.

## Wat hierna komt

Fase 4: de Pi als brein. Het paneel vraagt dan bij een gebeurtenis — ingang gaat
naar phono, of geluid begint na stilte — om een opzoeking, en krijgt artiest,
album en een hoes terug. Zie [../brein/](../brein/), dat draait nu al op je Mac.
