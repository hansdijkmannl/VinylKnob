# Webproef — herkenning uitproberen

Klein webinterfaceje om te zien of muziekherkenning met een microfoon werkt, en
hoe het eruitziet met hoes en al. Geen hardware nodig, niets te leren of vast te
leggen: knop indrukken, muziek laten spelen, kijken wat eruit komt.

De browser doet de microfoon (dan regelt macOS de toestemming via een gewone
pop-up), een klein servertje doet de herkenning. Dezelfde opname gaat naar
**twee motoren tegelijk**, zodat je ze rechtstreeks kunt vergelijken:

| | |
|---|---|
| **shazamio** | open-source client voor Shazam, geen sleutel nodig, maar Python-met-Rust en dus alleen op een computer |
| **AudD** | commerciele API die een rauwe audio-upload slikt — en dus ook rechtstreeks vanaf een ESP32 aan te roepen is |

Die vergelijking is de reden dat dit bestaat. Draait AudD net zo goed op jouw
platen, dan kan het uiteindelijke apparaat het zonder computer af en volstaat
een ESP32-bordje. Valt AudD tegen, dan is dat een argument om er een Raspberry
Pi bij te zetten die shazamio kan draaien.

## Draaien

```bash
cd /Volumes/Opslag/Apps/MarantzKnob/v2/webtest
/usr/bin/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Dan <http://localhost:8770> openen.

**Voor AudD heb je een sleutel nodig.** Haal er zelf een op bij audd.io — er is
een gratis proefniveau — en zet hem in een bestand `audd_token.txt` naast
`server.py`, of in de omgevingsvariabele `AUDD_TOKEN`. Zonder sleutel doet
alleen Shazam mee en zegt de pagina dat erbij.

**Let op: `/usr/bin/python3`**, dus Apple's Python 3.9, niet je nieuwere.
shazamio leunt op een Rust-extensie die op Python 3.14 segfault, en op pydub dat
de `audioop`-module nodig heeft die sinds Python 3.13 uit de standaardbibliotheek
is gehaald. Op 3.9 werkt alles zonder kunstgrepen.

## Wat het doet

De browser neemt 8 seconden op, maakt daar een gewone 16-bits WAV van in
JavaScript en stuurt die naar het servertje. Dat scheelt aan de serverkant elke
afhankelijkheid van ffmpeg. Terug komen twee resultaten naast elkaar, elk met artiest, titel, album, de
verstreken tijd en de hoes — rond getoond met een spindelgaatje in het midden,
zoals het op het uiteindelijke ronde scherm zou staan.

Ruisonderdrukking, echo-onderdrukking en automatische versterking staan bewust
uit. Die "slimme" verwerking knipt precies de details weg waar herkenning op
leunt.

## Verhouding tot `../recognizer/`

Twee verschillende dingen, en ze bijten elkaar niet:

- **Dit** beantwoordt "werkt herkenning met een microfoon, en ziet het er goed
  uit?" Het herkent alles, ook platen die je niet bezit, maar het vraagt een
  internetverbinding en een externe dienst per opzoeking.
- **`../recognizer/`** is de eigen, lokale fingerprint-database die na de eerste
  keer geen dienst meer nodig heeft. Dat is wat er uiteindelijk op de Pi draait.

In het uiteindelijke ontwerp doen ze allebei mee: een dienst als deze voor de
koude start, daarna de lokale database. Zie [../PLAN.md](../PLAN.md).
