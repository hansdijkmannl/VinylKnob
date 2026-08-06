#pragma once

#include <Arduino.h>
#include <lvgl.h>

// ---------------------------------------------------------------------------
// De albumhoes ophalen en decoderen.
//
// De Pi levert hem al op maat (240x240 JPEG, zo'n 9 kB): schalen op een ESP32
// kost geheugen en tijd die hier beter besteed zijn, en de Pi doet het in
// tientallen milliseconden. Hier hoeft dus alleen gedecodeerd te worden.
//
// De uitkomst is een LVGL-plaatje in PSRAM dat blijft staan tot er een andere
// plaat komt. Ophalen gebeurt daarom precies één keer per plaat.
// ---------------------------------------------------------------------------

// Schermvullend: de hoes is de achtergrond van het volumescherm, niet een
// schijfje in het midden. 480x480x2 = 460 kB in PSRAM, naast de twee
// tekenbuffers van LVGL — samen nog geen anderhalve megabyte van de acht.
#define ARTWORK_PX 480

void artworkBegin();

// Haalt en decodeert de hoes van dit adres. Geeft true als er iets te tonen is.
bool artworkLoad(const char *host, uint16_t poort);

// Idem, maar voor een album dat je zelf in de kast hebt aangewezen. Zelfde
// buffer en zelfde accentberekening; alleen de bron verschilt.
bool artworkLoadAlbum(const char *host, uint16_t poort, uint16_t releaseId);

// Weggooien; toont weer het lege platenlabel.
void artworkClear();

// Het plaatje voor LVGL, of nullptr als er geen hoes is.
const lv_img_dsc_t *artworkImage();

// De opvallendste kleur uit de hoes, als 0xRRGGBB. Zonder hoes de standaard.
// Bedoeld voor de volumeboog, zodat die bij de plaat past.
uint32_t artworkAccent();
