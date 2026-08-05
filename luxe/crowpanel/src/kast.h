#pragma once

#include <Arduino.h>
#include <lvgl.h>

// ---------------------------------------------------------------------------
// De platenkast op het paneel — fase 6.
//
// Waarom dit een eigen bestand is en niet bij hoes.cpp: dat gaat over één hoes,
// die van de plaat die nu draait. Dit gaat over 549 hoezen waarvan er drie
// tegelijk in beeld staan, en dat is een heel ander probleem.
//
// De verdeling is dezelfde als overal in dit apparaat: de Pi weet dingen, het
// paneel toont ze. De namen komen in één keer binnen als platte tekst — 25 kB
// voor de hele kast, en regels splitsen op een tab kost een ESP32 bijna niets,
// waar 40 kB JSON ontleden seconden duurt. De plaatjes komen per stuk, op maat
// gemaakt door de Pi, en alleen die van de albums die je werkelijk ziet.
//
// Ophalen gebeurt nooit tijdens het draaien. Een knop die per stap honderd
// milliseconden staat te wachten op een netwerkverzoek voelt kapot; daarom
// schuift de tekst meteen mee en komen de hoezen na als je even stilhoudt.
// ---------------------------------------------------------------------------

// Formaat van de hoesjes. Alle drie even groot: dan hoeft er bij één stap maar
// één nieuwe op te halen in plaats van drie. Welke de huidige is zie je aan de
// rand eromheen en aan de titel eronder, niet aan het formaat.
#define KAST_PX 120

void kastBegin();

// De lijst ophalen. Eén keer genoeg; geeft false als het niet lukte.
bool kastLaad(const char *host, uint16_t poort);
bool kastGeladen();
int  kastAantal();

// Waar we nu staan, en verplaatsen. Loopt om aan beide uiteinden.
int  kastIndex();
void kastGa(int stappen);
void kastZet(int index);

// De eerste letter van de artiest ('#' als het geen A-Z is).
char kastLetterVan(int index);

// Naar het begin van de vorige of volgende letter springen. Met 549 albums is
// stap voor stap draaien geen doen; dit is de sprongindex van de webinterface,
// maar dan met de knop bediend.
void kastSpring(int richting);

// Tekst van het album op deze plek in de lijst.
const char *kastArtiest(int index);
const char *kastTitel(int index);

// Het releasenummer, om de hoes schermvullend op te kunnen halen.
uint16_t kastId(int index);

// Het plaatje voor een van de drie plekken (0 = links, 1 = midden, 2 = rechts),
// of nullptr zolang het er nog niet is.
const lv_img_dsc_t *kastHoes(int plek);

// Per lus aanroepen: haalt op wat er ontbreekt, maar alleen als je even stil
// bent. Geeft true als er iets veranderd is en het scherm opnieuw moet.
bool kastLus(const char *host, uint16_t poort);
